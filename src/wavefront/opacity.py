"""When each unit's last user is processed: the layout users of a struct,
union or enum, and the referrers of a function, global, macro, function
pointer or typedef, and the point of a schedule after which none of them is
left to process.

A type is *opaque* after its layout users: once every unit that reads its
members, size or alignment, names an enum's enumerators, or holds it by value,
has been processed, what comes after holds it only through pointers. A
function, global, macro, function pointer or typedef is *unreferenced* after
its referrers: once every unit that calls it, takes its address, reads it,
expands it or names it has been processed.

A function pointer written inline has no name to refer to it by: C needs its
signature for as long as anything reaches a site that writes it. A field's
reaches it through the struct, so its users are the struct's layout users; a
parameter's or a return's, through the function, so they are the function's
referrers, and a global's the global's; a local's or a cast's, nothing but
the function. Each site is a user too, and so are all of them when one
signature is written at several (:func:`inline_users`). Both are objective-neutral facts of the order; what a consumer
does at that point is its own.

The users are units of the closure, scheduled or not: an entity that is no
unit, such as an external function or a test the closure leaves out, does
not count. A macro's layout uses are recorded where it is expanded, so a
macro is never a layout user; the units that expand it are. A type that another holds by value
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
from typing import NamedTuple

from compose.scope import load_csv
from wavefront.dag import NodeKey
from wavefront.order import _sort_key

#: The layout-use kinds of ``t2/layout_uses.csv``.
USE_KINDS = ("field", "size", "value", "index", "embed", "constant")


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
    functions and globals every edge is a reference; an edge into a macro is
    an expansion, from a function's body or a type's declaration."""
    out: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    for u, ds in edges.items():
        if not is_referrer(u):
            continue
        for d in ds:
            if d != u and is_target(d):
                out[d].add(u)
    return dict(out)


#: How each kind of site of an inline function pointer is reached from outside.
SITE_REACH = {"field": "layout", "param": "referrers", "return": "referrers",
              "global": "referrers", "local": "self", "cast": "self"}


def load_function_pointer_sites(t2: Path) -> dict[NodeKey, set[tuple[NodeKey, str]]]:
    """``{function pointer key: {(site key, use kind)}}`` from
    ``t2/function_pointer_uses.csv``: every site that writes an inline
    function pointer, keyed as the graph keys both."""
    path = t2 / "function_pointer_uses.csv"
    out: dict[NodeKey, set[tuple[NodeKey, str]]] = defaultdict(set)
    if not path.is_file():
        return {}
    for r in load_csv(path):
        fp = (r["signature"], r["def_file"], "symbol")
        ns = "type" if r["user_kind"] == "type" else "symbol"
        out[fp].add(((r["user_name"], r.get("user_def_file") or "", ns), r["use_kind"]))
    return dict(out)


def inline_users(sites, layout_users: dict, refs: dict) -> set[NodeKey]:
    """The users of an inline function pointer written at ``sites``: each
    site, and what reaches it from outside (:data:`SITE_REACH`), a field's
    struct through its layout users, a parameter's, return's or global's
    owner through its referrers."""
    out: set[NodeKey] = set()
    for site, use in sites:
        out.add(site)
        reach = SITE_REACH.get(use, "self")
        if reach == "layout":
            out |= set(layout_users.get(site, {}))
        elif reach == "referrers":
            out |= set(refs.get(site, ()))
    return out


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


# ------------------------------------------------------------ raw lifecycle
#
# A struct or union's memory is *unmanaged* after the units that apply a raw routine to
# it: allocate it with an allocator of untyped memory, or free or dispose of
# it with a releaser of untyped memory. Its own constructors and destructors
# are functions like any other, unreferenced after their callers; what keeps
# its storage in C's allocator is C handing it to the raw routines. The raw
# routines are the store's: a lifecycle role acting on a type-erased pointer,
# submitted while planning. A site is a conversion `t2/arg_casts.csv` records
# at the routine's parameter or return, and its type is what the other end of
# the conversion holds: the value's named type, the type a slot is declared
# to hold, or what the dependency graph says an erased slot holds. Nothing is
# followed beyond the one conversion.

#: A raw site's ways of naming its type.
RAW_HOW = ("value", "typed slot", "erased param", "erased field")


class RawRoutines(NamedTuple):
    #: ``{(routine, def_file, position)}``: the erased parameters a raw
    #: dropper, disposer or out-parameter allocator acts on.
    into: frozenset
    #: ``{(routine, def_file)}``: the raw allocators and cloners whose return
    #: is a new allocation.
    out: frozenset


class RawSite(NamedTuple):
    user: tuple[str, str]           # (function, def_file)
    routine: str
    op: str                         # "alloc" | "release"
    how: str                        # one of RAW_HOW, or "" when unresolved
    types: frozenset                # {("exact", name, file)} | {("tag", name)}
    slot: str                       # the slot end, `slot_casts.slot_id` form, or ""
    line: int


def raw_routines(symbols, params_rows) -> RawRoutines:
    """The raw routines among the store's ``symbols``: a role whose subject
    is a type-erased parameter (``params.csv``'s ``is_erased``), or an
    ``alloc`` constructor or deep cloner, whose return is new storage. A
    routine of a typed subject is no raw routine, whatever it calls."""
    erased = {(r["function_name"], r.get("function_def_file") or "", r["param_name"]):
              str(r["position"]) for r in params_rows if r.get("is_erased") == "true"}
    erased_fns = {(n, f) for n, f, _ in erased}
    into, out = set(), set()
    for sym in symbols:
        roles = sym.get("lifetime")
        name, file = sym.get("name"), sym.get("defined_in") or ""
        for lt in (roles if isinstance(roles, list) else [roles]):
            if not lt:
                continue
            ctor = lt.get("is_constructor") or {}
            clone = lt.get("is_cloner") or {}
            subject = lt.get("for")
            if subject == "return":
                if ctor.get("alloc"):
                    out.add((name, file))
                continue
            pos = erased.get((name, file, subject))
            if pos is None:
                continue
            if lt.get("is_dropper") or lt.get("is_disposer") or ctor.get("alloc"):
                into.add((name, file, pos))
            if clone.get("deep") and (name, file) in erased_fns:
                out.add((name, file))
    return RawRoutines(frozenset(into), frozenset(out))


