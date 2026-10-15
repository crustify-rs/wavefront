"""slot_casts.py -- join slot edges into slot-mediated cast pairs.

`edges/arg_casts.ql` and `edges/field_casts.ql` emit three kinds of edge
between named types and value SLOTS (parameters, returns, fields):

    from     D -> slot     a value of named type D is stored into the slot
    forward  slot -> slot  a slot read is stored, unchanged, into a slot
    to       slot -> T     a slot read is converted to named type T

Each slot also carries `decl`, the named struct it is declared to hold
("" when it is type-erased).

PARAMETERS propagate. `D casted_to T` holds when some path
`D -> P0 -forward*-> Pn -> T` exists over parameter slots only: a parameter
is one value per call, so what enters it is what its body converts. D
enters a parameter by a `from` row, as the parameter's own `decl`, or as the
`decl` of a named field or return whose read is passed in
(`av_log(s->avctx)`). Forward cycles (A calls B calls C calls A) are
harmless: the parameters of one strongly connected component reach the
same types.

FIELDS and RETURNS do not propagate. A field is one slot for every instance
of its struct and a return one slot for every call, so joining what one
writer stores with what another reader converts relates types no single
value ever had -- `AVCodecContext.priv_data` would pair the one codec that
stores a typed context with all 346 that read one. They yield a pair only
when BOTH sides are named: a `Base *` field read as `Derived *`
(`Base -> Derived`), a `Derived *` stored into it (`Derived -> Base`). An
ERASED field is recorded instead -- the types `stored` into it and the
types it is `read_as` -- as the field's variants, never as pairs.

What a pair means: every edge is a conversion or hand-off written in the
source, and the queries follow no flow through locals or memory, so casts
are missed rather than invented. A parameter path is still
path-insensitive: a cast guarded by a type check joins every type that
reaches its parameter.

Pure: rows in, pairs and variants out. `Reach` feeds it the two CSVs.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import NamedTuple

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


def _sccs(nodes: Iterable[Slot], succ: dict[Slot, set[Slot]]) -> list[list[Slot]]:
    """Tarjan, iterative, deterministic. Returns SCCs in reverse topological
    order: every SCC comes after the SCCs it reaches."""
    index: dict[Slot, int] = {}
    low: dict[Slot, int] = {}
    on: set[Slot] = set()
    stack: list[Slot] = []
    out: list[list[Slot]] = []
    counter = 0
    for root in sorted(nodes):
        if root in index:
            continue
        work = [(root, iter(sorted(succ.get(root, ()))))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(succ.get(w, ())))))
                    advanced = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp))
    return out


class Composed(NamedTuple):
    #: `{(D, T): witness}`: the slots that witness `D casted_to T`, `D != T`.
    #: A parameter path gives `(entry, exit)`, a named field or return `(slot,)`.
    pairs: dict[tuple[str, str], tuple[Slot, ...]]
    #: `{field slot: (stored, read_as)}` for every type-erased field.
    variants: dict[Slot, tuple[frozenset[str], frozenset[str]]]


def _keep(pairs: dict, key: tuple[str, str], witness: tuple[Slot, ...]) -> None:
    if key[0] != key[1] and (key not in pairs or witness < pairs[key]):
        pairs[key] = witness


def compose(rows: Iterable[dict]) -> Composed:
    """Slot-mediated cast pairs and erased-field variants from `arg_casts` +
    `field_casts` rows. When several witnesses exist, the smallest is kept,
    so the result is deterministic."""
    enters: dict[str, set[Slot]] = defaultdict(set)     # D -> params it enters
    succ: dict[Slot, set[Slot]] = defaultdict(set)      # param -> param
    exits: dict[Slot, set[str]] = defaultdict(set)      # param -> T it is read as
    params: set[Slot] = set()
    pairs: dict[tuple[str, str], tuple[Slot, ...]] = {}
    stored: dict[Slot, set[str]] = defaultdict(set)
    read_as: dict[Slot, set[str]] = defaultdict(set)
    erased: set[Slot] = set()

    for r in rows:
        sk, src, sdecl = _end(r, "src")
        dk, dst, ddecl = _end(r, "dst")
        for kind, end, decl in ((sk, src, sdecl), (dk, dst, ddecl)):
            if kind == "param":
                params.add(end)
                if decl:
                    enters[decl].add(end)
            elif kind == "field" and not decl:
                erased.add(end)
        rel = r["rel"]
        if rel == "from" and sk == "type":
            if dk == "param":
                enters[src].add(dst)
            elif ddecl:                                 # named field / return
                _keep(pairs, (src, ddecl), (dst,))
            elif dk == "field":
                stored[dst].add(src)
        elif rel == "to" and dk == "type":
            if sk == "param":
                exits[src].add(dst)
            elif sdecl:                                 # named field / return
                _keep(pairs, (sdecl, dst), (src,))
            elif sk == "field":
                read_as[src].add(dst)
        elif rel == "forward" and sk != "type" and dk != "type":
            if sk == "param" and dk == "param":
                succ[src].add(dst)
            elif dk == "param":
                if sdecl:                               # named field / return read
                    enters[sdecl].add(dst)
            elif sdecl and ddecl:                       # named -> named slot
                _keep(pairs, (sdecl, ddecl), (src, dst))
            elif sdecl and dk == "field":               # named read -> erased field
                stored[dst].add(sdecl)

    # Per SCC of parameters: the types it reaches, each with its smallest exit.
    reach_of: dict[Slot, dict[str, Slot]] = {}
    for comp in _sccs(params, succ):
        acc: dict[str, Slot] = {}
        members = set(comp)
        for p in comp:
            for t in exits.get(p, ()):
                if t not in acc or p < acc[t]:
                    acc[t] = p
            for w in succ.get(p, ()):
                if w in members:
                    continue
                for t, x in reach_of[w].items():
                    if t not in acc or x < acc[t]:
                        acc[t] = x
        for p in comp:
            reach_of[p] = acc

    for d, entries in enters.items():
        for p in entries:
            for t, x in reach_of.get(p, {}).items():
                _keep(pairs, (d, t), (p, x) if p != x else (p,))

    variants = {f: (frozenset(stored.get(f, ())), frozenset(read_as.get(f, ())))
                for f in sorted(erased) if stored.get(f) or read_as.get(f)}
    return Composed(pairs, variants)


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
