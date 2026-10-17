"""slot_casts.py -- join slot edges into slot-mediated cast pairs.

`edges/arg_casts.ql` and `edges/field_casts.ql` emit three kinds of edge
between named types and value SLOTS (parameters, returns, fields):

    from     D -> slot     a value of named type D is stored into the slot
    forward  slot -> slot  a slot read is stored, unchanged, into a slot
    to       slot -> T     a slot read is converted to named type T

Each slot also carries `decl`, the named struct it is declared to hold
("" when it is type-erased).

ONLY DIRECT CASTS. A pair `D casted_to T` needs both casts at ONE slot: D
converted into it where it is stored (a `from` row, the slot's own `decl`,
or a NAMED value handed on -- `av_log(s->avctx)` converts AVCodecContext to
`void *` at that call), and the slot converted to T where it is read. A
type-erased value handed on (`av_log(avcl)` -> `av_vlog`) is not a cast: it
is a call chain, and following it joins every type that reaches the callee
with every type any branch of it reads -- `git_cached_obj_decref(void *)`
hands `_obj` to `git_odb_object__free` OR `git_object__free` on a flag
test, which would pair `git_blob` with `git_odb_object`. Such chains are
left to the orchestrator's review; the analyzer only states casts it sees.

FIELDS and RETURNS are one slot for every instance or call, so joining what
one writer stores with what another reader converts relates types no single
value ever had -- `AVCodecContext.priv_data` would pair the one codec that
stores a typed context with all 346 that read one. They yield a pair only
when BOTH sides are named: a `Base *` field read as `Derived *`
(`Base -> Derived`), a `Derived *` stored into it (`Derived -> Base`). An
ERASED field is recorded instead -- the types `stored` into it and the
types it is `read_as` -- as the field's variants, never as pairs.

PROJECTION. With `keep`, every edge with an end outside it is dropped
BEFORE joining -- in API mode, every node not on the public API: an
internal function's parameters, an internal type, an internal struct's
fields. Nothing is followed through a dropped node.

What a pair means: every edge is a conversion written in the source, at the
slot access itself. A pair is still path-insensitive within its one slot: a
read guarded by a type check joins every type stored into that slot.

Pure: rows in, pairs and variants out. `Reach` feeds it the two CSVs.
"""
from __future__ import annotations

import csv
import functools
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

#: `void *`, `const void *`, `void **`, ... -- a C type that names nothing.
_VOID_PTR = re.compile(r"^(?:(?:const|volatile)\s+)*void\s*(?:\*\s*(?:const\s*)?)+$")

#: A slot: (kind, name, file, member). Types are keyed by tag alone, as in
#: the raw cast graph (`casts.csv` names no file).
Slot = tuple[str, str, str, str]


def slot_id(slot: Slot) -> str:
    """Display form: `param:av_log.0@libavutil/log.c`, `field:Holder.opaque@f.h`."""
    kind, name, file, member = slot
    return f"{kind}:{name}.{member}@{file}"


def _end(row: dict, side: str) -> tuple[str, Slot | str, str]:
    kind = row[f"{side}_kind"]
    if kind == "type":
        return kind, row[f"{side}_name"], ""
    slot = (kind, row[f"{side}_name"], row[f"{side}_file"], row[f"{side}_member"])
    return kind, slot, row.get(f"{side}_decl") or ""


class Composed(NamedTuple):
    #: `{(D, T): witness}`: the slots that witness `D casted_to T`, `D != T`.
    #: A parameter path gives `(entry, exit)`, a named field or return `(slot,)`.
    pairs: dict[tuple[str, str], tuple[Slot, ...]]
    #: `{field slot: (stored, read_as)}` for every type-erased field.
    variants: dict[Slot, tuple[frozenset[str], frozenset[str]]]
    #: `{param slot: types}` for every `void *` parameter: the named types its
    #: own body reads its value as. This is the type the signature erases
    #: (`av_vlog.0` -> AVClass). A typed scalar pointer (`unsigned *flags`)
    #: erases nothing, so it carries none.
    param_reads: dict[Slot, frozenset[str]]


def _keep(pairs: dict, key: tuple[str, str], witness: tuple[Slot, ...]) -> None:
    if key[0] != key[1] and (key not in pairs or witness < pairs[key]):
        pairs[key] = witness