def raw_sites(rows, raw: RawRoutines, param_types: dict, fn_types: dict,
              field_types: dict) -> list[RawSite]:
    """Every conversion at a raw routine's parameter or return in
    ``arg_casts`` rows, with the types its other end holds. ``param_types``
    and ``field_types`` are what the dependency graph says an erased
    parameter ``(fn, file, position)`` or field ``(owner, file, member)``
    holds, and ``fn_types`` what T3 says a function's erased parameters hold.
    An erased parameter names a type when its body reads it as exactly one,
    or T3 names what it holds; an erased field every type it holds, since
    freeing the field frees whatever any instance stored. A site whose erased
    end names no type has none: unresolved. A held type is ``(tag,
    def_file)``: exact when the file is known, by tag when it is not."""
    from compose.slot_casts import _VOID_PTR

    out = []

    def end(r: dict, side: str) -> tuple[str, frozenset, str]:
        kind, name, file = r[f"{side}_kind"], r[f"{side}_name"], r[f"{side}_def_file"]
        member, decl = r[f"{side}_member"], r[f"{side}_decl"]
        if kind == "type":
            return "value", frozenset({("exact", name, file)}), ""
        slot = f"{kind}:{name}.{member}@{file}"
        if decl:
            return "typed slot", frozenset({("tag", decl)}), slot
        if not _VOID_PTR.match(r[f"{side}_ctype"] or ""):
            return "typed slot", frozenset(), slot     # a scalar buffer: no struct
        if kind == "param":
            # A parameter its body reads as several types is dispatched on
            # (`opt_free_elem(type, void *ptr)`): which one a raw routine
            # gets is the branch's, and no table says. T3 does.
            refs = fn_types.get((name, file)) or param_types.get((name, file, member), set())
            if len(refs) != 1 and (name, file) not in fn_types:
                refs = set()
            return ("erased param" if refs else ""), _held(refs), slot
        if kind == "field":
            refs = field_types.get((name, file, member), set())
            return ("erased field" if refs else ""), _held(refs), slot
        return "", frozenset(), slot                   # an erased return

    for r in rows:
        if not r.get("site_fn"):
            continue
        user = (r["site_fn"], r["site_file"])
        if (r["dst_kind"] == "param"
                and (r["dst_name"], r["dst_def_file"], r["dst_member"]) in raw.into):
            how, types, slot = end(r, "src")
            out.append(RawSite(user, r["dst_name"], "release", how, types, slot,
                               int(r["line"])))
        elif (r["src_kind"] == "ret" and (r["src_name"], r["src_def_file"]) in raw.out
              and _VOID_PTR.match(r["src_ctype"] or "")):
            how, types, slot = end(r, "dst")
            out.append(RawSite(user, r["src_name"], "alloc", how, types, slot,
                               int(r["line"])))
    return out


def _held(refs) -> frozenset:
    """A raw site's types from the ``(tag, def_file)`` refs a slot holds."""
    return frozenset(("exact", t, f) if f else ("tag", t) for t, f in refs)


def erased_slot_types(layout) -> tuple[dict, dict, dict]:
    """What the dependency graph says each type-erased slot holds:
    ``(param_types, fn_types, field_types)``, as :func:`raw_sites` takes them.
    A parameter holds what its own body reads it as, less T3 ``drop`` rows,
    and its function's T3 ``erased_arg`` rows; a field what is stored into
    it or read out of it, less T3 ``drop`` rows, and its T3 ``erased_field``
    rows (``compose.deps_dag``)."""
    from compose import slot_casts, t3

    sc = slot_casts.load(layout.t2)
    tables = t3.load(layout.t1)
    params: dict = {}
    for (_k, n, f, p), ts in sc.param_reads.items():
        drops = tables.drop_args.get((n, f), ())
        params[(n, f, p)] = {t for t in ts if not slot_casts.dropped(t, p, drops)}
    fns = {k: {(tag, df or "") for tag, df in v} for k, v in tables.erased_args.items()}
    fields: dict = {}
    for (_k, o, f, m), (stored, read_as) in sc.variants.items():
        drops = tables.drop_fields.get((o, f), ())
        fields[(o, f, m)] = {t for t in stored | read_as
                             if not slot_casts.dropped(t, m, drops)}
    for (o, f), refs in tables.erased_fields.items():
        for m, t, df in refs:
            fields.setdefault((o, f, m), set()).add((t, df or ""))
    return params, fns, fields


def load_raw_sites(layout) -> list[RawSite] | None:
    """The raw sites of ``layout``'s tables, or ``None`` when the store holds
    no raw routine: without them nothing is known, and nothing is guessed."""
    from compose import slot_casts
    from compose.scope import load_csv
    from wavefront import store

    symbols = [s for s in store.load(layout).get("symbols") or [] if s.get("lifetime")]
    params = layout.t1 / "params.csv"
    raw = raw_routines(symbols, load_csv(params) if symbols and params.is_file() else [])
    if not raw.into and not raw.out:
        return None
    path = layout.t2 / "arg_casts.csv"
    rows = slot_casts.narrow(load_csv(path)) if path.is_file() else []
    return raw_sites(rows, raw, *erased_slot_types(layout))
