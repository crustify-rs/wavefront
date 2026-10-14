"""slot_casts.py -- join slot edges into slot-mediated cast pairs.

`edges/arg_casts.ql` and `edges/field_casts.ql` emit three kinds of edge
between named types and value SLOTS (parameters, returns, fields):

    from     D -> slot     a value of named type D is stored into the slot
    forward  slot -> slot  a slot read is stored, unchanged, into a slot
    to       slot -> T     a slot read is converted to named type T

Every slot is also seeded with its declared struct (`decl`), so a typed slot
`Base *b` acts as a `from Base`.

`D casted_to T` holds when some path `D -from-> S0 -forward*-> Sn -to-> T`
exists. Forward cycles (A calls B calls C calls A) are harmless: the slots
of one strongly connected component reach the same types.

What the pairs mean, exactly: each EDGE is a conversion or hand-off written
in the source. A PAIR composes them field-based (all instances of a field
share one slot) and path-insensitively (a cast guarded by a type check
still joins every type reaching its slot), and the queries follow no flow
through locals or memory. So a pair is a may-relation over those
abstractions: neither every runtime cast is found, nor is every pair a
cast some single execution performs.

Pure: rows in, pairs out. `Reach` feeds it the two CSVs.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

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


def compose(rows: Iterable[dict]) -> dict[tuple[str, str], tuple[Slot, Slot]]:
    """Slot-mediated cast pairs from `arg_casts` + `field_casts` rows.

    Returns `{(D, T): (entry_slot, exit_slot)}` for every `D casted_to T`
    with `D != T`: `entry_slot` is where D enters, `exit_slot` the slot whose
    read is converted to T. When several witnesses exist, the smallest
    `(entry, exit)` is kept, so the result is deterministic.
    """
    enters: dict[str, set[Slot]] = defaultdict(set)    # D -> slots it enters
    succ: dict[Slot, set[Slot]] = defaultdict(set)     # forward edges
    exits: dict[Slot, set[str]] = defaultdict(set)     # slot -> T it is read as
    slots: set[Slot] = set()

    for r in rows:
        sk, src, sdecl = _end(r, "src")
        dk, dst, ddecl = _end(r, "dst")
        for kind, end, decl in ((sk, src, sdecl), (dk, dst, ddecl)):
            if kind != "type":
                slots.add(end)
                if decl:
                    enters[decl].add(end)
        rel = r["rel"]
        if rel == "from" and sk == "type" and dk != "type":
            enters[src].add(dst)
        elif rel == "forward" and sk != "type" and dk != "type":
            succ[src].add(dst)
        elif rel == "to" and sk != "type" and dk == "type":
            exits[src].add(dst)

    # Per SCC: the types its slots reach, each with its smallest exit slot.
    reach_of: dict[Slot, dict[str, Slot]] = {}
    for comp in _sccs(slots, succ):
        acc: dict[str, Slot] = {}
        members = set(comp)
        for s in comp:
            for t in exits.get(s, ()):
                if t not in acc or s < acc[t]:
                    acc[t] = s
            for w in succ.get(s, ()):
                if w in members:
                    continue
                for t, x in reach_of[w].items():
                    if t not in acc or x < acc[t]:
                        acc[t] = x
        for s in comp:
            reach_of[s] = acc

    pairs: dict[tuple[str, str], tuple[Slot, Slot]] = {}
    for d, entries in enters.items():
        for s in entries:
            for t, x in reach_of.get(s, {}).items():
                if t == d:
                    continue
                w = (s, x)
                if (d, t) not in pairs or w < pairs[(d, t)]:
                    pairs[(d, t)] = w
    return pairs


def by_type(pairs: dict[tuple[str, str], tuple[Slot, Slot]]
            ) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Index pairs per tag as manifest records.

    `to[D]` lists `{type: T, via: [entry, exit]}` for each T that D is
    cast into through slots; `from_[T]` the mirror image. Sorted by type.
    """
    to: dict[str, list[dict]] = defaultdict(list)
    from_: dict[str, list[dict]] = defaultdict(list)
    for (d, t), (entry, exit_) in sorted(pairs.items()):
        via = [slot_id(entry)] if entry == exit_ else [slot_id(entry), slot_id(exit_)]
        to[d].append({"type": t, "via": via})
        from_[t].append({"type": d, "via": via})
    return dict(to), dict(from_)
