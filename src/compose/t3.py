"""t3.py -- the third table tier: relations the orchestrator chased.

T1 (entities) and T2 (edges) are extracted from the CodeQL database and
state only what is written in the source. Some dependencies are not
written anywhere a syntactic query can see them, and are left to the
orchestrator:

- a type-erased value handed on through calls or locals: `av_log(void
  *avcl)` only forwards `avcl` to `av_vlog`, whose body reads it as
  AVClass, so `av_log` depends on AVClass with no cast in its own body;
- a polymorphic pair joined through such slots, base and derived;
- which type-minting macros are templates (`GIT_HASHMAP_STRUCT`) rather
  than one-off definitions (`FF_PAD_STRUCTURE`).

The orchestrator writes what it accepts into two CSVs under the config's
`t3_dir` (relative to `state_dir`), tracked with the campaign:

`chased_casts.csv`, one dependency per row:

    kind          erased_arg | erased_field | base_derived
    slot_name     function (erased_arg) or owner struct (erased_field)
    slot_def_file its definition file
    slot_member   parameter position, or field path as `fields.csv` spells it
    type_name     the type the slot holds, or the base (base_derived)
    type_def_file
    derived_name  base_derived only
    derived_def_file
    op            add (default, also when the column is absent) | drop

`type_generators.csv`, one generated entity per row:

    generator_macro, generator_def_file
    derived_kind  type | macro
    derived_name, derived_def_file

Every `add` row becomes one DAG edge (`deps_dag`): a function depends on
what its erased parameter holds, what an erased field holds on the field's
owner (a derived type on its base), a derived type on its base, a
generated type or macro on its generator. A `drop` row removes a cast edge
wavefront derives itself from T2 and the orchestrator rejected: a
parameter or field read as a type it is not polymorphic over (an
alignment pun, a slot one file reuses), or a cast between two types that
are no pair. Only cast edges can be dropped; field and signature edges are
declarations. This module checks the NODES each row
names -- that they exist, at those files, with the right shape (an erased
slot really is `void *` / `void **`). It does not check the relation
itself: whether the cast happens, or the chain that carries it, is the
orchestrator's judgement and the reason the tier exists. A failing row is
an error, never skipped: the tables are input, like the config.

The checks are the same in every mode, and the records (`types_manifest`,
`import_closure`) see every row. API mode only PROJECTS: `load(...,
api_paths)` leaves out the rows whose nodes are not public, as the DAG does
for every other whole-program relation.
"""
from __future__ import annotations

import csv
import functools
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

CHASED = "chased_casts.csv"
GENERATORS = "type_generators.csv"
TABLES = (CHASED, GENERATORS)

CHASED_COLS = ("kind", "slot_name", "slot_def_file", "slot_member",
               "type_name", "type_def_file", "derived_name", "derived_def_file",
               "op")
#: Columns a header may leave out: `op` defaults to `add`.
OPTIONAL_COLS = ("op",)
#: Earlier spellings a header may still use, read as their current names.
LEGACY_COLS = {"base_name": "type_name", "base_def_file": "type_def_file"}
GENERATOR_COLS = ("generator_macro", "generator_def_file",
                  "derived_kind", "derived_name", "derived_def_file")

KINDS = ("erased_arg", "erased_field", "base_derived")
OPS = ("add", "drop")
DERIVED_KINDS = ("type", "macro")

#: The T1 tables a check reads.
_T1 = ("types.csv", "functions.csv", "params.csv", "fields.csv", "macros.csv")

Key = tuple[str, str]

_DIR: Path | None = None


def configure(t3_dir: Path | None) -> None:
    """Select the T3 directory every composer reads (`Layout` does this from
    the config's `t3_dir`). ``None``: no third tier."""
    global _DIR
    _DIR = None if t3_dir is None else Path(t3_dir)


def configured() -> Path | None:
    return _DIR


def files() -> list[Path]:
    """The T3 CSVs present in the configured directory (cache inputs)."""
    return [] if _DIR is None else [p for p in (_DIR / n for n in TABLES) if p.is_file()]


