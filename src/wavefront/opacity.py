"""When each unit's last user is processed: the layout users of a struct or
union, and the referrers of a function or global, and the point of a
schedule after which none of them is left to process.

A type is *opaque* after its layout users: once every unit that reads its
members, size or alignment, or holds it by value, has been processed, what
comes after holds it only through pointers. A function or global is
*unreferenced* after its referrers: once every unit that calls it, takes its
address or reads it has been processed. Both are objective-neutral facts of
the order; what a consumer does at that point is its own.

The users are units of the closure, scheduled or not: an entity that is no
unit, such as an external function, a test the closure leaves out, or a macro
expanded where it is used, does not count. A type that another holds by value
is also used by every layout user of its holder, so the layout users close
over embedding.

The point is a frontier, not a wave: two users' waves may be listed one after
the other without either depending on the other, so the frontier is every
candidate (the unit's own wave and its users') that no other candidate
depends on, transitively. The same holds over the modules, and over the units
of the whole closure's order.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from compose.scope import load_csv
from wavefront.dag import NodeKey
from wavefront.order import _sort_key

#: The layout-use kinds of ``t2/layout_uses.csv``.
USE_KINDS = ("field", "size", "value", "index", "embed")


def load_layout_uses(t2: Path) -> dict[NodeKey, dict[NodeKey, set[str]]]:
    """``{type key: {user key: {use kind}}}`` from ``t2/layout_uses.csv``.

    A user the database holds no definition of (a prototype taking the type by
    value) is no unit of anything, and is left out; so is a type use without a
    definition file."""
    path = t2 / "layout_uses.csv"
    out: dict[NodeKey, dict[NodeKey, set[str]]] = defaultdict(lambda: defaultdict(set))
    if not path.is_file():
        return {}
    for r in load_csv(path):
        if not r.get("user_def_file") or not r.get("type_def_file"):
            continue
        tkey = (r["type_name"], r["type_def_file"], "type")
        ukind = "type" if r.get("user_kind") == "type" else "symbol"
        ukey = (r["user_name"], r["user_def_file"], ukind)
        if ukey != tkey:
            out[tkey][ukey].add(r["use_kind"])
    return {t: dict(us) for t, us in out.items()}


def close_over_embedding(direct: dict[NodeKey, dict[NodeKey, set[str]]]
                         ) -> dict[NodeKey, dict[NodeKey, tuple[set[str], set[NodeKey]]]]:
    """Each type's layout users, its holders' included: ``{type: {user: (uses,
    via)}}``, ``uses`` the user's own kinds of use of the type and ``via`` the
    holders, direct or transitive, it uses the type through. A holder is
    itself a user, by ``embed``."""
    holders: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    for t, users in direct.items():
        for u, kinds in users.items():
            if u[2] == "type" and "embed" in kinds:
                holders[t].add(u)

    memo: dict[NodeKey, dict[NodeKey, tuple[set[str], set[NodeKey]]]] = {}

    def users_of(t: NodeKey, path: frozenset) -> dict:
        if t in memo:
            return memo[t]
        out: dict[NodeKey, tuple[set[str], set[NodeKey]]] = {}
        for u, kinds in direct.get(t, {}).items():
            out[u] = (set(kinds), set())
        for h in sorted(holders.get(t, ()), key=_sort_key):
            if h in path:            # by-value embedding cannot cycle; a
                continue             # database that says so is not followed
            for u, (_, via) in users_of(h, path | {t}).items():
                if u == t:
                    continue
                uses, own_via = out.setdefault(u, (set(), set()))
                own_via.add(h)
                own_via.update(via)
        memo[t] = out
        return out

    return {t: users_of(t, frozenset()) for t in sorted(direct, key=_sort_key)}


def referrers(edges: dict[NodeKey, set[NodeKey]], is_target, is_referrer
              ) -> dict[NodeKey, set[NodeKey]]:
    """``{symbol: {referrer}}`` over the body-deep graph's edges: every node
    ``is_referrer`` admits that depends on a node ``is_target`` admits, itself
    aside. Signature edges reach types and callbacks only, so between
    functions and globals every edge is a reference."""
    out: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    for u, ds in edges.items():
        if not is_referrer(u):
            continue
        for d in ds:
            if d != u and is_target(d):
                out[d].add(u)
    return dict(out)


class Order:
    """The transitive dependencies of an acyclic ``dag`` (``{node: {dep}}``),
    as bitsets, so that a frontier among thousands of nodes stays cheap. A
    node the dag does not hold is ordered against nothing."""

    def __init__(self, dag: dict) -> None:
        nodes = sorted(set(dag) | {d for ds in dag.values() for d in ds},
                       key=_sort_key)
        self.bit = {n: 1 << i for i, n in enumerate(nodes)}
        self.below: dict = {}
        for root in nodes:
            if root in self.below:
                continue
            stack = [(root, False)]
            while stack:
                n, done = stack.pop()
                if done:
                    acc = 0
                    for d in dag.get(n, ()):
                        acc |= self.bit[d] | self.below[d]
                    self.below[n] = acc
                elif n not in self.below:
                    stack.append((n, True))
                    stack.extend((d, False) for d in dag.get(n, ())
                                 if d not in self.below)

    def depends(self, a, b) -> bool:
        """Whether ``a`` depends on ``b``, transitively."""
        return bool(self.below.get(a, 0) & self.bit.get(b, 0))

    def frontier(self, candidates) -> list:
        """The candidates no other candidate depends on, transitively."""
        cs = set(candidates)
        under = 0
        for c in cs:
            under |= self.below.get(c, 0)
        return sorted((c for c in cs if not under & self.bit.get(c, 0)),
                      key=_sort_key)
