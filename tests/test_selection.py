"""Scheduling: the order over every unit of the closure, and the selection a
config's `schedule` keeps of it."""
from __future__ import annotations

import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path

from test_schedule_parity import _schedule, _scheduled_items

from wavefront.order import _cut, _layers
from wavefront.stats import Stats


def _rec(name, home, *, kind="symbol", syms=(), types=(), fallback=()):
    rec = {"id": name, "node_kind": kind,
           "subkind": "struct" if kind == "type" else "function_def",
           "defined_in": home, "loc": 1,
           "deps": {"types": [{"name": n, "defined_in": h} for n, h in types],
                    "syms": [{"name": n, "defined_in": h} for n, h in syms]}}
    if fallback:
        rec["fallback"] = {"types": [],
                           "syms": [{"name": n, "defined_in": h}
                                    for n, h in fallback]}
    return rec


def _inventory(functions=(), types=()):
    none = {"files": [], "functions": [], "globals": [], "macros": [],
            "types": []}
    return {
        "closure": {**none,
                     "functions": [{"name": n, "defined_in": h,
                                    "declared_in": list(d)}
                                   for n, h, *d in functions],
                     "types": [{"name": n, "defined_in": h,
                                "declared_in": list(d)}
                               for n, h, *d in types]},
        "external": dict(none), "api": dict(none),
    }


def _config(*entries, files=("a.c", "b.c", "h.h")):
    config = {"closure": {"impl_files": {"included": list(files)}}}
    if entries:
        config["schedule_seeds"] = list(entries)
    return config


def _names(schedule):
    return [[i["name"] for b in w["batches"] for i in b["items"]]
            for w in schedule["waves"]]


# a1 -> b1 and a2 -> a1 within the closure; b2 -> a1 closes a cycle that the
# composer has already cut, as `fallback`. h.h declares b1, which b.c defines.
GRAPH = {"layers": [
    [_rec("b1", "b.c"), _rec("b2", "b.c", fallback=[("a1", "a.c")]),
     _rec("T", "h.h", kind="type")],
    [_rec("a1", "a.c", syms=[("b1", "b.c")])],
    [_rec("a2", "a.c", syms=[("a1", "a.c"), ("b1", "b.c")])],
]}
INVENTORY = _inventory(
    functions=[("a1", "a.c", "a.c"), ("a2", "a.c", "a.c"),
               ("b1", "b.c", "b.c", "h.h"), ("b2", "b.c", "b.c")],
    types=[("T", "h.h", "h.h")])


class OrderTests(unittest.TestCase):
    def test_every_unit_is_layered_and_one_wave_per_layer(self) -> None:
        schedule = _schedule(GRAPH, INVENTORY, config=_config())
        self.assertEqual(_names(schedule), [["T", "b1"], ["a1"], ["a2", "b2"]])
        self.assertEqual([w["layer"] for w in schedule["waves"]], [0, 1, 2])
        self.assertEqual({w["module"] for w in schedule["waves"]}, {None})

    def test_the_cut_is_recorded_on_both_ends(self) -> None:
        # a1 and b2 depend on each other: equal weights, so the tie goes to
        # the first by name, a1, and its edge to b2 is cut.
        graph = {"layers": [[_rec("b1", "b.c")],
                            [_rec("a1", "a.c", syms=[("b1", "b.c")],
                                  fallback=[("b2", "b.c")])],
                            [_rec("b2", "b.c", syms=[("a1", "a.c")])]]}
        inventory = _inventory(functions=[("a1", "a.c"), ("b1", "b.c"),
                                          ("b2", "b.c")])
        items = {i["name"]: i for i in _scheduled_items(
            _schedule(graph, inventory, config=_config()))}
        self.assertEqual([r["name"] for r in items["a1"]["depends_on"]["cut"]["symbols"]], ["b2"])
        self.assertEqual([r["name"] for r in items["b2"]["depended_on_by"]["cut"]["symbols"]], ["a1"])
        self.assertEqual(items["a1"]["depends_on"]["scheduled"]["symbols"],
                         [{"name": "b1", "defined_in": "b.c", "scope": "scheduled"}])
        self.assertEqual(_names(_schedule(graph, inventory, config=_config())),
                         [["b1"], ["a1"], ["b2"]])

    def test_an_item_carries_its_declarations(self) -> None:
        items = {i["name"]: i for i in _scheduled_items(
            _schedule(GRAPH, INVENTORY, config=_config()))}
        self.assertEqual(items["b1"]["declared_in"], ["b.c", "h.h"])