class Tables(NamedTuple):
    #: `{(function, def_file): {(type, type_def_file)}}`
    erased_args: dict[Key, frozenset[Key]]
    #: `{(owner, def_file): {(field path, type, type_def_file)}}`, the path
    #: canonical to its declaring struct
    erased_fields: dict[Key, frozenset[tuple[str, str, str]]]
    #: `{(derived, def_file): {(type, type_def_file)}}`
    bases: dict[Key, frozenset[Key]]
    #: `{(macro, def_file): {(kind, name, def_file)}}`
    generates: dict[Key, frozenset[tuple[str, str, str]]]
    #: `drop` rows. `{(function, def_file): {(position, type, type_def_file)}}`
    drop_args: dict[Key, frozenset[tuple[str, str, str]]] = {}
    #: `{(owner, def_file): {(field path, type, type_def_file)}}`
    drop_fields: dict[Key, frozenset[tuple[str, str, str]]] = {}
    #: `{(derived, def_file): {(type, type_def_file)}}`
    drop_bases: dict[Key, frozenset[Key]] = {}


EMPTY = Tables({}, {}, {}, {})


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or ()), list(reader)


def _split(cell: str) -> list[str]:
    return [d for d in (cell or "").split("|") if d]


class _Inventory:
    """The T1 facts a check consults, indexed once per load."""

    def __init__(self, t1: Path) -> None:
        self.t1 = t1
        self._loaded: dict[str, list[dict]] = {}

    def table(self, name: str) -> list[dict] | None:
        if name not in self._loaded:
            p = self.t1 / name
            self._loaded[name] = _rows(p)[1] if p.is_file() else None
        return self._loaded[name]

    @functools.cached_property
    def types(self) -> dict[str, dict[str, set[str]]]:
        """`{name: {def_file: decl files}}`. A typedef naming another tag is
        an alias, not an entity, and is left out."""
        out: dict[str, dict[str, set[str]]] = defaultdict(dict)
        for r in self.table("types.csv") or ():
            if r.get("kind") == "typedef" and r.get("aliases"):
                continue
            out[r["name"]].setdefault(r.get("def_file") or "", set()).update(
                _split(r.get("decl_files")))
        return out

    @functools.cached_property
    def functions(self) -> dict[Key, set[str]]:
        out: dict[Key, set[str]] = defaultdict(set)
        for r in self.table("functions.csv") or ():
            out[(r["name"], r.get("def_file") or "")].update(_split(r.get("decl_files")))
        return out

    @functools.cached_property
    def params(self) -> dict[tuple[str, str, str], dict]:
        return {(r["function_name"], r.get("function_def_file") or "", r["position"]): r
                for r in self.table("params.csv") or ()}

    @functools.cached_property
    def fields(self) -> dict[Key, dict[str, dict]]:
        out: dict[Key, dict[str, dict]] = defaultdict(dict)
        for r in self.table("fields.csv") or ():
            out[(r["struct_name"], r.get("struct_def_file") or "")][r["field_name"]] = r
        return out

    @functools.cached_property
    def macros(self) -> set[Key]:
        return {(r["name"], r.get("def_file") or "") for r in self.table("macros.csv") or ()
                if r.get("name")}

    def type_error(self, name: str, df: str) -> str | None:
        defs = self.types.get(name)
        if not defs:
            return f"type {name!r} is not in t1/types.csv"
        if df not in defs or (df == "" and any(defs.keys() - {""})):
            have = sorted(d for d in defs if d) or ['""']
            return f"type {name!r} is not defined in {df or '<none>'!r} (defined in {have})"
        return None

    def resolve_field(self, owner: Key, path: str) -> tuple[Key, str] | None:
        """`(owner, path)` canonical to the struct that DECLARES the field.

        `fields.csv` already spells a member of an anonymous aggregate as a
        dotted path from its named owner (`git_blob` / `data.odb`). A member
        of a TAGGED embedded struct belongs to that struct, so `S` / `in.p`
        is rewritten to `Inner` / `p` by following `in`'s declared type."""
        flds = self.fields.get(owner)
        if not flds:
            return None
        if path in flds:
            return owner, path
        head, _, rest = path.partition(".")
        r = flds.get(head)
        if not rest or r is None or (r.get("ptr_depth") or "0") != "0":
            return None
        tag = r["field_type"]
        for q in ("const ", "volatile ", "struct ", "union "):
            tag = tag.replace(q, "")
        tag = tag.strip()
        defs = [d for d in self.types.get(tag, {}) if (tag, d) in self.fields]
        return self.resolve_field((tag, defs[0]), rest) if len(defs) == 1 else None

    # -- publication (API mode) ------------------------------------------
    def type_public(self, k: Key, api: frozenset[str]) -> bool:
        decls = self.types.get(k[0], {}).get(k[1], set())
        return k[1] in api or bool(decls & api)

    def function_public(self, k: Key, api: frozenset[str]) -> bool:
        return k[1] in api or bool(self.functions.get(k, set()) & api)


