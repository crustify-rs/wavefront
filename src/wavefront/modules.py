"""A config's ``modules``: the groups a schedule orders its units in.

``modules``, optional, lists module records, ``{"name": ..., "files": [file
entries]}``, each file entry as ``schedule_seeds`` writes one. A module claims
the units whose home, their defining file or, with none, their declaration, is
one of its files, as its items narrow them; a unit two modules claim is an
error, and one none claims is a group of its own. An item names a unit its
file is home to: one its file only declares, homed elsewhere, is an error. The schedule orders the
groups, cutting their cycles, and each module's units within it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wavefront.dag import NodeKey
from wavefront.selection import Entry, _fail, file_entry

MODULES = "modules"
_HINT = ('`modules` is a list of module records {"name": ..., "files": [file '
         'entries]}, each file entry as `schedule_seeds` writes one.')


@dataclass
class Module:
    name: str
    entries: list[Entry]

    def claims(self, key: NodeKey) -> bool:
        name, home, kind = key
        return any(e.path == (home or "") and e.selects(name, kind, home or "", set())
                   for e in self.entries)


def load(config: dict, repo_root: Path) -> list[Module]:
    """The config's ``modules``, validated; empty without any."""
    from compose.scope_manifest import targeted_candidates

    if MODULES not in config:
        return []
    records = config[MODULES]
    if not isinstance(records, list) or not records:
        _fail(f"`modules` must be a non-empty list. {_HINT}")
    closure = set(targeted_candidates(config, repo_root))
    out: list[Module] = []
    seen: set[str] = set()
    for i, rec in enumerate(records):
        where = f"modules[{i}]"
        if (not isinstance(rec, dict) or set(rec) - {"name", "files", "_comment"}
                or not isinstance(rec.get("name"), str) or not rec["name"]
                or not isinstance(rec.get("files"), list) or not rec["files"]):
            _fail(f"{where}: {rec!r} is no module record. {_HINT}")
        if rec["name"] in seen:
            _fail(f"{where}: module {rec['name']!r} is named twice")
        seen.add(rec["name"])
        entries = [e for j, f in enumerate(rec["files"])
                   for e in file_entry(f, f"{where} ({rec['name']}) files[{j}]",
                                       repo_root, closure)]
        out.append(Module(rec["name"], entries))
    return out


def check(modules: list[Module], decls: dict[NodeKey, set[str]], units) -> None:
    """Refuse an item that would claim a unit its file only declares: a unit
    is claimed at its home, the file that defines it or, with none, its
    canonical declaration, so the item would claim nothing."""
    homes: dict[tuple[str, str, str], set[str]] = {}
    for key in units:
        name, home, kind = key
        for f in decls.get(key, set()) | {home or ""}:
            homes.setdefault((f, name, kind), set()).add(home or "")
    bad = []
    for m in modules:
        for e in m.entries:
            for name, kind in sorted(e.included):
                found = homes.get((e.path, name, kind), set())
                if found and e.path not in found:
                    bad.append(f"  - {m.name}: {e.path} items.included: {kind} "
                               f"{name} is homed in {', '.join(sorted(found))}")
    if bad:
        _fail(f"{len(bad)} module item(s) name a unit their file only declares; "
              f"a module claims a unit by the file that defines it, so list "
              f"that file instead:\n" + "\n".join(bad[:40])
              + (f"\n  ... and {len(bad) - 40} more" if len(bad) > 40 else ""))


def owners(modules: list[Module], units) -> dict[NodeKey, int]:
    """The module claiming each unit, by index; a unit two modules claim is
    refused, and one none claims is left out."""
    out: dict[NodeKey, int] = {}
    shared: dict[NodeKey, list[str]] = {}
    for key in units:
        hits = [i for i, m in enumerate(modules) if m.claims(key)]
        if len(hits) == 1:
            out[key] = hits[0]
        elif hits:
            shared[key] = [modules[i].name for i in hits]
    if shared:
        lines = [f"  - {k[2]} {k[0]} ({k[1] or '?'}): {', '.join(v)}"
                 for k, v in sorted(shared.items(), key=lambda kv: str(kv[0]))[:40]]
        more = (f"\n  ... and {len(shared) - 40} more" if len(shared) > 40 else "")
        raise SystemExit(f"schedule: {len(shared)} unit(s) belong to several "
                         f"modules:\n" + "\n".join(lines) + more)
    return out
