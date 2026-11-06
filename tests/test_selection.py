"""Scheduling: the order over every unit of the closure, and the selection a
config's `schedule` keeps of it."""
from __future__ import annotations

import csv
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
        "targeted": {**none,
                     "functions": [{"name": n, "defined_in": h,
                                    "declared_in": list(d)}
                                   for n, h, *d in functions],
                     "types": [{"name": n, "defined_in": h,
                                "declared_in": list(d)}
                               for n, h, *d in types]},
        "imported": dict(none), "api": dict(none),
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
        self.assertEqual([w["layers"] for w in schedule["waves"]],
                         [[0], [1], [2]])

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
        self.assertEqual([r["name"] for r in items["a1"]["higher_cuts"]], ["b2"])
        self.assertEqual([r["name"] for r in items["b2"]["lower_cuts"]], ["a1"])
        self.assertEqual(items["a1"]["deps"]["symbols"],
                         [{"name": "b1", "defined_in": "b.c", "scope": "scheduled"}])
        self.assertEqual([items[n]["layer"] for n in ("b1", "a1", "b2")], [0, 1, 2])

    def test_an_item_carries_its_declarations(self) -> None:
        items = {i["name"]: i for i in _scheduled_items(
            _schedule(GRAPH, INVENTORY, config=_config()))}
        self.assertEqual(items["b1"]["declared_in"], ["b.c", "h.h"])


class SelectionTests(unittest.TestCase):
    def test_a_selection_keeps_the_order_of_the_whole_closure(self) -> None:
        whole = {i["name"]: i["layer"] for i in _scheduled_items(
            _schedule(GRAPH, INVENTORY, config=_config()))}
        narrow = _schedule(GRAPH, INVENTORY, config=_config("a.c"))
        self.assertEqual(_names(narrow), [["b1"], ["a1"], ["a2"]])
        for item in _scheduled_items(narrow):
            self.assertEqual(item["layer"], whole[item["name"]])

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

    def test_a_selection_brings_what_it_depends_on(self) -> None:
        schedule = _schedule(GRAPH, INVENTORY, config=_config("a.c"))
        items = {i["name"]: i for i in _scheduled_items(schedule)}
        self.assertEqual({n: i["seeded"] for n, i in items.items()},
                         {"a1": True, "a2": True, "b1": False})
        self.assertEqual(items["a1"]["deps"]["symbols"],
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
            "no targeted entity": _config(
                {"path": "h.h", "items": {"included": [{"name": "V", "kind": "type"}]}}),
            "no targeted entity ": _config(
                {"path": "h.h", "items": {"included": [{"name": "T", "kind": "symbol"}]}}),
            "both lists name": _config({"path": "h.h", "items": {
                "included": [{"name": "T", "kind": "type"}],
                "excluded": [{"name": "T", "kind": "type"}]}}),
            "the closure does not": _config("c.c"),
            "a directory": _config({"path": "src/", "items": {}}),
            "non-empty list": {"closure": {"impl_files": {"included": ["a.c"]}},
                               "schedule_seeds": []},
        }
        for message, config in cases.items():
            with self.subTest(message), \
                    self.assertRaisesRegex(SystemExit, message.strip()):
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
        self.assertEqual(_scheduled_items(schedule)[0]["layer"], 0)
        f = _scheduled_items(schedule)[0]
        self.assertEqual([r["scope"] for r in f["deps"]["types"] + f["deps"]["symbols"]],
                         ["closure", "closure"])

    def test_flags_make_them_units(self) -> None:
        enums = _schedule(self.GRAPH, self.INVENTORY, config=_config(),
                          with_enums=True)
        self.assertEqual(_names(enums), [["E"], ["f"]])
        both = _schedule(self.GRAPH, self.INVENTORY, config=_config(),
                         with_enums=True, with_macros=True)
        self.assertEqual(_names(both), [["E", "M"], ["f"]])
        self.assertEqual((both["with_enums"], both["with_macros"]), (True, True))


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
