"""manifests.py — the type / symbol records, composed on demand.

The composer emits the structural half from the CodeQL tables; the authored
half comes from `ownership-store.json` (:mod:`wavefront.store`). A consumer sees
the whole record.

Composing costs 1.7s for types and 2.2s for symbols, and narrowing does not
reduce it: the work is parsing the T1/T2 tables and building the indexes, not
the per-entry emit. Memoized per `(repo_root, target, kind)` for the process.
"""
from __future__ import annotations

import json
from pathlib import Path

from wavefront.layout import Layout


#: (repo_root, target, kind) -> {rel_dir: [entry]}. Process-lifetime: the CSVs
#: and the store cannot change under a running stage.
_CACHE: dict[tuple[str, str, str], dict] = {}

_ENTRIES_KEY = {"types": "types", "symbols": "symbols"}


def build(layout: Layout, target: Path, kind: str, *, stage: str,
          scoped: bool = True) -> dict:
    """``{rel_dir: [entry]}`` for ``kind`` (``"types"`` | ``"symbols"``),
    skeleton composed and store overlaid.

    ``rel_dir`` groups by source stem — the vocabulary `crates.json` and every
    provenance-reporting caller uses.

    ``scoped=False`` drops the scope seed and composes the whole CodeQL
    universe. Enumeration stays scoped; a *named* lookup falls back to the
    universe so an agent can read and analyse an entity its target does not
    own — a destructor in another scope still decides this target's ownership.
    Both emits cost the same (~2.4s): the work is parsing the tables.
    """
    if kind not in _ENTRIES_KEY:
        raise ValueError(f"unknown manifest kind: {kind!r}")
    ck = (str(layout.repo_root), str(target), kind, scoped)
    hit = _CACHE.get(ck)
    if hit is not None:
        return hit

    from compose.filter_spec import FilterSpec
    from wavefront import scope as _scope_mod, store as _store

    if kind == "types":
        from compose.types_manifest import compose as _compose
    else:
        from compose.syms_manifest import compose as _compose

    t1 = layout.t1
    if not (t1 / "functions.csv").is_file():
        raise SystemExit(
            f"{stage}: no CodeQL T1 tables at {t1}. "
            f"Run `wavefront {layout.repo_root} extract-ql` first.")

    # `scope_json_path=None` disables the seed gate and port/wrap
    # classification, widening the emit to the repo-wide universe.
    spec = FilterSpec(scope_json_path=(
        _scope_mod.build(layout, target, stage=stage) if scoped else None))
    by_dir, _dir_scope, _focus = _compose(t1, layout.t2, spec)
    by_dir = _dedup(by_dir, kind)

    doc = _store.load(layout)
    ti, si = _store.index(doc)
    overlay = _store.overlay_type if kind == "types" else _store.overlay_sym
    keyfn = _store.type_key if kind == "types" else _store.sym_key
    idx = ti if kind == "types" else si
    for entries in by_dir.values():
        for e in entries:
            overlay(e, idx.get(keyfn(e)))

    if kind == "symbols":
        _materialize_forks(by_dir, doc)

    _annotate_cpp(by_dir, kind, layout)

    for entries_ in by_dir.values():
        for e in entries_:
            e["_analysis"] = analysis_state(e, kind, keyfn(e) in idx)

    _CACHE[ck] = by_dir
    return by_dir


def _annotate_cpp(by_dir: dict, kind: str, layout: Layout) -> None:
    """Add what a C++ codebase's type system states to its records
    (:mod:`compose.cpp_facts`): on a class, its declarations, lifecycle and
    implementers, and on each field what its type says of ownership,
    nullability and cardinality; on a member, the class it implements; on a
    function, the same for each parameter and its return. Composed, not
    findings: the type states them. A C codebase has no `cpp_*` rows, and its
    records are unchanged."""
    from compose import cpp_facts as _cpp

    facts = _cpp.load(layout.codeql)
    if not facts:
        return
    if kind == "types":
        by_class: dict = {}
        for mkey, row in facts.members.items():
            ckey = (row["class_name"], row.get("class_def_file") or "")
            by_class.setdefault(ckey, []).append((mkey, row))
        for entries_ in by_dir.values():
            for e in entries_:
                key = (e.get("name") or "", e.get("defined_in") or "")
                info = facts.class_info(key)
                if info is None:
                    continue
                members = sorted(by_class.get(key, ()), key=lambda m: m[0])
                info["lifecycle"] = [
                    {"name": n, "defined_in": f or None, "member_kind": r["member_kind"],
                     **({"role": _cpp.LIFECYCLE_ROLES[r["member_kind"]]}
                        if r.get("deleted") != "true" else {"deleted": True})}
                    for (n, f), r in members if r["member_kind"] in _cpp.LIFECYCLE_KINDS]
                info["implementers"] = [
                    {"name": n, "defined_in": f or None, "member_kind": r["member_kind"],
                     **({"accessor": {"kind": r["accessor"], "field": r.get("accessor_field") or ""}}
                        if r.get("accessor") else {})}
                    for (n, f), r in members if r["member_kind"] not in _cpp.LIFECYCLE_KINDS]
                e["cpp"] = info
                slots = _cpp.slots_of(facts, "field", key)
                for fld in e.get("fields") or []:
                    if isinstance(fld, dict) and fld.get("name") in slots:
                        fld["cpp"] = slots[fld["name"]]
        return
    for entries_ in by_dir.values():
        for e in entries_:
            key = (e.get("name") or "", e.get("defined_in") or "")
            member = facts.member_info(key)
            if member is not None:
                e["member"] = member
            kind_ = e.get("kind") or ""
            if kind_.startswith("global"):
                g = _cpp.slots_of(facts, "global", key)
                if g:
                    e["cpp"] = g.get("") or next(iter(g.values()))
                continue
            params = _cpp.slots_of(facts, "param", key)
            ret = _cpp.slots_of(facts, "return", key).get("ret")
            if params or ret:
                e["cpp"] = {"params": params, **({"return": ret} if ret else {})}