def _legacy(have: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    """A header in an earlier spelling (`base_name`), read as the current one."""
    if not any(c in LEGACY_COLS for c in have):
        return have, rows
    rename = lambda d: {LEGACY_COLS.get(k, k): v for k, v in d.items()}
    return [LEGACY_COLS.get(c, c) for c in have], [rename(r) for r in rows]


def _check_header(path: Path, have: list[str], want: tuple[str, ...]) -> list[str]:
    missing = [c for c in want if c not in have and c not in OPTIONAL_COLS]
    return [f"{path.name}: missing column(s) {missing}"] if missing else []


def _chased(path: Path, inv: _Inventory, api: frozenset[str] | None,
            errs: list[str]) -> tuple[dict, ...]:
    """`(args, fields, bases)` of the `add` rows, then the same three of the
    `drop` rows; `drop` args keep the parameter position."""
    adds = (defaultdict(set), defaultdict(set), defaultdict(set))
    drops = (defaultdict(set), defaultdict(set), defaultdict(set))
    have, rows = _legacy(*_rows(path))
    errs += _check_header(path, have, CHASED_COLS)
    if any(e.startswith(path.name) for e in errs):
        return (*adds, *drops)
    seen: dict[tuple, tuple[str, str]] = {}         # edge -> (op, where)
    for line, r in enumerate(rows, start=2):
        at = f"{path.name}:{line}"
        v = {c: (r.get(c) or "").strip() for c in CHASED_COLS}
        kind, op = v["kind"], v["op"] or "add"
        if kind not in KINDS:
            errs.append(f"{at}: kind {kind!r} is not one of {list(KINDS)}")
            continue
        if op not in OPS:
            errs.append(f"{at}: op {op!r} is not one of {list(OPS)}")
            continue
        edge = (kind, v["slot_name"], v["slot_def_file"], v["slot_member"],
                v["type_name"], v["type_def_file"], v["derived_name"],
                v["derived_def_file"])
        prev = seen.setdefault(edge, (op, at))
        if prev[0] != op:
            errs.append(f"{at}: {op} contradicts {prev[0]} of the same edge at {prev[1]}")
            continue
        args, flds, bases = adds if op == "add" else drops
        slot_cols = ("slot_name", "slot_def_file", "slot_member")
        need = ["type_name"] + (["derived_name"] if kind == "base_derived" else
                                ["slot_name", "slot_member"])
        empty = [c for c in need if not v[c]]
        stray = ([c for c in slot_cols if v[c]] if kind == "base_derived" else
                 [c for c in ("derived_name", "derived_def_file") if v[c]])
        if empty or stray:
            errs.append(f"{at}: {kind} needs {need}"
                        + (f", missing {empty}" if empty else "")
                        + (f", must leave {stray} empty" if stray else ""))
            continue
        base = (v["type_name"], v["type_def_file"])
        bad = inv.type_error(*base)
        if bad:
            errs.append(f"{at}: type: {bad}")
            continue
        if kind == "base_derived":
            derived = (v["derived_name"], v["derived_def_file"])
            bad = inv.type_error(*derived)
            if bad:
                errs.append(f"{at}: derived: {bad}")
            elif derived == base:
                errs.append(f"{at}: base and derived are the same type")
            elif api is not None and not (inv.type_public(base, api)
                                          and inv.type_public(derived, api)):
                pass                            # not public: no API edge
            else:
                bases[derived].add(base)
            continue
        owner = (v["slot_name"], v["slot_def_file"])
        if kind == "erased_arg":
            if inv.table("params.csv") is None:
                errs.append(f"{at}: t1/params.csv is missing; run extract-ql")
                continue
            if owner not in inv.functions:
                errs.append(f"{at}: function {owner[0]!r} is not defined in "
                            f"{owner[1] or '<none>'!r} (t1/functions.csv)")
                continue
            p = inv.params.get((*owner, v["slot_member"]))
            if p is None:
                errs.append(f"{at}: {owner[0]} has no parameter {v['slot_member']!r}")
            elif p.get("is_erased") != "true":
                errs.append(f"{at}: parameter {v['slot_member']} of {owner[0]} is "
                            f"{p.get('param_type')!r}, not void * / void **")
            elif api is not None and not inv.function_public(owner, api):
                pass                            # not public: no API edge
            elif op == "drop":
                args[owner].add((v["slot_member"], *base))
            else:
                args[owner].add(base)
            continue
        if inv.table("fields.csv") and "is_erased" not in inv.table("fields.csv")[0]:
            errs.append(f"{at}: t1/fields.csv has no is_erased column; run extract-ql")
            continue
        bad = inv.type_error(*owner)
        if bad:
            errs.append(f"{at}: owner: {bad}")
            continue
        got = inv.resolve_field(owner, v["slot_member"])
        if got is None:
            errs.append(f"{at}: {owner[0]} has no field {v['slot_member']!r} (t1/fields.csv)")
            continue
        decl, fpath = got
        f = inv.fields[decl][fpath]
        # The slots wavefront records variants for: a pointer that names no
        # struct -- `void *`, or a scalar pointer read through a cast
        # (`uint8_t *data` read as `AVStereo3D`).
        erased = f.get("is_erased") == "true" or (
            f.get("is_scalar") == "true" and (f.get("ptr_depth") or "0") != "0")
        if not erased:
            errs.append(f"{at}: field {decl[0]}.{fpath} is {f.get('field_type')!r}, "
                        f"not void * / void ** or a scalar pointer")
        elif api is not None and decl[1] not in api:
            pass                                # not a public layout: no API edge
        else:
            flds[decl].add((fpath, *base))
    return (*adds, *drops)


def _generators(path: Path, inv: _Inventory, api: frozenset[str] | None,
                errs: list[str]) -> dict:
    gens: dict[Key, set[tuple[str, str, str]]] = defaultdict(set)
    have, rows = _rows(path)
    errs += _check_header(path, have, GENERATOR_COLS)
    if any(e.startswith(path.name) for e in errs):
        return gens
    for line, r in enumerate(rows, start=2):
        at = f"{path.name}:{line}"
        v = {c: (r.get(c) or "").strip() for c in GENERATOR_COLS}
        empty = [c for c in ("generator_macro", "derived_kind", "derived_name") if not v[c]]
        if empty:
            errs.append(f"{at}: missing {empty}")
            continue
        macro = (v["generator_macro"], v["generator_def_file"])
        if macro not in inv.macros:
            errs.append(f"{at}: macro {macro[0]!r} is not defined in "
                        f"{macro[1] or '<none>'!r} (t1/macros.csv)")
            continue
        dk, derived = v["derived_kind"], (v["derived_name"], v["derived_def_file"])
        if dk not in DERIVED_KINDS:
            errs.append(f"{at}: derived_kind {dk!r} is not one of {list(DERIVED_KINDS)}")
            continue
        bad = (inv.type_error(*derived) if dk == "type" else
               None if derived in inv.macros else
               f"macro {derived[0]!r} is not defined in {derived[1] or '<none>'!r}")
        if bad:
            errs.append(f"{at}: derived: {bad}")
        elif dk == "macro" and derived == macro:
            errs.append(f"{at}: a macro does not generate itself")
        elif api is not None and macro[1] not in api:
            pass                                # not exported: no API edge
        else:
            gens[macro].add((dk, *derived))
    return gens


@functools.lru_cache(maxsize=8)
def _load(t3: str, t1: str, api: frozenset[str] | None, _stamp: tuple) -> Tables:
    d, inv, errs = Path(t3), _Inventory(Path(t1)), []
    args, flds, bases, gens = {}, {}, {}, {}
    dargs, dflds, dbases = {}, {}, {}
    if (d / CHASED).is_file():
        args, flds, bases, dargs, dflds, dbases = _chased(d / CHASED, inv, api, errs)
    if (d / GENERATORS).is_file():
        gens = _generators(d / GENERATORS, inv, api, errs)
    if errs:
        mode = " (API mode)" if api is not None else ""
        raise SystemExit(f"invalid T3 tables in {d}{mode}:\n  " + "\n  ".join(errs))

    def freeze(m: dict) -> dict:
        return {k: frozenset(v) for k, v in sorted(m.items())}
    return Tables(freeze(args), freeze(flds), freeze(bases), freeze(gens),
                  freeze(dargs), freeze(dflds), freeze(dbases))


def load(t1: Path, api_paths=None) -> Tables:
    """The configured T3 tables, checked against `t1`. With `api_paths`
    (API mode), projected onto the public API: rows naming a non-public
    node are left out, never an error. Empty when no `t3_dir` is configured
    or it holds no tables. Raises `SystemExit` naming every failing row."""
    if _DIR is None:
        return EMPTY
    stamp = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.is_file() else None
                  for p in [_DIR / n for n in TABLES] + [Path(t1) / n for n in _T1])
    if stamp[0] is None and stamp[1] is None:
        return EMPTY
    api = None if api_paths is None else frozenset(api_paths)
    return _load(str(_DIR), str(t1), api, stamp)
