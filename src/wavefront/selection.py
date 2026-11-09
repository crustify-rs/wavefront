"""A config's ``schedule_seeds``: the units a schedule starts from.

``schedule_seeds`` lists file entries. Each seeds the units its file defines or
declares; a file entry is a path, a directory with a trailing slash, or
``{"path": ..., "items": {"included": [...], "excluded": [...]}}`` whose items,
each ``{"name": ..., "kind": ...}``, narrow what it selects of its file. An
item's kind is what the entity is in C (:mod:`wavefront.kinds`): ``function``,
``global``, ``macro``, ``struct``, ``union``, ``enum`` or ``typedef``. A config without ``schedule_seeds`` seeds every unit. The selection never
changes the order: it is computed over every unit of the closure, and a
schedule keeps its seeds, and every unit they depend on, in it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from wavefront import kinds as c_kinds
from wavefront.dag import NodeKey

SCHEDULE = "schedule_seeds"
_HINT = (
    '`schedule_seeds` is a list of file entries: a path, a directory with a '
    'trailing slash, or {"path": ..., "items": {"included": [...], '
    '"excluded": [...]}}, each item {"name": ..., "kind": ...}, its kind one '
    'of ' + ", ".join(c_kinds.KINDS) + '.')


def _fail(message: str):
    raise SystemExit(f"wavefront-config.json: {message}")


@dataclass
class Entry:
    """One listed file and the items that narrow what it selects, each
    ``(name, namespace)``, the key the graph matches; ``kinds`` keeps the kind
    an item gave, which :func:`check` holds the unit to."""
    path: str
    included: set[tuple[str, str]] = field(default_factory=set)
    excluded: set[tuple[str, str]] = field(default_factory=set)
    kinds: dict[tuple[str, str], str] = field(default_factory=dict)

    def selects(self, name: str, kind: str, home: str, decls: set[str]) -> bool:
        if self.path != home and self.path not in decls:
            return False
        if (name, kind) in self.excluded:
            return False
        return not self.included or (name, kind) in self.included


def _items(value, where: str) -> tuple[set, set, dict]:
    if not isinstance(value, dict) or not set(value) <= {"included", "excluded"}:
        _fail(f"{where}: `items` must be an object of `included` and "
              f"`excluded` lists. {_HINT}")
    out = []
    given: dict[tuple[str, str], str] = {}
    for part in ("included", "excluded"):
        entries = value.get(part) or []
        if not isinstance(entries, list):
            _fail(f"{where}: `items.{part}` must be a list")
        pairs = set()
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {"name", "kind"}
                    or not isinstance(entry["name"], str) or not entry["name"]
                    or entry["kind"] not in c_kinds.KINDS):
                _fail(f'{where}: each item is {{"name": ..., "kind": ...}}, its '
                      f'kind one of {", ".join(c_kinds.KINDS)}; got {entry!r}')
            key = (entry["name"], c_kinds.namespace(entry["kind"]))
            pairs.add(key)
            given[key] = entry["kind"]
        out.append(pairs)
    if out[0] & out[1]:
        name, kind = sorted(out[0] & out[1])[0]
        _fail(f"{where}: both lists name {given.get((name, kind), kind)} {name}")
    return out[0], out[1], given


def file_entry(rec, where: str, repo_root: Path, closure: set[str]) -> list[Entry]:
    """One file entry, validated, as an entry per file it names: a path, a
    directory with a trailing slash, or ``{"path", "items"}``. A file lies
    within the closure; a directory names the closure's files under it, and
    at least one."""
    if isinstance(rec, str):
        path, items = rec, None
    elif (isinstance(rec, dict) and set(rec) <= {"path", "items"}
            and isinstance(rec.get("path"), str)):
        path, items = rec["path"], rec.get("items")
    else:
        _fail(f"{where}: {rec!r} is no file entry. {_HINT}")
    if not path:
        _fail(f"{where}: a file entry needs a path")
    if items is not None and path.endswith("/"):
        _fail(f"{where}: {path} is a directory; items narrow one file")
    included, excluded, given = (_items(items, f"{where} {path}")
                                 if items is not None else (set(), set(), {}))
    if path.endswith("/"):
        paths = sorted(f for f in closure if f.startswith(path))
        if not paths:
            _fail(f"{where}: {path} holds no file of the closure")
    elif path not in closure:
        _fail(f"{where}: {path} is no file of the closure")
    else:
        paths = [path]
    return [Entry(p, set(included), set(excluded), dict(given)) for p in paths]


def load(config: dict, repo_root: Path) -> list[Entry] | None:
    """The config's ``schedule_seeds`` as file entries, validated: every file lies
    within the closure. ``None`` when the config lists none: every unit is a
    seed."""
    from compose.scope_manifest import closure_candidates

    if SCHEDULE not in config:
        return None
    records = config[SCHEDULE]
    if not isinstance(records, list) or not records:
        _fail(f"`schedule_seeds` must be a non-empty list. {_HINT}")
    closure = set(closure_candidates(config, repo_root))
    out: list[Entry] = []
    for i, rec in enumerate(records):
        out.extend(file_entry(rec, f"schedule_seeds[{i}]", repo_root, closure))
    return out


def declarations(inventory: dict) -> dict[NodeKey, set[str]]:
    """The declaration files of every entity the closure owns, keyed as the
    dag keys its node: by its home, the defining file or, without one, its
    canonical declaration. A tag's declaration-only rows fold into its
    definitions, as the graph folds them. A macro a closure header defines is
    in the `closure` section but not owned (`compose.scope.owned_macro`): it
    is a unit all the same, and an item names it through the units."""
    from compose import scope as compose_scope

    doc = compose_scope._doc(inventory)
    out: dict[NodeKey, set[str]] = defaultdict(set)
    floating: dict[str, set[str]] = defaultdict(set)
    for bucket, kind in (("types", "type"), ("functions", "symbol"),
                         ("globals", "symbol"), ("macros", "symbol")):
        owned = compose_scope.owned_entities(doc, bucket)
        for e in doc.get(compose_scope.CLOSURE, {}).get(bucket, []):
            name = compose_scope.entry_tag(e)
            if (name, e.get("defined_in") or "") not in owned:
                continue
            decls = set(e.get("declared_in") or ())
            if kind == "type" and not e.get("defined_in"):
                floating[name] |= decls
            home = compose_scope.origin_key(name, e.get("defined_in") or None,
                                            sorted(decls))[1]
            out[(name, home, kind)] |= decls
    for (name, home, kind), decls in out.items():
        if kind == "type":
            decls |= floating.get(name, set())
    return out


def check(entries: list[Entry], decls: dict[NodeKey, set[str]],
          units=(), kind_of=None) -> None:
    """Refuse an item that names no owned entity or unit its file defines
    or declares: a misspelt name, or the wrong namespace; and, with
    ``kind_of`` (a unit's kind by its key), one that names a unit as a kind it
    is not: a struct as a union."""
    known: dict[str, set[tuple[str, str]]] = defaultdict(set)
    actual: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for (name, home, ns), files in decls.items():
        for f in files | {home}:
            known[f].add((name, ns))
    for key in units:
        name, home, ns = key
        known[home or ""].add((name, ns))
    for key, kind in (kind_of or {}).items():
        if kind is None:
            continue
        name, home, ns = key
        for f in decls.get(key, set()) | {home or ""}:
            actual[(f, name, ns)].add(kind)
    bad, wrong = [], []
    for e in entries:
        for part, items in (("included", e.included), ("excluded", e.excluded)):
            for item in sorted(items):
                name, ns = item
                given = e.kinds[item]
                if item not in known[e.path]:
                    bad.append(f"  - {e.path} items.{part}: {given} {name}")
                    continue
                found = actual.get((e.path, name, ns))
                if found and given not in found:
                    wrong.append(f"  - {e.path} items.{part}: {name} is a "
                                 f"{' or '.join(sorted(found))}, not a {given}")
    if bad:
        _fail(f"{len(bad)} item(s) name no owned entity their file "
              f"defines or declares:\n" + "\n".join(bad[:40]))
    if wrong:
        _fail(f"{len(wrong)} item(s) give the wrong kind:\n"
              + "\n".join(wrong[:40]))


def select(entries: list[Entry] | None, units, decls) -> set[NodeKey]:
    """The units the entries select: those a listed file defines or declares,
    as its items narrow it; every unit without entries."""
    if entries is None:
        return set(units)
    by_file: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        by_file[e.path].append(e)
    out = set()
    for key in units:
        name, home, kind = key
        files = decls.get(key, set()) | {home or ""}
        if any(e.selects(name, kind, home or "", files)
               for f in files for e in by_file.get(f, ())):
            out.add(key)
    return out