def analysis_state(entry: dict, kind: str, submitted: bool,
                   keep: set | None = None) -> dict:
    """Whether this entity's ownership analysis exists, and what it still owes.

    Derived at read time, never stored.

    `submitted` answers what a null slot cannot: `lifetime: null` reads the
    same whether nobody has looked or an agent looked and found no lifecycle
    role.

    `pending` lists the pointer slots carrying no ownership block — the
    entity's remaining work. ``keep`` narrows it to a field-name set, so under
    `--closure-only` / `--external-only` it counts only the fields that section's code
    touches and agrees with what `--fields` shows.
    """
    pending: list[str] = []
    if kind == "types":
        for f in entry.get("fields") or []:
            if not isinstance(f, dict) or f.get("ref") != "pointer" or f.get("ptr"):
                continue
            if keep is not None and f.get("name") not in keep:
                continue
            pending.append(f"fields.{f.get('name')}.ptr")
    else:
        for a in entry.get("ptr_args") or []:
            if isinstance(a, dict) and not a.get("ptr"):
                pending.append(f"ptr_args.{a.get('name')}.ptr")
        ret = entry.get("ptr_ret")
        if isinstance(ret, dict) and not ret.get("ptr"):
            pending.append("ptr_ret.ptr")
    return {"submitted": submitted, "pending": pending}


def _dedup(by_dir: dict, kind: str) -> dict:
    """Collapse composer entries that share a key.

    The composer emits the same entity twice in a handful of cases — seven in
    the ssl target, each a symbol whose return type it spells once as the
    typedef and once as the tag (`EVP_PKEY *` / `evp_pkey_st *`). Without this
    the record a consumer gets would depend on iteration order.

    Composer keys are add-missing, so the first spelling wins; `depends_on` and
    `used_by` union.
    """
    from compose.manifest_merge import merge_entries, symbol_key, type_key

    keyfn = type_key if kind == "types" else symbol_key
    out: dict = {}
    for rel, entries in by_dir.items():
        merged, _a, _u = merge_entries([], entries, key=keyfn)
        out[rel] = merged
    return out


def _materialize_forks(by_dir: dict, doc: dict) -> None:
    """Create the entries for agent-declared callback FORKS.

    A function-pointer typedef whose invokers realize different ownership
    contracts is split into several entries sharing a ``name``, keyed apart by
    ``variant``. The composer emits only the primary (variant 0) — a fork is an
    agent's judgement that one C declaration carries two contracts — so a fork
    is materialized by cloning the primary and applying its findings, not
    overlaid onto a composed entry.
    """
    from wavefront import store as _store

    primaries: dict[tuple[str, str], tuple] = {}
    for rel, entries in by_dir.items():
        for e in entries:
            if not e.get("variant"):
                primaries[(e["name"], e.get("defined_in") or "")] = (rel, e)

    for rec in doc.get("symbols") or []:
        if not rec.get("variant"):
            continue
        hit = primaries.get((rec["name"], rec.get("defined_in") or ""))
        if hit is None:
            continue
        rel, primary = hit
        clone = json.loads(json.dumps(primary))
        clone["variant"] = rec["variant"]
        _store.overlay_sym(clone, rec)
        # The primary's `used_by` is every invoker of the one C declaration; a
        # fork's is the authored subset realizing ITS contract. `ref` stays
        # empty — a reference to the typedef names no variant.
        if rec.get("callsites") is not None:
            clone["used_by"] = {"call": list(rec["callsites"]), "ref": []}
            # The variants PARTITION the invoker set, so the primary drops
            # what a fork claims. Derived here rather than stored, so a new
            # invoker cannot leave the split stale.
            pu = primary.setdefault("used_by", {})
            taken = set(rec["callsites"])
            pu["call"] = [c for c in (pu.get("call") or []) if c not in taken]
        by_dir[rel].append(clone)


def entries(layout: Layout, target: Path, kind: str, *, stage: str,
            scoped: bool = True) -> list:
    """Every entry of ``kind``, flattened."""
    return [e for v in build(layout, target, kind, stage=stage,
                             scoped=scoped).values()
            for e in v]