class SelectionTests(unittest.TestCase):
    def test_a_selection_keeps_the_order_of_the_whole_closure(self) -> None:
        def stages(schedule):
            return {i["name"]: w["layer"] for w in schedule["waves"]
                    for b in w["batches"] for i in b["items"]}
        whole = stages(_schedule(GRAPH, INVENTORY, config=_config()))
        narrow = _schedule(GRAPH, INVENTORY, config=_config("a.c"))
        self.assertEqual(_names(narrow), [["b1"], ["a1"], ["a2"]])
        for name, stage in stages(narrow).items():
            self.assertEqual(stage, whole[name])

    def test_a_file_selects_what_it_defines_or_declares(self) -> None:
        schedule = _schedule(GRAPH, INVENTORY, config=_config("h.h"))
        self.assertEqual(_names(schedule), [["T", "b1"]])

    def test_items_narrow_a_file(self) -> None:
        only = {"path": "h.h", "items": {"included": [{"name": "b1", "kind": "symbol"}]}}
        self.assertEqual(_names(_schedule(GRAPH, INVENTORY, config=_config(only))),
                         [["b1"]])
        less = {"path": "h.h", "items": {"excluded": [{"name": "b1", "kind": "symbol"}]}}
        self.assertEqual(_names(_schedule(GRAPH, INVENTORY, config=_config(less))),
                         [["T"]])

    def test_a_directory_selects_the_closure_files_under_it(self) -> None:
        # The closure decides what src/ holds, not the disk, where it is empty.
        graph = {"layers": [[_rec("f", "src/a.c"), _rec("g", "src/sub/b.c"),
                             _rec("h", "lib/c.c")]]}
        inventory = _inventory(functions=[("f", "src/a.c"), ("g", "src/sub/b.c"),
                                          ("h", "lib/c.c")])
        files = ("src/a.c", "src/sub/b.c", "lib/c.c")
        schedule = _schedule(graph, inventory, config=_config("src/", files=files))
        self.assertEqual(_names(schedule), [["f", "g"]])

    def test_a_selection_brings_what_it_depends_on(self) -> None:
        schedule = _schedule(GRAPH, INVENTORY, config=_config("a.c"))
        items = {i["name"]: i for i in _scheduled_items(schedule)}
        self.assertEqual({n: i["seeded"] for n, i in items.items()},
                         {"a1": True, "a2": True, "b1": False})
        self.assertEqual(items["a1"]["depends_on"]["scheduled"]["symbols"],
                         [{"name": "b1", "defined_in": "b.c", "scope": "scheduled"}])
        self.assertEqual((schedule["summary"]["unit_count"],
                          schedule["summary"]["seeded_count"]), (3, 2))

    def test_a_cycle_partner_comes_along(self) -> None:
        graph = {"layers": [[_rec("b1", "b.c")],
                            [_rec("a1", "a.c", syms=[("b1", "b.c")],
                                  fallback=[("b2", "b.c")])],
                            [_rec("b2", "b.c", syms=[("a1", "a.c")])]]}
        inventory = _inventory(functions=[("a1", "a.c"), ("b1", "b.c"),
                                          ("b2", "b.c")])
        schedule = _schedule(graph, inventory, config=_config("a.c"))
        self.assertEqual(_names(schedule), [["b1"], ["a1"], ["b2"]])

    def test_errors(self) -> None:
        cases = {
            "no owned entity": _config(
                {"path": "h.h", "items": {"included": [{"name": "V", "kind": "type"}]}}),
            "no owned entity ": _config(
                {"path": "h.h", "items": {"included": [{"name": "T", "kind": "symbol"}]}}),
            "both lists name": _config({"path": "h.h", "items": {
                "included": [{"name": "T", "kind": "type"}],
                "excluded": [{"name": "T", "kind": "type"}]}}),
            "c.c is no file of the closure": _config("c.c"),
            "src/ holds no file of the closure": _config("src/"),
            "a directory": _config({"path": "src/", "items": {}}),
            "non-empty list": {"closure": {"impl_files": {"included": ["a.c"]}},
                               "schedule_seeds": []},
        }
        for message, config in cases.items():
            with self.subTest(message), \
                    self.assertRaisesRegex(SystemExit, message.strip()):
                _schedule(GRAPH, INVENTORY, config=config)


