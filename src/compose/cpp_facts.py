"""cpp_facts.py — what a C++ codebase's type system states, read from the
``cpp_*`` tables.

C states neither a type's lifecycle, nor which functions implement it, nor
its subtypes, nor who owns a pointer: wavefront orders a C codebase without
them, and takes them from users. C++ declares all four, and the extractor
records them (``entities/cpp_classes.ql``, ``entities/cpp_members.ql``,
``edges/cpp_bases.ql``, ``edges/cpp_overrides.ql``, ``edges/cpp_slots.ql``).
This module loads those tables and derives what the graph and the records
take from them:

- the **lifecycle** of a class, its special members and class-specific
  allocator, which the graph folds into the class's node;
- the **implementers** of a class, its other members, which depend on it as
  on a receiver and carry ``implements``;
- its **bases** and the primary template a specialization specializes, which
  it depends on as on a field's type;
- the functions an **override** implements;
- the **pointer properties** a slot's type states (:func:`slot_ptr`).

Every table is empty for a C codebase, so a C graph, record or schedule is
unchanged: :func:`load` returns facts that add nothing. Read-only, no CodeQL.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from pathlib import Path

try:
    from . import scope as _scope
except ImportError:                   # script execution
    import scope as _scope            # type: ignore


#: Member kinds that are the class's lifecycle: how its objects are made,
#: copied, moved and released. The graph folds them into the class's node.
LIFECYCLE_KINDS = frozenset({
    "constructor", "copy_constructor", "move_constructor", "destructor",
    "copy_assignment", "move_assignment", "allocator",
})

#: The lifecycle role each special member plays, in the vocabulary of
#: `docs/type-lifecycle.md`. A constructor initializes storage its caller
#: provides; a destructor releases what the object owns and leaves the
#: storage to whoever allocated it, as a disposer does; a copy is a deep
#: clone; a move transfers ownership, which Rust does by value.
LIFECYCLE_ROLES = {
    "constructor": "constructor_init",
    "copy_constructor": "cloner_deep",
    "move_constructor": "move",
    "destructor": "disposer",
    "copy_assignment": "cloner_deep_assign",
    "move_assignment": "move_assign",
    "allocator": "allocator",
}

Key = tuple[str, str]


def _b(v: str | None) -> bool:
    return (v or "") == "true"


@dataclass
class CppFacts:
    """The ``cpp_*`` tables, keyed by entity ``(name, def_file)``."""
    classes: dict[Key, dict] = field(default_factory=dict)
    members: dict[Key, dict] = field(default_factory=dict)
    bases: dict[Key, list[dict]] = field(default_factory=lambda: collections.defaultdict(list))
    overrides: dict[Key, list[Key]] = field(default_factory=lambda: collections.defaultdict(list))
    slots: dict[tuple[str, Key], dict[str, dict]] = field(
        default_factory=lambda: collections.defaultdict(dict))

    def __bool__(self) -> bool:
        return bool(self.classes or self.members)

    # ------------------------------------------------------------ classes

    def class_info(self, key: Key) -> dict | None:
        """What the record and the graph node say of a class: its keyword,
        template parameters, polymorphism, special members and value
        semantics, and its bases. None for a C type."""
        row = self.classes.get(key)
        if row is None:
            return None
        info = {
            "keyword": row.get("keyword") or "",
            "template_params": [p for p in (row.get("template_params") or "").split("|") if p],
            "abstract": _b(row.get("abstract")),
            "polymorphic": _b(row.get("polymorphic")),
            "final": _b(row.get("final")),
            "copyable": _b(row.get("copyable")),
            "movable": _b(row.get("movable")),
            "trivial": _b(row.get("trivial")),
            "special_members": {k: row.get(k) or "" for k in (
                "default_ctor", "copy_ctor", "move_ctor", "copy_assign",
                "move_assign", "dtor")},
            "bases": [{"name": b["base_name"], "defined_in": b["base_def_file"] or None,
                       "virtual": _b(b.get("virtual")), "access": b.get("access") or ""}
                      for b in self.bases.get(key, ())],
        }
        if row.get("specializes"):
            info["specializes"] = {"name": row["specializes"],
                                   "defined_in": row.get("specializes_def_file") or None}
        return info

    def specializes(self, key: Key) -> Key | None:
        row = self.classes.get(key)
        if row and row.get("specializes"):
            return (row["specializes"], row.get("specializes_def_file") or "")
        return None

    # ------------------------------------------------------------ members

    def member_info(self, key: Key) -> dict | None:
        """What a member is to its class, for the symbol's record and node:
        the class it implements, its kind, and its declared qualities. None
        for a free function, which is a consumer of the types it takes."""
        row = self.members.get(key)
        if row is None:
            return None
        info = {
            "implements": {"name": row["class_name"],
                           "defined_in": row.get("class_def_file") or None},
            "member_kind": row.get("member_kind") or "method",
            "static": _b(row.get("static")),
            "const": _b(row.get("const")),
            "virtual": _b(row.get("virtual")),
            "pure": _b(row.get("pure")),
            "access": row.get("access") or "",
        }
        for flag in ("defaulted", "deleted"):
            if _b(row.get(flag)):
                info[flag] = True
        if row.get("accessor"):
            info["accessor"] = {"kind": row["accessor"], "field": row.get("accessor_field") or ""}
        ovr = self.overrides.get(key)
        if ovr:
            info["overrides"] = [{"name": n, "defined_in": f or None} for n, f in sorted(ovr)]
        if info["member_kind"] in LIFECYCLE_KINDS:
            # Still the class's lifecycle, folded with it, but a deleted
            # member plays no role: it states that the class has none.
            info["lifecycle_role"] = (None if info.get("deleted")
                                      else LIFECYCLE_ROLES[info["member_kind"]])
        return info

    def lifecycle_of(self, key: Key) -> bool:
        row = self.members.get(key)
        return bool(row) and (row.get("member_kind") in LIFECYCLE_KINDS)

    def class_of(self, key: Key) -> Key | None:
        row = self.members.get(key)
        return (row["class_name"], row.get("class_def_file") or "") if row else None


def load(codeql_dir: Path | None) -> CppFacts:
    """Load the ``cpp_*`` tables below ``codeql_dir``. Missing tables (an
    extraction that predates them) read as empty, as for a C codebase."""
    facts = CppFacts()
    if codeql_dir is None:
        return facts
    t1, t2 = Path(codeql_dir) / "t1", Path(codeql_dir) / "t2"

    def rows(path: Path):
        return _scope.load_csv(path) if path.is_file() else []

    for r in rows(t1 / "cpp_classes.csv"):
        facts.classes[(r["name"], r.get("def_file") or "")] = r
    for r in rows(t1 / "cpp_members.csv"):
        facts.members[(r["function_name"], r.get("function_def_file") or "")] = r
    for r in rows(t2 / "cpp_bases.csv"):
        facts.bases[(r["derived_name"], r.get("derived_def_file") or "")].append(r)
    for k in facts.bases:
        facts.bases[k].sort(key=lambda r: int(r.get("position") or 0))
    for r in rows(t2 / "cpp_overrides.csv"):
        facts.overrides[(r["function_name"], r.get("function_def_file") or "")].append(
            (r["overridden_name"], r.get("overridden_def_file") or ""))
    for r in rows(t2 / "cpp_slots.csv"):
        owner = (r["owner_name"], r.get("owner_def_file") or "")
        facts.slots[(r["owner_kind"], owner)][r.get("member") or ""] = r
    return facts


# ---------------------------------------------------------------- slots

#: Standard layers that hold many elements, and those that are text.
_ARRAY_LAYERS = frozenset({"vector", "deque", "list", "forward_list", "array",
                           "span", "initializer_list", "valarray", "set",
                           "multiset", "unordered_set", "unordered_multiset"})
_MAP_LAYERS = frozenset({"map", "multimap", "unordered_map", "unordered_multimap"})
_TEXT_LAYERS = frozenset({"string", "string_view", "cstr", "char_ptr"})


def slot_ptr(chain: str, element: str = "") -> dict:
    """The pointer properties (`docs/pointer-properties.md`) a slot's type
    states, read off its chain of layers (`cppfacts.qll`). Only what the
    type states is set; a property it leaves open is absent, so a consumer
    knows what still needs judgement. A raw pointer states its shape and
    mutability but neither ownership nor nullability.

    ``owned``      the slot's holder releases the value: a value, a
                   `unique_ptr`, a `shared_ptr` (``shared``: by reference
                   count), an rvalue reference (moved in);
    ``borrowed``   the value lives elsewhere: an lvalue reference, a
                   `weak_ptr`, a view (`string_view`, `span`);
    ``nullable``   it may hold nothing: a smart pointer, an `optional`;
                   a reference or a value may not;
    ``mutable``    the holder may write through it;
    ``scalar`` / ``array`` / ``string`` / ``map``: what it holds.
    """
    layers = [x for x in chain.split(";") if x]
    out: dict = {"chain": chain}
    if element:
        out["element"] = element
    if not layers:
        return out
    top = layers[0]
    if top in ("ref", "cref"):
        out.update(owned=False, borrowed=True, nullable=False, mutable=top == "ref")
    elif top == "rref":
        out.update(owned=True, borrowed=False, nullable=False, mutable=True)
    elif top in ("ptr", "cptr", "void_ptr", "cvoid_ptr", "char_ptr", "cstr", "fnptr"):
        out.update(mutable=top in ("ptr", "void_ptr", "char_ptr"))
    elif top == "unique_ptr":
        out.update(owned=True, borrowed=False, nullable=True, mutable=True)
    elif top == "shared_ptr":
        out.update(owned=True, shared=True, borrowed=False, nullable=True, mutable=True)
    elif top == "weak_ptr":
        out.update(owned=False, borrowed=True, nullable=True)
    elif top == "optional":
        out.update(owned=True, borrowed=False, nullable=True)
    elif top in ("string_view", "span"):
        out.update(owned=False, borrowed=True, nullable=False, mutable=False)
    else:
        # A value: a class, a container, a string held by value.
        out.update(owned=True, borrowed=False, nullable=False)
    # What it holds: the first layer below the indirection that says.
    held = [x for x in layers if x not in ("ref", "cref", "rref", "ptr", "cptr",
                                           "unique_ptr", "shared_ptr", "weak_ptr",
                                           "optional", "atomic", "reference_wrapper")]
    first = held[0] if held else ""
    if first in _TEXT_LAYERS:
        out["cardinality"] = "string"
    elif first in _ARRAY_LAYERS or first == "array":
        out["cardinality"] = "array"
    elif first in _MAP_LAYERS:
        out["cardinality"] = "map"
    elif first:
        out["cardinality"] = "scalar"
    if "unique_ptr" in layers and layers[layers.index("unique_ptr") + 1:][:1] == ["array"]:
        out["cardinality"] = "array"
    return out


def slots_of(facts: CppFacts, kind: str, key: Key) -> dict[str, dict]:
    """``{member: pointer properties}`` for a function's parameters
    (``param``) and return (``return``), a type's fields (``field``) or a
    global (``global``)."""
    out = {}
    for member, r in sorted(facts.slots.get((kind, key), {}).items()):
        d = slot_ptr(r.get("chain") or "", r.get("element_name") or "")
        if r.get("member_name"):
            d["name"] = r["member_name"]
        d["type"] = r.get("type") or ""
        out[member] = d
    return out
