"""Dependency-graph model and shared readers.

The graph is deterministically composed from C facts and stored only in a
fingerprinted private cache. Scheduling and ``query dag`` share this node model,
type metadata, and canonical lifecycle-operation ordering.

The ordering in particular is shared ON PURPOSE — :func:`ordered_ops` is the one
definition both the scheduler and ``query types --lifecycle-ops`` consume, so the two
never disagree on a type's op set or its order.
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable


#: Every node's identity, types and symbols alike: ``(name, defined_in, kind)``,
#: ``kind`` being ``"type"`` or ``"symbol"``. A bare name is ambiguous on BOTH
#: sides — same-named file-local statics, and TU-local aggregates (a `struct
#: version_info` per `.c` that declares one) — and ``(name, defined_in)`` is
#: ambiguous ACROSS them: ``static const struct typelen {...} typelen[]`` is a
#: type and a global of one name in one file.
NodeKey = tuple[str, "str | None", str]

#: Historical alias. Kept because the scheduler's public signatures read
#: `SymKey` throughout and the two are the same tuple.
SymKey = NodeKey


# --------------------------------------------------------------------- model

@dataclass
class Node:
    id: str                       # type tag, or symbol name
    node_kind: str                # "type" | "symbol"
    subkind: str                  # struct/.../function_*/macro_*/"symbol" (bare)
    defined_in: str | None
    layer: int
    dep_types: list[NodeKey]
    dep_syms: list[NodeKey]
    # Cut cycle back-edges (FAS): types this node depends on that aren't wrapped
    # yet (render raw `ffi::T`); and the reverse — nodes that render *this* type
    # raw and should switch to its wrapper once it lands.
    fallback: list[NodeKey] = field(default_factory=list)
    back_fill: list[NodeKey] = field(default_factory=list)
    # Per-symbol lines-of-code (CodeQL body span; global=1, macro=0, 0 when the
    # `loc` column is absent — for a type node it is the struct field count).
    # Summed per batch against the port LoC budget.
    loc: int = 0
    #: Types this macro mints, when it is a template generator (else empty).
    #: Non-empty is what exempts it from the wrap stage's macro exclusion.
    type_generator_for: list[str] = field(default_factory=list)
    # C++ only: a class's declarations, with the lifecycle folded into it
    # (`cpp`), and a member's relation to the class it implements (`member`).
    cpp: dict | None = None
    member: dict | None = None

    @property
    def key(self) -> NodeKey:
        return (self.id, self.defined_in, self.node_kind)

    @property
    def is_bare(self) -> bool:
        # the DAG emits "symbol" when nothing has classified `kind` yet
        return self.node_kind == "symbol" and self.subkind == "symbol"


def build(layout, target: Path, *, stage: str,
          api_headers_only: bool = False) -> dict:
    """Compose this target's DAG **in memory** and return it.

    Both sides come from :mod:`wavefront.manifests` -- there is no analysis tree
    to walk. The graph is a function of the CodeQL tables and `in-memory inventory`
    alone; the store overlay contributes nothing to it, by design (a
    submission must never move a layer).

    ``api_headers_only`` selects the public-signature graph; the default is the
    implementation/body-deep graph.
    """
    from compose.deps_dag import compose as _compose
    from wavefront import cache as _cache, manifests as _manifests, scope as _scope

    # The dag cache is the valuable one: a hit skips scope AND both manifest
    # composes, not just the layering — 5.8s down to a 4.7 MB parse. Its
    # fingerprint is the same input set, since the graph is a function of the
    # CodeQL tables and scope alone (an agent submission never moves a layer).
    fp = _cache.fingerprint(layout, target)
    disk = _cache.load(layout.deps_dag(
        target, api_headers_only=api_headers_only), fp)
    if disk is not None:
        return disk

    dag = _compose(
        (_manifests.entries(layout, target, "types", stage=stage),
         _manifests.entries(layout, target, "symbols", stage=stage)),
        _scope.build(layout, target, stage=stage),
        codeql_dir=layout.codeql,
        api_headers_only=api_headers_only,
    )
    return _cache.store(layout.deps_dag(
        target, api_headers_only=api_headers_only), dag, fp)


def load_nodes(dag: dict) -> tuple[dict[SymKey, Node], dict[str, list[SymKey]]]:
    """Flatten a composed DAG into ``(by_key, by_name)``. SCC super-nodes are
    flattened to their members (each member keeps its own deps/layer)."""
    by_key: dict[SymKey, Node] = {}
    by_name: dict[str, list[SymKey]] = {}

    def keys(group: dict | None, side: str) -> list[NodeKey]:
        kind = "type" if side == "types" else "symbol"
        return [(d["name"], d.get("defined_in"), kind)
                for d in (group or {}).get(side) or []]

    def add(rec: dict, layer: int) -> None:
        deps = rec.get("deps") or {}
        n = Node(
            id=rec["id"],
            node_kind=rec["node_kind"],
            subkind=str(rec.get("subkind") or "symbol"),
            defined_in=rec.get("defined_in"),
            layer=layer,
            dep_types=keys(deps, "types"),
            dep_syms=keys(deps, "syms"),
            fallback=keys(rec.get("fallback"), "types"),
            back_fill=keys(rec.get("back_fill"), "types"),
            loc=int(rec.get("loc") or 0),
            type_generator_for=list(rec.get("type_generator_for") or ()),
            cpp=rec.get("cpp"),
            member=rec.get("member"),
        )
        by_key[n.key] = n
        by_name.setdefault(n.id, []).append(n.key)

    for layer, entries in enumerate(dag.get("layers", [])):
        for rec in entries:
            if "scc" in rec:
                deps = rec.get("deps")
                for m in rec["scc"]:
                    m = dict(m)
                    m.setdefault("deps", deps)
                    add(m, layer)
            else:
                add(rec, layer)
    return by_key, by_name


def select(
    names: list[str],
    by_key: dict[NodeKey, Node],
    by_name: dict[str, list[NodeKey]],
    files: set[str] | None = None,
    kind: str | None = None,
) -> tuple[list[NodeKey], list[str]]:
    """Resolve each ``--name`` to EVERY node it names, ``--file`` and ``kind``
    narrowing them, and return ``(keys, unknown names)``.

    A bare name is a query, not an identity: `ring_buf` is two unrelated
    structs, `stat` a type and a syscall, `typelen` a struct and the array of
    it in one file. A reading query reports every match, each labelled with
    its kind and defining file, so the caller can tell them apart; what needs
    one entity picks it with :func:`ambiguous`.
    """
    file_set = set(files or [])
    keys: list[NodeKey] = []
    unknown: list[str] = []
    for nm in dict.fromkeys(names or []):
        hit = [k for k in dict.fromkeys(by_name.get(nm, []))
               if (not file_set or (by_key[k].defined_in or "") in file_set)
               and (kind is None or k[2] == kind)]
        (keys.extend(hit) if hit else unknown.append(nm))
    return keys, unknown


def ambiguous(keys: list[NodeKey], *, stage: str, by_file: bool = True) -> None:
    """Refuse a selection that must name one entity but names several. Each
    candidate is listed with its kind and defining file. With ``by_file``,
    only candidates in different files count: a type and a symbol of one name
    in one file are both the caller's."""
    by_name: dict[str, list[NodeKey]] = {}
    for k in keys:
        by_name.setdefault(k[0], []).append(k)
    bad = {nm: ks for nm, ks in by_name.items()
           if len({k[1] for k in ks} if by_file else ks) > 1}
    if not bad:
        return
    lines = []
    for nm, ks in bad.items():
        lines.append(f"  - {nm}  ({len(ks)} nodes)")
        lines.extend(f"      {k[2]:<6} --file {k[1] or '<no defining file>'}"
                     for k in ks)
    raise SystemExit(
        f"{stage}: {len(bad)} name(s) resolve to more than one node — "
        f"pass --file to pick one:\n" + "\n".join(lines))


