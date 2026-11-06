"""The order of a schedule's units: their dependency graph, its cycles cut
by a weighted feedback-arc-set, and its layers."""
from __future__ import annotations

from collections import defaultdict

from wavefront.dag import NodeKey


def _full_edges(dag: dict) -> tuple[dict[NodeKey, set[NodeKey]],
                                    dict[tuple[NodeKey, NodeKey], int]]:
    """Every dependency edge of the composed graph, the cut ones included,
    with the weight of each edge heavier than 1."""
    def keys(group, side):
        kind = "type" if side == "types" else "symbol"
        return [(d["name"], d.get("defined_in"), kind)
                for d in (group or {}).get(side) or []]

    edges: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    weights: dict[tuple[NodeKey, NodeKey], int] = {}

    def add(rec, deps):
        key = (rec["id"], rec.get("defined_in"), rec["node_kind"])
        for group in (deps, rec.get("fallback")):
            for side in ("types", "syms"):
                edges[key].update(keys(group, side))
        for w in rec.get("weights") or []:
            weights[(key, (w["name"], w.get("defined_in"), "type"))] = w["w"]

    for layer in dag.get("layers", []):
        for rec in layer:
            if "scc" in rec:
                for member in rec["scc"]:
                    add(member, member.get("deps") or rec.get("deps"))
            else:
                add(rec, rec.get("deps"))
    return edges, weights


def _sccs(nodes: list, adj: dict) -> list[list]:
    """Tarjan's strongly connected components of ``adj`` restricted to
    ``nodes``, iteratively, members sorted."""
    index: dict = {}
    low: dict = {}
    on: set = set()
    stack: list = []
    out: list[list] = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(sorted(adj.get(root, ()))))]
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
                    work.append((w, iter(sorted(adj.get(w, ())))))
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


def _cut(nodes: list, adj: dict, weight) -> set[tuple]:
    """The edges a weighted feedback-arc-set cuts to make ``adj`` acyclic over
    ``nodes``. Within each cycle, a member is placed the earlier the more
    weight depends on it, net of the weight it depends on: the producer first.
    An edge from a member to one placed after it is cut."""
    cut: set[tuple] = set()
    for comp in _sccs(nodes, adj):
        if len(comp) < 2:
            continue
        members = set(comp)
        net: dict = defaultdict(int)
        for u in comp:
            for v in adj.get(u, ()):
                if v in members:
                    w = weight(u, v)
                    net[v] += w
                    net[u] -= w
        order = sorted(comp, key=lambda x: (-net[x], _sort_key(x)))
        pos = {x: i for i, x in enumerate(order)}
        for u in comp:
            for v in adj.get(u, ()):
                if v in members and pos[v] > pos[u]:
                    cut.add((u, v))
    return cut


def _sort_key(x):
    if isinstance(x, tuple):
        return tuple("" if part is None else str(part) for part in x)
    return (str(x),)


def _layers(nodes: list, adj: dict) -> dict:
    """Longest-path layer of each node of an acyclic ``adj``: 0 for a node
    with no dependency among ``nodes``."""
    members = set(nodes)
    memo: dict = {}
    for root in nodes:
        if root in memo:
            continue
        stack = [(root, False)]
        while stack:
            v, done = stack.pop()
            if v in memo:
                continue
            deps = [d for d in adj.get(v, ()) if d in members]
            if done:
                memo[v] = 1 + max((memo[d] for d in deps), default=-1)
                continue
            stack.append((v, True))
            stack.extend((d, False) for d in deps if d not in memo)
    return memo
