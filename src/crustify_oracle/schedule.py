"""Deterministic campaign planning over the oracle dependency graph."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from crustify_oracle.dag import Node, NodeKey, load_nodes, load_type_meta


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


def _resolve(names: list[str], by_key, by_name,
             keep: Callable[[Node], bool], *, require_unambiguous: bool = True) -> list[Node]:
    out: list[Node] = []
    seen: set[NodeKey] = set()
    unknown: list[str] = []
    for name in names:
        hits = [by_key[k] for k in by_name.get(name, ()) if keep(by_key[k])]
        if require_unambiguous and len(hits) > 1:
            homes = "\n".join(
                f"      --file {node.defined_in or '<no defining file>'}"
                for node in hits)
            raise SystemExit(
                f"schedule: {name!r} resolves to {len(hits)} nodes — pass "
                f"--file to pick one:\n{homes}")
        if not hits:
            unknown.append(name)
        for node in hits:
            if node.key not in seen:
                seen.add(node.key)
                out.append(node)
    if unknown:
        print(f"schedule: no in-scope match for: {', '.join(unknown)}", file=sys.stderr)
    if not out:
        raise SystemExit("schedule: nothing selected in scope.")
    bare = sorted((n.id, n.defined_in or "?") for n in out if n.is_bare)
    if bare:
        listing = "\n".join(f"  - {name}  ({home})" for name, home in bare)
        raise SystemExit(
            f"schedule: {len(bare)} selected symbol(s) are unclassified "
            f"(kind=null). Rebuild the CodeQL tables or fix symbol "
            f"classification before translation:\n{listing}")
    return out


def _closure(seeds: list[Node], by_key) -> list[Node]:
    pending = list(seeds)
    seen: set[NodeKey] = set()
    out: list[Node] = []
    while pending:
        node = pending.pop(0)
        if node.key in seen:
            continue
        seen.add(node.key)
        out.append(node)
        for key in [*node.dep_types, *node.dep_syms]:
            if key in by_key and key not in seen:
                pending.append(by_key[key])
    return out


def _pack(units: list[Unit], *, max_syms: int, max_loc: int | None,
          max_types: int, min_fields: int) -> list[Batch]:
    batches: list[Batch] = []
    types = [u for u in units if u.route == "type"]
    symbols = [u for u in units if u.route != "type"]

    chunk: list[Unit] = []
    fields = 0
    for unit in types:
        nfields = len(unit.fields)
        if chunk and (len(chunk) >= max_types or fields >= min_fields
                      or nfields >= min_fields):
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
            if chunk and (len(chunk) >= max_syms
                          or (max_loc and loc + item_loc > max_loc)):
                batches.append(Batch(list(chunk), None))
                chunk, loc = [], 0
            chunk.append(unit)
            loc += item_loc
        if chunk:
            batches.append(Batch(list(chunk), None))
    return batches


def _coalesce(by_layer: dict[int, list[Unit]], layers: list[int], *, closed: bool,
              budgets: dict) -> list[list[int]]:
    if not closed:
        return [[layer] for layer in layers]
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


def _node_doc(node: Node) -> dict:
    def refs(keys):
        return [{"name": name, "defined_in": home} for name, home in keys]
    return {
        "name": node.id,
        "defined_in": node.defined_in,
        "kind": ("type" if node.node_kind == "type" or is_generator(node)
                 else "callback" if node.subkind == "callback" else "symbol"),
        "source_kind": node.subkind,
        "layer": node.layer,
        "loc": node.loc,
        "deps": {"types": refs(node.dep_types), "symbols": refs(node.dep_syms)},
        "fallback": refs(node.fallback),
        "back_fill": refs(node.back_fill),
        "generates": list(node.generates),
    }


def _field_anchors(layout, target: Path, *,
                   api_headers_only: bool = False) -> dict[NodeKey, list[str]]:
    """Return accessor TODOs keyed by the type's full graph identity.

    An API-only campaign exposes fields only when the aggregate definition is
    itself published by an ``api_headers`` file.  A public forward declaration
    may resolve to a private definition so the wrapper can bind the type, but
    that private layout must remain opaque.  Keying by ``(tag, defined_in)``
    also prevents a public definition from donating its fields to an unrelated
    private aggregate with the same tag.
    """
    from compose import scope as compose_scope
    from crustify_oracle import manifests, scope
    from crustify_oracle.query import scope_touched_index

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
        key = (tag, defined_in)
        if api_paths is not None and defined_in not in api_paths:
            out[key] = []
            continue
        names = [f["name"] for f in entry.get("fields") or []
                 if isinstance(f, dict) and f.get("name")]
        if touched is not None:
            names = [name for name in names if name in touched.get(tag, set())]
        out[key] = names
    return out


def build_campaign(layout, target: Path, *, names: list[str] | None,
                   files: list[str] | None = None, dag_layer: int | None = None,
                   skip: list[str] | None = None, transitive: bool = False,
                   api_headers_only: bool = False, max_syms: int = 50,
                   max_loc: int | None = 1000, max_types: int = 5,
                   min_fields: int = 10, force: bool = False) -> dict:
    """Return a stable, objective-neutral campaign document."""
    from collections import defaultdict
    from compose import scope as compose_scope
    from crustify_oracle import dag as dag_mod, manifests, scope

    inventory = scope.build(layout, target, stage="schedule")
    graph = dag_mod.build(layout, target, stage="schedule",
                          api_headers_only=api_headers_only)
    by_key, by_name = load_nodes(graph)
    allowed = set()
    for section in compose_scope.SECTIONS:
        for kind in ("functions", "globals", "macros", "types"):
            allowed |= compose_scope.load_entities(inventory, section, kind)
    api_allowed = set()
    for kind in ("functions", "globals", "macros", "types"):
        api_allowed |= compose_scope.load_entities(inventory, compose_scope.API, kind)
    imported_allowed = set()
    for kind in ("functions", "globals", "macros", "types"):
        imported_allowed |= compose_scope.load_entities(
            inventory, compose_scope.IMPORTED, kind)
    file_set = set(files or ())
    def keep_scope(node: Node) -> bool:
        if file_set and (node.defined_in or "") not in file_set:
            return False
        if ((node.subkind or "").startswith("macro")
                and node.node_kind == "symbol" and not is_generator(node)):
            return False
        keys = {(node.id, node.defined_in or ""), (node.id, "")}
        return bool(keys & allowed)

    def keep_seed(node: Node) -> bool:
        if not keep_scope(node):
            return False
        if not api_headers_only:
            return True
        keys = {(node.id, node.defined_in or ""), (node.id, "")}
        return bool(keys & api_allowed)

    selected_names = list(names or ())
    if dag_layer is not None:
        selected_names += sorted({n.id for n in by_key.values()
                                  if n.layer == dag_layer and keep_seed(n)})
    nodes = _resolve(selected_names, by_key, by_name, keep_seed,
                     require_unambiguous=dag_layer is None)
    if transitive:
        closure_names = sorted({n.id for n in _closure(nodes, by_key)
                                if keep_scope(n)})
        nodes = _resolve(closure_names, by_key, by_name, keep_scope,
                         require_unambiguous=False)
    blocked = set(skip or ())
    nodes = [n for n in nodes if n.id not in blocked]
    if not nodes:
        raise SystemExit("schedule: nothing selected in scope.")

    pair = (manifests.entries(layout, target, "types", stage="schedule"),
            manifests.entries(layout, target, "symbols", stage="schedule"))
    declared = load_type_meta(pair)
    bound_ops = {op for _tag, (_fields, ops) in declared.items() for op in ops}
    for entry in pair[1]:
        lifetime = entry.get("lifetime")
        if isinstance(lifetime, dict) and any(lifetime.get(key) for key in (
                "is_dropper", "is_disposer", "is_cloner")):
            bound_ops.add(entry.get("name"))
    if not force:
        dropped = sorted({node.id for node in nodes if node.id in bound_ops})
        if dropped:
            print(f"[crustify-oracle schedule] dropped {len(dropped)} lifecycle "
                  "primitive(s) emitted by their owning type or raw tier: "
                  + ", ".join(dropped[:8]) + (" …" if len(dropped) > 8 else ""))
            nodes = [node for node in nodes if node.id not in bound_ops]
    if not nodes:
        raise SystemExit("schedule: nothing selected after lifecycle filtering")
    anchors = _field_anchors(layout, target,
                             api_headers_only=api_headers_only)
    def section(node: Node) -> str:
        key = (node.id, node.defined_in or "")
        return "imported" if key in imported_allowed else "targeted"
    units = [Unit(n, list(declared.get(n.id, ([], set()))[0]), section(n))
             for n in nodes]
    by_layer: dict[int, list[Unit]] = defaultdict(list)
    for unit in units:
        by_layer[unit.node.layer].append(unit)
    layers = sorted(by_layer)
    budgets = {"max_syms": max_syms, "max_loc": max_loc,
               "max_types": max_types, "min_fields": min_fields}
    wave_layers = _coalesce(by_layer, layers,
                            closed=transitive and not blocked, budgets=budgets)
    waves = []
    batch_count = 0
    batch_files: set[str | None] = set()
    for group in wave_layers:
        wave_units = [u for layer in group for u in by_layer[layer]]
        batches = _pack(wave_units, **budgets)
        batch_count += len(batches)
        batch_files |= {batch.file for batch in batches}
        waves.append({
            "layers": group,
            "unit_count": len(wave_units),
            "batches": [{
                "kind": batch.route,
                "source_file": batch.file,
                "items": [{**_node_doc(unit.node),
                           "field_anchors": anchors.get(unit.node.key, [])}
                          for unit in batch.units],
            } for batch in batches],
        })
    return {
        "schema_version": 1,
        "oracle_target": layout.rel_target(target),
        "api_headers_only": api_headers_only,
        "budgets": budgets,
        "summary": {"unit_count": len(units), "layer_count": len(layers),
                    "batch_count": batch_count, "file_count": len(batch_files)},
        "plan_items": [_node_doc(unit.node) for unit in units],
        "dependency_nodes": [
            {**_node_doc(by_key[key]),
             "in_scope": keep_scope(by_key[key])}
            for key in sorted({key for node in nodes
                               for key in [*node.dep_types, *node.dep_syms]
                               if key in by_key} - {node.key for node in nodes},
                              key=lambda key: (key[0], key[1] or ""))
        ],
        "waves": waves,
    }


def build_raw_lifetime_campaign(layout, target: Path, spec: str) -> dict:
    if spec not in ("void", "string"):
        raise SystemExit("schedule: --lifetime-for must be void or string")
    item = {"name": spec, "defined_in": None, "kind": "raw-lifetime",
            "source_kind": "raw-lifetime", "layer": 0, "loc": 0,
            "deps": {"types": [], "symbols": []}, "fallback": [],
            "back_fill": [], "generates": [], "field_anchors": []}
    return {
        "schema_version": 1, "oracle_target": layout.rel_target(target),
        "api_headers_only": False,
        "budgets": {"max_syms": 1, "max_loc": None,
                    "max_types": 1, "min_fields": 0},
        "summary": {"unit_count": 1, "layer_count": 1,
                    "batch_count": 1, "file_count": 1},
        "plan_items": [item], "dependency_nodes": [],
        "waves": [{"layers": [0], "unit_count": 1, "batches": [{
            "kind": "raw-lifetime", "source_file": f"lifetime-for-{spec}",
            "items": [item],
        }]}],
    }


def write_campaign(path: Path, campaign: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(campaign, indent=2) + "\n")
