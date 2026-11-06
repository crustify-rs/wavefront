"""Deterministic wave planning over the oracle dependency graph.

The schedule orders every unit of the closure (:mod:`wavefront.order`), keeps
the config's ``schedule_seeds`` (:mod:`wavefront.selection`) and the
units they depend on, and emits one wave per layer of the order. Batch caps are optional: a cap that is
not given does not bound a batch.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from wavefront.dag import Node, NodeKey, load_nodes, load_type_meta

#: The batch caps, each optional.
CAPS = ("max_syms", "max_loc", "max_types", "min_fields")


def is_generator(node: Node) -> bool:
    return (node.node_kind == "symbol"
            and (node.subkind or "").startswith("macro")
            and bool(node.type_generator_for))


@dataclass
class Unit:
    node: Node
    fields: list[str] = field(default_factory=list)
    scope: str | None = None

    @property
    def route(self) -> str:
        if self.node.node_kind == "type" or is_generator(self.node):
            return "type"
        if self.node.subkind == "callback":
            return "callback"
        return "symbol"

    def label(self) -> str:
        return self.node.id


@dataclass
class Batch:
    units: list[Unit]
    file: str | None = None

    @property
    def route(self) -> str:
        routes = {u.route for u in self.units}
        if routes <= {"symbol", "callback"}:
            return "symbol"
        return next(iter(routes))


def _pack(units: list[Unit], *, max_syms: int | None = None,
          max_loc: int | None = None, max_types: int | None = None,
          min_fields: int | None = None) -> list[Batch]:
    """Pack units into batches by route. A cap left ``None`` (or ``max_loc``
    0) bounds nothing; with no cap at all, each route is one batch."""
    batches: list[Batch] = []
    types = [u for u in units if u.route == "type"]
    symbols = [u for u in units if u.route != "type"]

    chunk: list[Unit] = []
    fields = 0
    for unit in types:
        nfields = len(unit.fields)
        if chunk and ((max_types is not None and len(chunk) >= max_types)
                      or (min_fields is not None
                          and (fields >= min_fields or nfields >= min_fields))):
            batches.append(Batch(list(chunk), chunk[0].node.defined_in))
            chunk, fields = [], 0
        chunk.append(unit)
        fields += nfields
    if chunk:
        batches.append(Batch(list(chunk), chunk[0].node.defined_in))

    pools: dict[str | None, list[Unit]] = {}
    for unit in symbols:
        pools.setdefault(unit.scope, []).append(unit)
    for pool in pools.values():
        chunk = []
        loc = 0
        for unit in pool:
            item_loc = unit.node.loc if max_loc else 0
            if chunk and ((max_syms is not None and len(chunk) >= max_syms)
                          or (max_loc and loc + item_loc > max_loc)):
                batches.append(Batch(list(chunk), None))
                chunk, loc = [], 0
            chunk.append(unit)
            loc += item_loc
        if chunk:
            batches.append(Batch(list(chunk), None))
    return batches


def _coalesce(by_layer: dict[int, list[Unit]], layers: list[int], *,
              budgets: dict) -> list[list[int]]:
    waves: list[list[int]] = []
    index = 0
    while index < len(layers):
        group = [layers[index]]
        nxt = index + 1
        while nxt < len(layers):
            candidate = group + [layers[nxt]]
            merged = [u for layer in candidate for u in by_layer[layer]]
            if len(_pack(merged, **budgets)) != 1:
                break
            group = candidate
            nxt += 1
        waves.append(group)
        index = nxt
    return waves


def _used_fields(layout, target: Path, *,
                   api_headers_only: bool = False) -> dict[NodeKey, list[str]]:
    """The fields of each type its users reach, keyed by the type's graph
    identity: in API mode every field of a type an ``api_headers`` file
    defines, and none of a type defined elsewhere, whose layout the API does
    not publish even when a public forward declaration names it; otherwise
    the fields the config's own functions access. Keying by
    ``(tag, defined_in)`` keeps a public definition from donating its fields
    to an unrelated private aggregate of the same tag.
    """
    from compose import scope as compose_scope
    from wavefront import manifests, scope
    from wavefront.query import scope_touched_index

    api_paths = None
    touched = None
    if api_headers_only:
        inventory = scope.build(layout, target, stage="schedule fields")
        api_paths = compose_scope.load_api_paths(inventory)
    else:
        touched = scope_touched_index(layout, target, compose_scope.TARGETED)
        touched = {tag: {name for names in by_file.values() for name in names}
                   for tag, by_file in touched.items()} or None

    out: dict[NodeKey, list[str]] = {}
    for entry in manifests.entries(layout, target, "types", stage="schedule"):
        tag = entry.get("name") or entry.get("type")
        if not tag:
            continue
        defined_in = entry.get("defined_in")
        key = (tag, defined_in, "type")
        if api_paths is not None and defined_in not in api_paths:
            out[key] = []
            continue
        names = [f["name"] for f in entry.get("fields") or []
                 if isinstance(f, dict) and f.get("name")]
        if touched is not None:
            names = [name for name in names if name in touched.get(tag, set())]
        out[key] = names
    return out


def build_schedule(layout, target: Path, *, api_headers_only: bool = False,
                   with_enums: bool = False, with_macros: bool = False,
                   caps: dict | None = None) -> dict:
    """Order every unit of the closure, and schedule those the config's
    ``schedule_seeds`` names with every unit they depend on, one wave per layer
    of the order.

    The units are the closure's targeted nodes, or with ``api_headers_only``
    what the published declarations reach of them over the API graph; an
    enum only ``with_enums``, and a macro, a type generator aside, only
    ``with_macros``, then every macro the closure's files define. Their
    cycles are cut and they are layered over all of them, so that a narrow
    selection keeps the order and the cuts of the whole closure. Without caps
    a wave holds one batch per route; with any, each layer is packed, and
    adjacent layers fold into one wave while they fit one batch."""
    from compose import scope as compose_scope
    from compose.scope_manifest import targeted_candidates
    from wavefront import dag as dag_mod, manifests, scope
    from wavefront import modules, selection
    from wavefront.order import _cut, _full_edges, _layers, _sort_key
    from wavefront.stats import Stats

    # `max_loc` 0 bounds nothing, as an absent cap: it must not turn packing,
    # and with it the folding of layers, on.
    caps = {k: (caps or {}).get(k) or None if k == "max_loc"
            else (caps or {}).get(k) for k in CAPS}
    budgets = caps if any(v is not None for v in caps.values()) else None

    config = json.loads(layout.config(target).read_text())
    entries = selection.load(config, layout.repo_root)
    mods = modules.load(config, layout.repo_root)
    closure_files = set(targeted_candidates(config, layout.repo_root))

    inventory = scope.build(layout, target, stage="schedule")
    decls = selection.declarations(inventory)
    graph = dag_mod.build(layout, target, stage="schedule",
                          api_headers_only=api_headers_only)
    by_key, _ = load_nodes(graph)
    edges = _full_edges(graph)

    def entities(section):
        out = set()
        for kind in ("functions", "globals", "macros", "types"):
            out |= compose_scope.load_entities(inventory, section, kind)
        return out
    targeted = entities(compose_scope.TARGETED)
    api = entities(compose_scope.API)

    def is_unit(node: Node) -> bool:
        if node.node_kind == "type" and node.subkind == "enum":
            if not with_enums:
                return False
        elif ((node.subkind or "").startswith("macro")
                and node.node_kind == "symbol" and not is_generator(node)):
            # A header macro is imported, whatever file defines it: with
            # macros, every one the closure's files define is a unit.
            return with_macros and (node.defined_in or "") in closure_files
        return bool({(node.id, node.defined_in or ""), (node.id, "")} & targeted)

    def is_seed(node: Node) -> bool:
        if not is_unit(node):
            return False
        return (not api_headers_only
                or bool({(node.id, node.defined_in or ""), (node.id, "")} & api))

    unit_keys = {k for k, n in by_key.items() if is_unit(n)}
    if entries is not None:
        selection.check(entries, decls, unit_keys)
    if mods:
        selection.check([e for m in mods for e in m.entries], decls, unit_keys)
        modules.check(mods, decls, unit_keys)
        # Claimed over every unit of the closure, whatever the graph: a module
        # that claims none of them is a config error, not an API-mode gap.
        claimed = modules.owners(mods, unit_keys)
        busy = set(claimed.values())
        idle = [m.name for i, m in enumerate(mods) if i not in busy]
        if idle:
            print(f"warning: {len(idle)} module(s) claim no unit: "
                  + ", ".join(idle[:20]) + (" ..." if len(idle) > 20 else ""),
                  file=sys.stderr)
    else:
        claimed = {}

    # The units: every targeted node, or in API mode what the published
    # declarations reach of it, closed over the graph's edges.
    pending = sorted((k for k, n in by_key.items() if is_seed(n)), key=_sort_key)
    units: set[NodeKey] = set()
    while pending:
        key = pending.pop()
        if key in units:
            continue
        units.add(key)
        pending.extend(d for d in edges.get(key, ())
                       if d in by_key and d not in units and is_unit(by_key[d]))

    # The order, over every unit; a schedule keeps its units in it. Units
    # are ordered in groups: each module's, and each unit no module claims
    # alone. The groups' cycles are cut and the groups layered into stages;
    # each module's units are then ordered within it. A cut costs a binding
    # of each dependency it leaves behind: a unit edge weighs 1, and an edge
    # between two groups the distinct units it depends on.
    def unit_weight(u: NodeKey, v: NodeKey) -> int:
        return 1

    ordered = sorted(units, key=_sort_key)
    adj = {k: {d for d in edges.get(k, ()) if d in units} for k in ordered}
    owner = {k: claimed[k] for k in ordered if k in claimed}

    def group(k: NodeKey) -> tuple:
        return ("module", owner[k]) if k in owner else ("unit", k)

    crossing: dict[tuple, list] = defaultdict(list)
    group_adj: dict[tuple, set] = defaultdict(set)
    for u in ordered:
        for v in sorted(adj[u], key=_sort_key):
            gu, gv = group(u), group(v)
            if gu != gv:
                crossing[(gu, gv)].append((u, v))
                group_adj[gu].add(gv)
    groups = sorted({group(k) for k in ordered}, key=_sort_key)
    group_cut = _cut(groups, group_adj,
                     lambda a, b: len({v for _, v in crossing[(a, b)]}))
    stage = _layers(groups, {g: {d for d in group_adj[g] if (g, d) not in group_cut}
                             for g in groups})
    cut: set[tuple[NodeKey, NodeKey]] = set()
    for e in group_cut:
        cut.update(crossing[e])
    members: dict[int, list[NodeKey]] = defaultdict(list)
    for k in ordered:
        if k in owner:
            members[owner[k]].append(k)
    layer: dict[NodeKey, int] = {k: 0 for k in ordered if k not in owner}
    for i, keys in members.items():
        inner = {k: {d for d in adj[k] if owner.get(d) == i} for k in keys}
        inner_cut = _cut(keys, inner, unit_weight)
        cut |= inner_cut
        layer.update(_layers(keys, {k: {d for d in ds if (k, d) not in inner_cut}
                                    for k, ds in inner.items()}))
    lower: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    for u, v in cut:
        lower[v].add(u)

    # The seeds, and every unit they depend on, cut edges included:
    # a cycle partner is still a dependency, scheduled after its user.
    seeds = selection.select(entries, units, decls)
    if not seeds:
        raise SystemExit("schedule: `schedule_seeds` names no unit.")
    chosen = set()
    pending = sorted(seeds, key=_sort_key)
    while pending:
        key = pending.pop()
        if key not in chosen:
            chosen.add(key)
            pending.extend(d for d in adj[key] if d not in chosen)
    # With modules, every unit a schedule holds is the closure's, and needs
    # one: what a schedule does not reach needs none.
    loose = sorted((k for k in chosen if k not in owner),
                   key=lambda k: (k not in seeds, _sort_key(k)))
    if mods and loose:
        n_seeds = sum(1 for k in loose if k in seeds)
        print(f"warning: {len(loose)} scheduled unit(s) belong to no module "
              f"({n_seeds} seed(s), {len(loose) - n_seeds} dependenc(ies)), and "
              f"are ordered alone: "
              + ", ".join(f"{k[2]} {k[0]} ({k[1] or '?'})" for k in loose[:20])
              + (" ..." if len(loose) > 20 else ""), file=sys.stderr)

    stats = Stats(layout.t1, layout.t2, closure_files)
    pair = (manifests.entries(layout, target, "types", stage="schedule"),
            manifests.entries(layout, target, "symbols", stage="schedule"))
    declared = load_type_meta(pair, by_file=True)
    used = _used_fields(layout, target, api_headers_only=api_headers_only)

    def scope_of(key: NodeKey) -> str:
        if key in chosen:
            return "scheduled"
        node = by_key.get(key)
        if node is not None and (node.defined_in or "") in closure_files:
            return "closure"
        return "external"

    def ref(key: NodeKey) -> dict:
        return {"name": key[0], "defined_in": key[1], "scope": scope_of(key)}

    def route(key: NodeKey) -> str:
        """A key's side of a reference list: a generator macro is a type, as
        its item is."""
        node = by_key.get(key)
        return "type" if node is not None and is_generator(node) else key[2]

    def refs(keys, kind=None):
        return [ref(k) for k in sorted(keys, key=_sort_key)
                if kind is None or route(k) == kind]

    def sides(keys) -> dict:
        return {"types": refs(keys, "type"), "symbols": refs(keys, "symbol")}

    def doc(key: NodeKey) -> dict:
        node = by_key[key]
        deps = {d for d in edges.get(key, ()) if (key, d) not in cut}
        higher = {d for d in edges.get(key, ()) if (key, d) in cut}
        return {
            "name": node.id,
            "defined_in": node.defined_in,
            "declared_in": sorted(decls.get(key, ())),
            "kind": ("type" if node.node_kind == "type" or is_generator(node)
                     else "callback" if node.subkind == "callback" else "symbol"),
            "source_kind": node.subkind,
            "seeded": key in seeds,
            "module": mods[owner[key]].name if key in owner else None,
            "loc": node.loc,
            "stats": stats.of(node.id, node.defined_in, node.node_kind,
                              node.subkind),
            "depends_on": {"scheduled": sides(deps), "cut": sides(higher)},
            "depended_on_by": {"cut": sides(lower.get(key, ()))},
            "type_generator_for": list(node.type_generator_for),
            "used_fields": used.get(key, []),
        }

    def unit(key: NodeKey) -> Unit:
        node = by_key[key]
        return Unit(node, list(declared.get((node.id, node.defined_in),
                                            ([], set()))[0]), "targeted")

    def batches_of(keys: list[NodeKey]) -> list[dict]:
        if budgets is None:
            routes: dict[str, list[NodeKey]] = {}
            for k in keys:
                routes.setdefault("type" if unit(k).route == "type" else "symbol",
                                  []).append(k)
            return [{"kind": route, "items": [doc(k) for k in ks]}
                    for route, ks in sorted(routes.items(),
                                            key=lambda r: r[0] != "type")]
        return [{"kind": b.route, "source_file": b.file,
                 "items": [doc(u.node.key) for u in b.units]}
                for b in _pack([unit(k) for k in keys], **budgets)]

    # One wave per layer of a module; with caps, a module's adjacent layers
    # fold. Without modules, the waves are the stages of the units' order.
    slots: dict[tuple, list[NodeKey]] = defaultdict(list)
    for k in sorted(chosen, key=_sort_key):
        if k in owner:
            slots[(owner[k], layer[k])].append(k)
    held_by: dict[tuple, list[NodeKey]] = {}
    for i in sorted({sl[0] for sl in slots}):
        held = sorted(n for m, n in slots if m == i)
        if budgets is None:
            runs = [[n] for n in held]
        else:
            runs = _coalesce({n: [unit(k) for k in slots[(i, n)]] for n in held},
                             held, budgets=budgets)
        for r, run in enumerate(runs):
            held_by[("module", i, r)] = [k for n in run for k in slots[(i, n)]]
    loose = sorted((k for k in chosen if k not in owner), key=_sort_key)

    def kept(k: NodeKey) -> list[NodeKey]:
        return [d for d in adj[k] if (k, d) not in cut and d in chosen]

    consumers: dict[NodeKey, list[NodeKey]] = defaultdict(list)
    for k in chosen:
        for d in kept(k):
            consumers[d].append(k)

    # Where each wave goes: its slot's key orders the listing, a dependency
    # before every wave that needs it. A module's wave is keyed by its
    # module's layer and its rank among the module's waves. A unit no module
    # claims is a seed, keyed by its place in the order and listed before
    # that layer's module waves, or a dependency, which goes in the wave
    # right before the first one listed that needs it: that module's
    # previous wave, a new one ahead of its first when there is none; the
    # previous layer's without modules; or, before a seed's wave, a wave of
    # its own.
    slot: dict[NodeKey, tuple] = {}
    for sl, keys in held_by.items():
        for k in keys:
            slot[k] = sl

    def key(sl: tuple) -> tuple:
        if sl[0] == "module":
            _, i, r = sl
            return (stage[("module", i)], r, 1, 0, mods[i].name)
        return sl[1] + ("",)

    for k in sorted(loose, key=lambda k: (-stage[group(k)], _sort_key(k))):
        users = [slot[c] for c in consumers[k]]
        if k in seeds or not users:
            slot[k] = ("loose", (stage[group(k)], -1, 0, 0))
            continue
        first = min(users, key=key)
        if not mods:
            slot[k] = ("loose", (key(first)[0] - 1, -1, 0, 0))
        elif first[0] == "module":
            slot[k] = ("module", first[1], first[2] - 1)
        else:
            layer_, sub, _, r = first[1]
            slot[k] = ("loose", (layer_, sub, 0, r - 1))

    plan: dict[tuple, list[NodeKey]] = {sl: list(keys) for sl, keys in held_by.items()}
    for k in loose:
        plan.setdefault(slot[k], []).append(k)
    order = sorted(plan, key=key)
    index_of = {sl: n for n, sl in enumerate(order)}
    waves = []
    previous: dict[int, int] = {}
    sublayer: dict[int, int] = defaultdict(int)
    for sl in order:
        keys = sorted(plan[sl], key=_sort_key)
        n = index_of[sl]
        module = sl[1] if sl[0] == "module" else None
        # A cut dependency listed before it is met by the order: only one
        # listed after it is cut.
        ds = {index_of[slot[d]] for k in keys for d in kept(k)} - {n}
        cut_ds = {index_of[slot[d]] for k in keys for d in adj[k]
                  if (k, d) in cut} - {n}
        ds |= {w for w in cut_ds if w < n}
        wave = {"index": n, "module": mods[module].name if module is not None else None}
        if module is not None:
            if module in previous:
                ds.add(previous[module])
            previous[module] = n
            wave["sublayer"] = sublayer[module]
            sublayer[module] += 1
        else:
            wave["layer"] = sl[1][0]
        wave.update({
            "depends_on": {"scheduled": sorted(ds),
                           "cut": sorted(w for w in cut_ds if w > n)},
            "unit_count": len(keys),
            "batches": batches_of(keys),
        })
        assert all(d < n for d in wave["depends_on"]["scheduled"]), n
        waves.append(wave)

    # A module's dependencies are those of its scheduled units, which every
    # unit they reach is too: a narrow schedule names no module it leaves out.
    # They pass through the units no module claims, over kept edges, to the
    # module they reach; such a module is ordered before it.
    def module_doc(i: int) -> dict:
        edges_to: dict[int, list] = defaultdict(list)
        for g, es in crossing.items():
            if g[0] == ("module", i) and g[1][0] == "module":
                edges_to[g[1][1]] = [(u, v) for u, v in es if u in chosen]
        through: dict[int, list] = defaultdict(list)
        seen: set[NodeKey] = set()
        pending = [d for u in members[i] if u in chosen for d in kept(u)
                   if d not in owner]
        while pending:
            k = pending.pop()
            if k in seen:
                continue
            seen.add(k)
            for d in kept(k):
                if d not in owner:
                    pending.append(d)
                elif owner[d] != i:
                    through[owner[d]].append((k, d))

        def dep(j: int, is_cut: bool) -> dict:
            es = edges_to[j] + sorted(through[j], key=_sort_key)
            out = {"module": mods[j].name,
                   "unique_edges": len({v for _, v in es}), "total_edges": len(es)}
            if is_cut:
                out["items"] = [{"from": {"name": u[0], "defined_in": u[1]},
                                 "to": {"name": v[0], "defined_in": v[1]},
                                 "kind": route(v)} for u, v in es]
            else:
                out["via_dependency"] = [{"name": k[0], "defined_in": k[1]} for k in
                              sorted({u for u, _ in through[j]}, key=_sort_key)]
            return out
        out_deps = sorted((j for j in set(edges_to) | set(through)
                           if edges_to[j] or through[j]),
                          key=lambda j: mods[j].name)
        # A kept path orders the module it reaches before this one, so no cut
        # separates them.
        assert not any(through[j] and (("module", i), ("module", j)) in group_cut
                       for j in out_deps), mods[i].name
        return {
            "name": mods[i].name,
            "layer": stage[("module", i)],
            "unit_count": sum(1 for k in members[i] if k in chosen),
            "waves": [w["index"] for w in waves if w["module"] == mods[i].name],
            "depends_on": {
                "scheduled": [dep(j, False) for j in out_deps
                              if (("module", i), ("module", j)) not in group_cut],
                "cut": [dep(j, True) for j in out_deps
                        if (("module", i), ("module", j)) in group_cut],
            },
        }

    listed = sorted({owner[k] for k in chosen if k in owner},
                    key=lambda i: (stage[("module", i)], mods[i].name))
    return {
        "schema_version": 4,
        "oracle_config": layout.config_provenance(),
        "api_headers_only": api_headers_only,
        "with_enums": with_enums,
        "with_macros": with_macros,
        "caps": caps,
        "summary": {
            "unit_count": len(chosen),
            "seeded_count": len(seeds),
            "module_count": len(listed),
            "wave_count": len(waves),
            "batch_count": sum(len(w["batches"]) for w in waves),
            "cut_count": sum(1 for u, v in cut if u in chosen or v in chosen),
        },
        "modules": [module_doc(i) for i in listed],
        "waves": waves,
    }


def write_wave(path: Path, wave: dict) -> None:
    path = Path(path)
    if not path.parent.is_dir():
        raise SystemExit(
            f"schedule: output directory does not exist: {path.parent}")
    path.write_text(json.dumps(wave, indent=2) + "\n")
