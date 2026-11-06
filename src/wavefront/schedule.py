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
            and bool(node.generates))


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
    from wavefront import selection
    from wavefront.order import _cut, _full_edges, _layers, _sort_key
    from wavefront.stats import Stats

    # `max_loc` 0 bounds nothing, as an absent cap: it must not turn packing,
    # and with it the folding of layers, on.
    caps = {k: (caps or {}).get(k) or None if k == "max_loc"
            else (caps or {}).get(k) for k in CAPS}
    budgets = caps if any(v is not None for v in caps.values()) else None

    config = json.loads(layout.config(target).read_text())
    entries = selection.load(config, layout.repo_root)
    closure_files = set(targeted_candidates(config, layout.repo_root))

    inventory = scope.build(layout, target, stage="schedule")
    decls = selection.declarations(inventory)
    graph = dag_mod.build(layout, target, stage="schedule",
                          api_headers_only=api_headers_only)
    by_key, _ = load_nodes(graph)
    edges, weights = _full_edges(graph)

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

    if entries is not None:
        selection.check(entries, decls,
                        {k for k, n in by_key.items() if is_unit(n)})

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

    # The order, over every unit; a schedule keeps its units in it.
    def weight(u: NodeKey, v: NodeKey) -> int:
        return weights.get((u, v), 1)

    ordered = sorted(units, key=_sort_key)
    adj = {k: {d for d in edges.get(k, ()) if d in units} for k in ordered}
    cut = _cut(ordered, adj, weight)
    layer = _layers(ordered, {k: {d for d in ds if (k, d) not in cut}
                              for k, ds in adj.items()})
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

    def refs(keys, kind=None):
        return [ref(k) for k in sorted(keys, key=_sort_key)
                if kind is None or k[2] == kind]

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
            "layer": layer[key],
            "loc": node.loc,
            "stats": stats.of(node.id, node.defined_in, node.node_kind,
                              node.subkind),
            "deps": {"types": refs(deps, "type"), "symbols": refs(deps, "symbol")},
            "higher_cuts": refs(higher),
            "lower_cuts": refs(lower.get(key, ())),
            "generates": list(node.generates),
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

    by_layer: dict[int, list[NodeKey]] = defaultdict(list)
    for k in sorted(chosen, key=_sort_key):
        by_layer[layer[k]].append(k)
    layers = sorted(by_layer)
    if budgets is None:
        groups = [[n] for n in layers]
    else:
        groups = _coalesce({n: [unit(k) for k in by_layer[n]] for n in layers},
                           layers, budgets=budgets)
    waves = []
    for group in groups:
        keys = [k for n in group for k in by_layer[n]]
        waves.append({"index": len(waves), "layers": group,
                      "unit_count": len(keys), "batches": batches_of(keys)})

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
            "wave_count": len(waves),
            "batch_count": sum(len(w["batches"]) for w in waves),
            "cut_count": sum(1 for u, v in cut if u in chosen or v in chosen),
        },
        "waves": waves,
    }


def write_wave(path: Path, wave: dict) -> None:
    path = Path(path)
    if not path.parent.is_dir():
        raise SystemExit(
            f"schedule: output directory does not exist: {path.parent}")
    path.write_text(json.dumps(wave, indent=2) + "\n")
