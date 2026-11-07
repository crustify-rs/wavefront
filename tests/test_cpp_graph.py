"""The C++ layer of the graph: what the `cpp_*` tables state orders and
annotates the nodes, without any data-flow, and a C graph is unchanged.

Synthetic tables: `shape.h` defines `geo::Shape`, an abstract class with a
pure virtual `area`, and `geo::Circle`, derived from it, with a constructor,
destructor, an override of `area` and a getter; `scene.cc` defines a free
function `geo::make_circle` that calls the constructor, and downcasts a
`Shape` to a `Circle`.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from compose import cpp_facts, deps_dag
from test_t3 import FN_COLS, TYPE_COLS, _write

CLASS_COLS = ["name", "def_file", "keyword", "template_params", "specializes",
              "specializes_def_file", "abstract", "polymorphic", "final",
              "default_ctor", "copy_ctor", "move_ctor", "copy_assign", "move_assign",
              "dtor", "copyable", "movable", "trivial", "ctors"]
MEMBER_COLS = ["function_name", "function_def_file", "class_name", "class_def_file",
               "member_kind", "static", "const", "virtual", "pure", "override",
               "access", "defaulted", "deleted", "accessor", "accessor_field"]
BASE_COLS = ["derived_name", "derived_def_file", "base_name", "base_def_file",
             "position", "virtual", "access"]
OVERRIDE_COLS = ["function_name", "function_def_file", "overridden_name",
                 "overridden_def_file"]

SHAPE, CIRCLE = ("geo::Shape", "shape.h"), ("geo::Circle", "shape.h")


def _class(name, abstract="false", **kw):
    row = {c: "" for c in CLASS_COLS}
    row.update(name=name, def_file="shape.h", keyword="class", abstract=abstract,
               polymorphic="true", final="false", copyable="true", movable="true",
               trivial="false", ctors="0")
    row.update(kw)
    return row


def _member(fn, cls, kind, **kw):
    row = {c: "false" for c in MEMBER_COLS}
    row.update(function_name=fn, function_def_file="shape.h", class_name=cls,
               class_def_file="shape.h", member_kind=kind, access="public",
               accessor="", accessor_field="")
    row.update(kw)
    return row


def _sym(name, deps=(), types=(), defined_in="shape.h"):
    return {"name": name, "kind": "function_exported", "defined_in": defined_in,
            "declared_in": ["shape.h"], "loc": 3,
            "depends_on": {"types": [{"type": t, "fields": []} for t in types],
                           "syms": [{"name": d, "defined_in": "shape.h",
                                     "declared_in": ["shape.h"]} for d in deps]},
            "ptr_args": [], "ptr_ret": None}


def _tables(root: Path, cpp: bool = True) -> Path:
    codeql = root / "codeql"
    t1, t2 = codeql / "t1", codeql / "t2"
    _write(t1 / "types.csv", TYPE_COLS, [
        {"name": n, "kind": "struct", "def_file": "shape.h", "decl_files": "shape.h",
         "aliases": "", "unaliased_kind": ""} for n in ("geo::Shape", "geo::Circle")])
    _write(t1 / "functions.csv", FN_COLS, [])
    _write(t1 / "fields.csv", ["struct_name", "struct_def_file", "field_name",
                               "field_type", "is_scalar", "ptr_depth", "is_erased"], [])
    # A downcast, `Shape` to `Circle`: alone, it would order the base after
    # its derived class.
    _write(t2 / "casts.csv", ["from_tag", "to_tag"],
           [{"from_tag": "geo::Shape", "to_tag": "geo::Circle"}])
    _write(t2 / "field_type_uses.csv", ["struct_name", "struct_def_file", "field_name",
                                        "type_name", "type_kind", "type_def_file"], [])
    _write(t2 / "signature_type_uses.csv", ["function_name", "function_def_file",
                                            "type_name", "type_kind", "type_def_file",
                                            "position"], [])
    if cpp:
        _write(t1 / "cpp_classes.csv", CLASS_COLS, [
            _class("geo::Shape", abstract="true", dtor="user"),
            _class("geo::Circle", dtor="user", copy_ctor="deleted")])
        _write(t1 / "cpp_members.csv", MEMBER_COLS, [
            _member("geo::Shape::area", "geo::Shape", "method", virtual="true", pure="true"),
            _member("geo::Circle::Circle", "geo::Circle", "constructor"),
            _member("geo::Circle::Circle(const Circle &)", "geo::Circle",
                    "copy_constructor", deleted="true"),
            _member("geo::Circle::~Circle", "geo::Circle", "destructor"),
            _member("geo::Circle::area", "geo::Circle", "method", virtual="true",
                    override="true"),
            _member("geo::Circle::radius", "geo::Circle", "method", const="true",
                    accessor="getter", accessor_field="r_"),
        ])
        _write(t2 / "cpp_bases.csv", BASE_COLS, [
            {"derived_name": "geo::Circle", "derived_def_file": "shape.h",
             "base_name": "geo::Shape", "base_def_file": "shape.h", "position": "0",
             "virtual": "false", "access": "public"}])
        _write(t2 / "cpp_overrides.csv", OVERRIDE_COLS, [
            {"function_name": "geo::Circle::area", "function_def_file": "shape.h",
             "overridden_name": "geo::Shape::area", "overridden_def_file": "shape.h"}])
    return codeql


SYMS = [
    _sym("geo::Shape::area"),
    _sym("geo::Circle::Circle"),
    _sym("geo::Circle::Circle(const Circle &)"),
    _sym("geo::Circle::~Circle"),
    _sym("geo::Circle::area"),
    _sym("geo::Circle::radius"),
    _sym("geo::make_circle", deps=("geo::Circle::Circle",), types=("geo::Circle",),
         defined_in="scene.cc"),
]


def _dag(cpp: bool = True) -> dict:
    with tempfile.TemporaryDirectory() as td:
        codeql = _tables(Path(td), cpp)
        return deps_dag.compose(([], SYMS), None, codeql_dir=codeql)


def _nodes(dag: dict) -> dict:
    out = {}
    for layer, recs in enumerate(dag["layers"]):
        for r in recs:
            out[(r["id"], r["node_kind"])] = (layer, r)
    return out


def _deps(rec: dict, side: str) -> set:
    return {d["name"] for d in rec["deps"][side]}


class CppGraphTests(unittest.TestCase):

    def test_base_before_derived_despite_a_downcast(self) -> None:
        nodes = _nodes(_dag())
        (ls, shape), (lc, circle) = nodes[("geo::Shape", "type")], nodes[("geo::Circle", "type")]
        self.assertIn("geo::Shape", _deps(circle, "types"))
        self.assertNotIn("geo::Circle", _deps(shape, "types"))
        self.assertLess(ls, lc)

    def test_lifecycle_folds_into_its_class(self) -> None:
        dag = _dag()
        nodes = _nodes(dag)
        _, circle = nodes[("geo::Circle", "type")]
        roles = {m["name"]: m.get("role") for m in circle["cpp"]["lifecycle"]}
        self.assertEqual(roles, {"geo::Circle::Circle": "constructor_init",
                                 "geo::Circle::Circle(const Circle &)": None,
                                 "geo::Circle::~Circle": "disposer"})
        for name in roles:
            self.assertNotIn((name, "symbol"), nodes)
        self.assertEqual(dag["stats"]["lifecycle_folded"], 3)
        # An edge to a folded member is an edge to its class.
        _, maker = nodes[("geo::make_circle", "symbol")]
        self.assertIn("geo::Circle", _deps(maker, "types"))
        self.assertNotIn("geo::Circle::Circle", _deps(maker, "syms"))

    def test_members_implement_their_class(self) -> None:
        nodes = _nodes(_dag())
        lt, _ = nodes[("geo::Circle", "type")]
        lr, radius = nodes[("geo::Circle::radius", "symbol")]
        self.assertEqual(radius["member"]["implements"]["name"], "geo::Circle")
        self.assertEqual(radius["member"]["accessor"], {"kind": "getter", "field": "r_"})
        self.assertIn("geo::Circle", _deps(radius, "types"))
        self.assertLess(lt, lr)
        _, maker = nodes[("geo::make_circle", "symbol")]
        self.assertNotIn("member", maker)           # a consumer, not an implementer

    def test_override_follows_the_function_it_overrides(self) -> None:
        nodes = _nodes(_dag())
        lb, _ = nodes[("geo::Shape::area", "symbol")]
        lo, ovr = nodes[("geo::Circle::area", "symbol")]
        self.assertIn("geo::Shape::area", _deps(ovr, "syms"))
        self.assertEqual(ovr["member"]["overrides"],
                         [{"name": "geo::Shape::area", "defined_in": "shape.h"}])
        self.assertLess(lb, lo)

    def test_no_cpp_tables_no_change(self) -> None:
        dag = _dag(cpp=False)
        self.assertNotIn("lifecycle_folded", dag["stats"])
        for _, rec in _nodes(dag).values():
            self.assertNotIn("cpp", rec)
            self.assertNotIn("member", rec)


class SlotPointerTests(unittest.TestCase):
    """What a slot's type states of its pointer properties, and no more."""

    def test_borrowed_reference(self) -> None:
        p = cpp_facts.slot_ptr("cref;class", "geo::Shape")
        self.assertEqual((p["owned"], p["borrowed"], p["nullable"], p["mutable"]),
                         (False, True, False, False))
        self.assertEqual(p["cardinality"], "scalar")

    def test_owning_and_shared_pointers(self) -> None:
        u = cpp_facts.slot_ptr("unique_ptr;class")
        self.assertEqual((u["owned"], u["nullable"]), (True, True))
        s = cpp_facts.slot_ptr("shared_ptr;class")
        self.assertTrue(s["shared"])
        w = cpp_facts.slot_ptr("weak_ptr;class")
        self.assertEqual((w["owned"], w["borrowed"], w["nullable"]), (False, True, True))
        self.assertEqual(cpp_facts.slot_ptr("unique_ptr;array;class")["cardinality"], "array")

    def test_containers_and_text(self) -> None:
        self.assertEqual(cpp_facts.slot_ptr("cref;vector;unique_ptr;class")["cardinality"],
                         "array")
        self.assertEqual(cpp_facts.slot_ptr("map;unique_ptr;class")["cardinality"], "map")
        self.assertEqual(cpp_facts.slot_ptr("string_view")["cardinality"], "string")
        self.assertEqual(cpp_facts.slot_ptr("cstr")["cardinality"], "string")

    def test_raw_pointer_leaves_ownership_open(self) -> None:
        p = cpp_facts.slot_ptr("ptr;class")
        self.assertNotIn("owned", p)
        self.assertNotIn("nullable", p)
        self.assertTrue(p["mutable"])


if __name__ == "__main__":
    unittest.main()