def _modules(config, *modules):
    return {**config, "modules": [{"name": n, "files": list(fs)} for n, *fs in modules]}


def _waves(schedule):
    return [(w["module"], [i["name"] for b in w["batches"] for i in b["items"]],
             w["depends_on"]["scheduled"], w["sublayer"] if w["module"] else w["layer"])
            for w in schedule["waves"]]


class ModuleTests(unittest.TestCase):
    def test_modules_are_ordered_and_their_cycle_cut(self) -> None:
        # A uses two units of B (a1 -> b1, a2 -> b3), B one of A (b2 -> a1):
        # the cycle is cut on B's side, and B, the producer, comes first.
        graph = {"layers": [
            [_rec("b1", "b.c"), _rec("b2", "b.c", fallback=[("a1", "a.c")]),
             _rec("b3", "b.c"), _rec("T", "h.h", kind="type")],
            [_rec("a1", "a.c", syms=[("b1", "b.c")])],
            [_rec("a2", "a.c", syms=[("a1", "a.c"), ("b3", "b.c")])]]}
        inventory = _inventory(
            functions=[("a1", "a.c"), ("a2", "a.c"), ("b1", "b.c"),
                       ("b2", "b.c"), ("b3", "b.c")],
            types=[("T", "h.h")])
        config = _modules(_config(), ("A", "a.c"), ("B", "b.c"), ("H", "h.h"))
        schedule = _schedule(graph, inventory, config=config)
        self.assertEqual(_waves(schedule), [
            ("B", ["b1", "b2", "b3"], [], 0),
            ("H", ["T"], [], 0),
            ("A", ["a1"], [0], 0),
            ("A", ["a2"], [0, 2], 1),
        ])
        modules = {m["name"]: m for m in schedule["modules"]}
        self.assertEqual(modules["A"]["depends_on"]["scheduled"],
                         [{"module": "B", "unique_edges": 2, "total_edges": 2,
                           "via_dependency": []}])
        self.assertEqual(modules["B"]["depends_on"]["cut"][0]["items"], [
            {"from": {"name": "b2", "defined_in": "b.c"},
             "to": {"name": "a1", "defined_in": "a.c"}, "kind": "symbol"}])
        items = {i["name"]: i for i in _scheduled_items(schedule)}
        self.assertEqual(items["a2"]["module"], "A")
        self.assertEqual({m: modules[m]["layer"] for m in modules},
                         {"B": 0, "H": 0, "A": 1})
        self.assertEqual([r["name"] for r in items["b2"]["depends_on"]["cut"]["symbols"]], ["a1"])

    def test_units_no_module_claims_are_ordered_alone(self) -> None:
        config = _modules(_config("a.c", "h.h"), ("A", "a.c"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            schedule = _schedule(GRAPH, INVENTORY, config=config)
        # T and b1 are seeds no module claims: they keep their place, layer 0.
        self.assertEqual(_waves(schedule), [
            (None, ["T", "b1"], [], 0),
            ("A", ["a1"], [0], 0),
            ("A", ["a2"], [0, 1], 1),
        ])
        self.assertIsNone(_scheduled_items(schedule)[0]["module"])
        # h.h defines T and declares b1: both are seeds no module claims.
        self.assertIn("2 scheduled unit(s) belong to no module (2 seed(s), "
                      "0 dependenc(ies))", err.getvalue())
        self.assertIn("type T (h.h), symbol b1 (b.c)", err.getvalue())
        # b1 is only a dependency here, and still needs a module.
        config = _modules(_config("a.c"), ("A", "a.c"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _schedule(GRAPH, INVENTORY, config=config)
        self.assertIn("1 scheduled unit(s) belong to no module (0 seed(s), "
                      "1 dependenc(ies)), and are ordered alone: symbol b1 (b.c)",
                      err.getvalue())
        # Once B claims it, nothing is warned of: b2, which no seed reaches,
        # needs no module.
        config = _modules(_config("a.c"), ("A", "a.c"), ("B", {"path": "b.c", "items": {
            "included": [{"name": "b1", "kind": "symbol"}]}}))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _schedule(GRAPH, INVENTORY, config=config)
        self.assertEqual(err.getvalue(), "")

    def test_a_dependency_no_module_claims_joins_the_wave_before_its_user(self) -> None:
        # x.c is in no module; only a3, A's third layer, uses x.
        graph = {"layers": [
            [_rec("a1", "a.c"), _rec("x", "x.c")],
            [_rec("a2", "a.c", syms=[("a1", "a.c")])],
            [_rec("a3", "a.c", syms=[("a2", "a.c"), ("x", "x.c")])]]}
        inventory = _inventory(functions=[("a1", "a.c"), ("a2", "a.c"),
                                          ("a3", "a.c"), ("x", "x.c")])
        config = _modules(_config("a.c", files=("a.c", "x.c")), ("A", "a.c"))
        # x joins the wave right before a3's: A's second.
        self.assertEqual(_waves(_schedule(graph, inventory, config=config)), [
            ("A", ["a1"], [], 0),
            ("A", ["a2", "x"], [0], 1),
            ("A", ["a3"], [1], 2),
        ])
        flat = _schedule(graph, inventory, config=_config(files=("a.c", "x.c")))
        self.assertEqual(_names(flat), [["a1", "x"], ["a2"], ["a3"]])
        # Seeded by a.c, x is a dependency: it runs just before a3 there too.
        seeded = _schedule(graph, inventory,
                           config=_config("a.c", files=("a.c", "x.c")))
        self.assertEqual(_names(seeded), [["a1"], ["a2", "x"], ["a3"]])

    def test_a_dependency_through_an_unclaimed_unit_names_its_module(self) -> None:
        # a1 uses x, which no module claims, and x uses b1.
        graph = {"layers": [[_rec("b1", "b.c")],
                            [_rec("x", "x.c", syms=[("b1", "b.c")])],
                            [_rec("a1", "a.c", syms=[("x", "x.c")])]]}
        inventory = _inventory(functions=[("a1", "a.c"), ("b1", "b.c"),
                                          ("x", "x.c")])
        config = _modules(_config("a.c", "b.c", files=("a.c", "b.c", "x.c")),
                          ("A", "a.c"), ("B", "b.c"))
        modules = {m["name"]: m for m in
                   _schedule(graph, inventory, config=config)["modules"]}
        self.assertEqual(modules["A"]["depends_on"]["scheduled"],
                         [{"module": "B", "unique_edges": 1, "total_edges": 1,
                           "via_dependency": [{"name": "x", "defined_in": "x.c"}]}])
        self.assertLess(modules["B"]["layer"], modules["A"]["layer"])

    def test_a_narrow_schedule_names_only_the_modules_it_holds(self) -> None:
        # a1 is the seed; a9, which A also holds, is the only user of B.
        graph = {"layers": [[_rec("b1", "b.c"), _rec("a1", "a.c")],
                            [_rec("a9", "a.c", syms=[("b1", "b.c")])]]}
        inventory = _inventory(functions=[("a1", "a.c"), ("a9", "a.c"),
                                          ("b1", "b.c")])
        config = _modules(_config(files=("a.c", "b.c")), ("A", "a.c"), ("B", "b.c"))
        whole = {m["name"]: m for m in _schedule(graph, inventory, config=config)
                 ["modules"]}
        self.assertEqual(whole["A"]["depends_on"]["scheduled"],
                         [{"module": "B", "unique_edges": 1, "total_edges": 1,
                           "via_dependency": []}])
        config["schedule_seeds"] = [
            {"path": "a.c", "items": {"included": [{"name": "a1", "kind": "symbol"}]}}]
        narrow = _schedule(graph, inventory, config=config)
        self.assertEqual([m["name"] for m in narrow["modules"]], ["A"])
        self.assertEqual(narrow["modules"][0]["depends_on"],
                         {"scheduled": [], "cut": []})
        # Its layer is still the whole closure's.
        self.assertEqual(narrow["modules"][0]["layer"], whole["A"]["layer"])

    def test_a_shared_header_is_split_item_by_item(self) -> None:
        # h.h defines S and U; a.c implements S, b.c U.
        graph = {"layers": [[_rec("S", "h.h", kind="type"), _rec("U", "h.h", kind="type")],
                            [_rec("a1", "a.c", types=[("S", "h.h")]),
                             _rec("b1", "b.c", types=[("U", "h.h")])]]}
        inventory = _inventory(functions=[("a1", "a.c"), ("b1", "b.c")],
                               types=[("S", "h.h", "h.h"), ("U", "h.h", "h.h")])

        def only(name):
            return {"path": "h.h", "items": {"included": [{"name": name, "kind": "type"}]}}
        config = _modules(_config(), ("A", "a.c", only("S")), ("B", "b.c", only("U")))
        self.assertEqual(_waves(_schedule(graph, inventory, config=config)), [
            ("A", ["S"], [], 0), ("B", ["U"], [], 0),
            ("A", ["a1"], [0], 1), ("B", ["b1"], [1], 1)])

    def test_a_tu_is_split_between_two_modules(self) -> None:
        # a.c's allocator and releaser are foundational; f uses them.
        graph = {"layers": [[_rec("alloc", "a.c"), _rec("release", "a.c")],
                            [_rec("f", "a.c", syms=[("alloc", "a.c"),
                                                    ("release", "a.c")])]]}
        inventory = _inventory(functions=[("alloc", "a.c"), ("release", "a.c"),
                                          ("f", "a.c")])
        lifecycle = [{"name": "alloc", "kind": "symbol"},
                     {"name": "release", "kind": "symbol"}]
        config = _modules(_config(),
                          ("F", {"path": "a.c", "items": {"included": lifecycle}}),
                          ("A", {"path": "a.c", "items": {"excluded": lifecycle}}))
        schedule = _schedule(graph, inventory, config=config)
        self.assertEqual(_waves(schedule), [("F", ["alloc", "release"], [], 0),
                                            ("A", ["f"], [0], 0)])
        self.assertEqual([m["layer"] for m in schedule["modules"]], [0, 1])

    def test_an_item_its_file_only_declares_is_an_error(self) -> None:
        # h.h declares b1, which b.c defines: H would claim nothing.
        b1 = {"path": "h.h", "items": {"included": [{"name": "b1", "kind": "symbol"}]}}
        config = _modules(_config(), ("H", b1), ("A", "a.c"))
        with self.assertRaisesRegex(SystemExit, r"H: h\.h items\.included: "
                                                r"symbol b1 is homed in b\.c"):
            _schedule(GRAPH, INVENTORY, config=config)
        # As a seed it still selects b1 by its declaration.
        self.assertEqual(_names(_schedule(GRAPH, INVENTORY, config=_config(b1))),
                         [["b1"]])

    def test_a_module_that_claims_no_unit_is_warned_of(self) -> None:
        # e.h is a closure file that defines no unit.
        config = _modules(_config(files=("a.c", "b.c", "h.h", "e.h")),
                          ("A", "a.c"), ("E", "e.h"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _schedule(GRAPH, INVENTORY, config=config)
        self.assertIn("warning: 1 module(s) claim no unit: E", err.getvalue())

    def test_a_module_outside_the_api_graph_is_no_warning(self) -> None:
        # Only a2 is published: the API graph reaches a1 and b1, not T, which
        # H still claims in the closure.
        inventory = {**INVENTORY, "api": {**INVENTORY["api"], "functions": [
            {"name": "a2", "defined_in": "a.c", "declared_in": ["a.c"]}]}}
        config = _modules(_config(), ("A", "a.c"), ("B", "b.c"), ("H", "h.h"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            schedule = _schedule(GRAPH, inventory, config=config,
                                 api_headers_only=True)
        self.assertEqual(_names(schedule), [["b1"], ["a1"], ["a2"]])
        self.assertNotIn("claim no unit", err.getvalue())

    def test_a_module_cycle_is_cut_where_it_leaves_fewest_dependencies(self) -> None:
        # A's a1, a2 and a3 all use b1; B's b2 and b3 use a1 and a2. Cutting
        # A's edges leaves one unit behind, b1; cutting B's, two.
        graph = {"layers": [
            [_rec("a1", "a.c", fallback=[("b1", "b.c")]),
             _rec("a2", "a.c", fallback=[("b1", "b.c")]),
             _rec("a3", "a.c", fallback=[("b1", "b.c")])],
            [_rec("b1", "b.c"), _rec("b2", "b.c", syms=[("a1", "a.c")]),
             _rec("b3", "b.c", syms=[("a2", "a.c")])]]}
        inventory = _inventory(functions=[(n, f"{n[0]}.c") for n in
                                          ("a1", "a2", "a3", "b1", "b2", "b3")])
        config = _modules(_config(files=("a.c", "b.c")), ("A", "a.c"), ("B", "b.c"))
        schedule = _schedule(graph, inventory, config=config)
        modules = {m["name"]: m for m in schedule["modules"]}
        self.assertEqual((modules["A"]["layer"], modules["B"]["layer"]), (0, 1))
        cut = modules["A"]["depends_on"]["cut"][0]
        self.assertEqual((cut["module"], cut["unique_edges"], cut["total_edges"]),
                         ("B", 1, 3))
        self.assertEqual(modules["B"]["depends_on"]["scheduled"],
                         [{"module": "A", "unique_edges": 2, "total_edges": 2,
                           "via_dependency": []}])

    def test_dependencies_before_a_module_s_first_wave_lead_it(self) -> None:
        # x1 <- x2 <- x3, which no module claims, lead to a1, A's first wave;
        # a2 also uses x1.
        graph = {"layers": [
            [_rec("b1", "b.c"), _rec("x1", "x.c")],
            [_rec("x2", "x.c", syms=[("x1", "x.c")])],
            [_rec("x3", "x.c", syms=[("x2", "x.c")])],
            [_rec("a1", "a.c", syms=[("x3", "x.c"), ("b1", "b.c")])],
            [_rec("a2", "a.c", syms=[("a1", "a.c"), ("x1", "x.c")])]]}
        inventory = _inventory(functions=[(n, f"{n[0]}.c") for n in
                                          ("a1", "a2", "b1", "x1", "x2", "x3")])
        config = _modules(_config("a.c", files=("a.c", "b.c", "x.c")),
                          ("A", "a.c"), ("B", "b.c"))
        schedule = _schedule(graph, inventory, config=config)
        self.assertEqual(_waves(schedule), [
            ("B", ["b1"], [], 0),
            ("A", ["x1"], [], 0),
            ("A", ["x2"], [1], 1),
            ("A", ["x3"], [2], 2),
            ("A", ["a1"], [0, 3], 3),
            ("A", ["a2"], [1, 4], 4),
        ])
        items = {i["name"]: i for i in _scheduled_items(schedule)}
        self.assertIsNone(items["x1"]["module"])
        modules = {m["name"]: m for m in schedule["modules"]}
        self.assertEqual((modules["A"]["unit_count"], modules["A"]["waves"]),
                         (2, [1, 2, 3, 4, 5]))

    def test_a_unit_two_modules_claim_is_an_error(self) -> None:
        config = _modules(_config(), ("A", "a.c", "h.h"), ("H", "h.h"))
        with self.assertRaisesRegex(SystemExit, "belong to several modules"):
            _schedule(GRAPH, INVENTORY, config=config)


class KindTests(unittest.TestCase):
    """`f` uses the enum `E` and the macro `M`, both defined in a.c."""
    GRAPH = {"layers": [[
        {**_rec("E", "a.c", kind="type"), "subkind": "enum"},
        {**_rec("M", "a.c"), "subkind": "macro_object"},
    ], [_rec("f", "a.c", types=[("E", "a.c")], syms=[("M", "a.c")])]]}
    INVENTORY = _inventory(functions=[("f", "a.c")], types=[("E", "a.c")])

    def test_enums_and_macros_are_dependencies_by_default(self) -> None:
        schedule = _schedule(self.GRAPH, self.INVENTORY, config=_config())
        self.assertEqual(_names(schedule), [["f"]])
        self.assertEqual(schedule["waves"][0]["layer"], 0)
        f = _scheduled_items(schedule)[0]
        self.assertEqual([r["scope"] for r in f["depends_on"]["scheduled"]["types"] + f["depends_on"]["scheduled"]["symbols"]],
                         ["closure", "closure"])

    def test_flags_make_them_units(self) -> None:
        enums = _schedule(self.GRAPH, self.INVENTORY, config=_config(),
                          with_enums=True)
        self.assertEqual(_names(enums), [["E"], ["f"]])
        both = _schedule(self.GRAPH, self.INVENTORY, config=_config(),
                         with_enums=True, with_macros=True)
        self.assertEqual(_names(both), [["E", "M"], ["f"]])
        self.assertEqual((both["with_enums"], both["with_macros"]), (True, True))

    def test_a_generator_is_a_type_dependency(self) -> None:
        # GEN mints T, which uses it: T lists GEN among its types, as GEN's
        # own item is a type.
        graph = {"layers": [
            [{**_rec("GEN", "a.c"), "subkind": "macro_function",
              "type_generator_for": ["T"]}],
            [_rec("T", "a.c", kind="type", syms=[("GEN", "a.c")])]]}
        inventory = _inventory(types=[("T", "a.c")])
        inventory["closure"]["macros"] = [
            {"name": "GEN", "defined_in": "a.c", "declared_in": []}]
        items = {i["name"]: i for i in
                 _scheduled_items(_schedule(graph, inventory, config=_config()))}
        self.assertEqual(items["GEN"]["kind"], "type")
        self.assertEqual(items["T"]["depends_on"]["scheduled"],
                         {"types": [{"name": "GEN", "defined_in": "a.c",
                                     "scope": "scheduled"}], "symbols": []})


class CapTests(unittest.TestCase):
    def test_without_caps_a_wave_holds_one_batch_per_route(self) -> None:
        graph = {"layers": [[_rec("T", "a.c", kind="type"), _rec("f", "a.c"),
                             _rec("g", "a.c")]]}
        inventory = _inventory(functions=[("f", "a.c"), ("g", "a.c")],
                               types=[("T", "a.c")])
        schedule = _schedule(graph, inventory)
        self.assertEqual(schedule["caps"], {"max_syms": None, "max_loc": None,
                                            "max_types": None,
                                            "min_fields": None})
        self.assertEqual(
            [(b["kind"], [i["name"] for i in b["items"]])
             for b in schedule["waves"][0]["batches"]],
            [("type", ["T"]), ("symbol", ["f", "g"])])
        capped = _schedule(graph, inventory, caps={"max_syms": 1})
        self.assertEqual(len(capped["waves"][0]["batches"]), 3)
        self.assertEqual(_schedule(graph, inventory, caps={"max_loc": 0})["caps"]
                         ["max_loc"], None)


class StatsTests(unittest.TestCase):
    def test_a_use_counts_only_in_the_config_files(self) -> None:
        tables = {
            "t1/functions.csv": [
                {"name": "f", "linkage": "function_exported", "def_file": "a.c",
                 "decl_files": "a.h", "signature": "int f(void)", "loc": 3,
                 "is_variadic": 0}],
            "t2/function_calls.csv": [
                {"caller_name": c, "caller_file": file, "callee_name": "f",
                 "callee_def_file": "a.c", "call_line": 1}
                for c, file in (("g", "a.c"), ("h", "b.c"),
                                ("test_f", "tests/a.c"))],
            "t2/field_accesses.csv": [
                {"enclosing_name": u, "access_file": file, "struct_name": "S",
                 "struct_def_file": "a.h", "field_name": "x",
                 "access_kind": "read", "access_line": 1}
                for u, file in (("g", "a.c"), ("test_f", "tests/a.c"))],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, rows in tables.items():
                (root / name).parent.mkdir(exist_ok=True)
                with (root / name).open("w", newline="") as out:
                    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
            stats = Stats(root / "t1", root / "t2", {"a.c", "a.h", "b.c"})
        self.assertEqual(stats.of("f", "a.c", "symbol", "function_exported")
                         ["callers"], 2)
        self.assertEqual(stats.of("S", "a.h", "type", "struct")
                         ["field_touchers"], 1)


class GraphTests(unittest.TestCase):
    def test_cut_breaks_every_cycle_toward_the_producer(self) -> None:
        adj = {"x": {"y"}, "y": {"x", "z"}, "z": {"y"}}
        weight = {("x", "y"): 1, ("y", "x"): 1, ("y", "z"): 1, ("z", "y"): 5}
        cut = _cut(["x", "y", "z"], adj, lambda u, v: weight[(u, v)])
        rest = {u: {v for v in vs if (u, v) not in cut} for u, vs in adj.items()}
        layers = _layers(["x", "y", "z"], rest)
        self.assertEqual(layers["y"], 0)
        self.assertNotIn(("z", "y"), cut)


if __name__ == "__main__":
    unittest.main()