def ordered_ops(node: Node, by_key: dict[SymKey, Node], lifecycle: set[str],
                in_scope: Callable[[Node], bool]) -> list[Node]:
    """A type's ops as the **canonical, windowable list**: the symbol nodes named
    by ``lifecycle`` that are ``in_scope``, ordered **lifecycle-first**
    (droppers/disposers/cloners/constructors) then alphabetical. This is the
    ordering ``query types --name T --lifecycle-ops`` reports.

    Membership comes from ``lifecycle`` — the op-name set reverse-derived from
    the analysis tree's ``lifetime`` records (``_resolve`` in query) — and not
    from the DAG, so a submission shows up without rebuilding the graph.

    A lifetime record names a FUNCTION, not a ``(name, defined_in)`` key, so
    membership is by id over ``by_key``; ``node_kind`` guards the case of a type
    tag colliding with an op name. Same-named statics in several files all
    qualify, as the dag's null-``defined_in`` fallback did."""
    ops = [n for n in by_key.values()
           if n.node_kind == "symbol" and n.id in lifecycle and in_scope(n)]
    ops.sort(key=lambda o: (o.id not in lifecycle, o.id))
    return ops


def load_type_meta(entry_pair, *, by_file: bool = False) -> dict:
    """type tag -> (field names, lifecycle op names), or ``(tag, defined_in)``
    -> the same with ``by_file``, so same-tagged TU-local aggregates keep their
    own fields. Fields drive the
    agent's accessor working set; the lifecycle set names its ops. Neither is a
    budget any more — a type is one batch.

    A type stores no lifecycle of its own — it is reverse-derived from the
    symbols whose ``lifetime`` acts on that type (droppers, cloners,
    field-disposers, constructors). These are agent findings, recorded as facts
    and reported by `query`; the scheduler reads only the fields, since a plan
    is made before any finding exists.

    Takes the composed ``(types, syms)`` pair, so it reads the same records
    `query` reports — one source, no fork to keep in step. Isolating an experimental arm is a
    git branch now, which is what ``--out-suffix`` was hand-rolling with
    filenames."""
    from compose.scope import build_lifecycle_index, type_method_syms

    meta: dict = {}
    types, syms = entry_pair
    lifecycle = build_lifecycle_index((types, syms))
    for e in types:
        tag = e.get("name") or e.get("type")
        key = (tag, e.get("defined_in")) if by_file else tag
        if not tag or key in meta:
            continue
        fields = [x["name"] for x in (e.get("fields") or []) if x.get("name")]
        meta[key] = (fields, set(type_method_syms(e, lifecycle)))
    return meta