def compose(rows: Iterable[dict], keep: Callable[[str, str, str], bool] | None = None
            ) -> Composed:
    """Slot-mediated cast pairs and erased-field variants from `arg_casts` +
    `field_casts` rows, projected onto `keep` (default: every node). When
    several witnesses exist, the smallest is kept, so the result is
    deterministic."""
    ok = keep or (lambda _k, _n, _f: True)

    def node(kind: str, end) -> bool:
        return ok("type", end, "") if kind == "type" else ok(kind, end[1], end[2])

    enters: dict[str, set[Slot]] = defaultdict(set)     # D -> params it enters
    exits: dict[Slot, set[str]] = defaultdict(set)      # param -> T it is read as
    decls: dict[Slot, str] = {}                         # param -> its named decl
    void_params: set[Slot] = set()                      # params declared `void *`
    pairs: dict[tuple[str, str], tuple[Slot, ...]] = {}
    stored: dict[Slot, set[str]] = defaultdict(set)
    read_as: dict[Slot, set[str]] = defaultdict(set)
    erased: set[Slot] = set()

    for r in rows:
        rel = r["rel"]
        sk, src, sdecl = _end(r, "src")
        dk, dst, ddecl = _end(r, "dst")
        if rel == "forward":
            # A hand-off is a cast only when the value handed on is NAMED: its
            # static type is converted at the store, like any `from`. An
            # erased value handed on is a call chain -- not followed.
            if sk == "type" or dk == "type" or not sdecl:
                continue
            if ddecl:                                   # named -> named slot
                if (node(sk, src) and node(dk, dst)
                        and ok("type", sdecl, "") and ok("type", ddecl, "")):
                    _keep(pairs, (sdecl, ddecl), (src, dst))
                continue
            rel, sk, src = "from", "type", sdecl
        if not (node(sk, src) and node(dk, dst)):
            continue
        for side, kind, end, decl in (("src", sk, src, sdecl), ("dst", dk, dst, ddecl)):
            if kind == "param":
                if _VOID_PTR.match(r.get(f"{side}_ctype") or ""):
                    void_params.add(end)
                if decl and ok("type", decl, ""):
                    decls[end] = decl
            elif kind == "field" and not decl:
                erased.add(end)
        if rel == "from" and sk == "type":
            if dk == "param":
                enters[src].add(dst)
            elif ddecl:                                 # named field / return
                if ok("type", ddecl, ""):
                    _keep(pairs, (src, ddecl), (dst,))
            elif dk == "field":
                stored[dst].add(src)
        elif rel == "to" and dk == "type":
            if sk == "param":
                exits[src].add(dst)
            elif sdecl:                                 # named field / return
                if ok("type", sdecl, ""):
                    _keep(pairs, (sdecl, dst), (src,))
            elif sk == "field":
                read_as[src].add(dst)

    for p, d in decls.items():                          # a param holds its decl
        enters[d].add(p)
    for d, entries in enters.items():
        for p in entries:
            for t in exits.get(p, ()):
                _keep(pairs, (d, t), (p,))

    variants = {f: (frozenset(stored.get(f, ())), frozenset(read_as.get(f, ())))
                for f in sorted(erased) if stored.get(f) or read_as.get(f)}
    param_reads = {p: frozenset(exits[p]) for p in sorted(void_params)
                   if p not in decls and exits.get(p)}
    return Composed(pairs, variants, param_reads)


TABLES = ("arg_casts.csv", "field_casts.csv")


def _decl_files(cell: str) -> list[str]:
    return [d for d in (cell or "").split("|") if d]


def public_keep(t1: Path, api_paths: frozenset[str]) -> Callable[[str, str, str], bool]:
    """Projection onto the public API: a type, or a function, is public when
    its definition or any declaration sits in `api_paths`. A field is public
    only when its owner is DEFINED there: an opaque handle's fields are not
    API (`git_annotated_commit.commit`). Read from the T1 inventory."""
    types: set[str] = set()
    layouts: set[str] = set()
    fns: set[tuple[str, str]] = set()
    fn_names: set[str] = set()

    def published(r: dict) -> bool:
        return any(f in api_paths for f in [r.get("def_file") or ""]
                   + _decl_files(r.get("decl_files") or ""))

    for name, sink in (("types.csv", types), ("functions.csv", fns)):
        path = Path(t1) / name
        if not path.exists():
            continue
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                if not published(r):
                    continue
                if sink is types:
                    types.add(r["name"])
                    if (r.get("def_file") or "") in api_paths:
                        layouts.add(r["name"])
                else:
                    fns.add((r["name"], r.get("def_file") or ""))
                    fn_names.add(r["name"])

    def keep(kind: str, name: str, file: str) -> bool:
        if kind == "type":
            return name in types
        if kind == "field":
            return name in layouts
        return (name, file) in fns or (not file and name in fn_names)
    return keep


@functools.lru_cache(maxsize=8)
def _load(t2: str, stamp: tuple, api_paths: frozenset[str] | None) -> Composed:
    rows: list[dict] = []
    for name in TABLES:
        path = Path(t2) / name
        if path.exists():
            with path.open(newline="") as f:
                rows += csv.DictReader(f)
    keep = None if api_paths is None else public_keep(Path(t2).parent / "t1", api_paths)
    return compose(rows, keep)


def load(t2: Path, api_paths: Iterable[str] | None = None) -> Composed:
    """`compose` over a T2 directory's two tables, cached per table state:
    the composer (`Reach`) and the scheduler (`deps_dag`) read the same
    result in one process. Missing tables compose to nothing. With
    `api_paths` (API mode), projected onto the public API (`public_keep`)."""
    stamp = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None
                  for p in [Path(t2) / n for n in TABLES]
                  + [Path(t2).parent / "t1" / n for n in ("types.csv", "functions.csv")])
    return _load(str(t2), stamp, None if api_paths is None else frozenset(api_paths))


def by_type(pairs: dict[tuple[str, str], tuple[Slot, ...]]
            ) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Index pairs per tag as manifest records.

    `to[D]` lists `{type: T, via: [slot ids]}` for each T that D is cast
    into through slots; `from_[T]` the mirror image. Sorted by type.
    """
    to: dict[str, list[dict]] = defaultdict(list)
    from_: dict[str, list[dict]] = defaultdict(list)
    for (d, t), witness in sorted(pairs.items()):
        via = [slot_id(s) for s in witness]
        to[d].append({"type": t, "via": via})
        from_[t].append({"type": d, "via": via})
    return dict(to), dict(from_)


def by_field(variants: dict[Slot, tuple[frozenset[str], frozenset[str]]]
             ) -> dict[tuple[str, str], dict]:
    """Erased-field variants keyed `(owner tag, field name)` as the field's
    `erased_as` record: `{stored: [tags], read_as: [tags]}`, sorted."""
    return {(name, member): {"stored": sorted(st), "read_as": sorted(rd)}
            for (_k, name, _f, member), (st, rd) in variants.items()}
