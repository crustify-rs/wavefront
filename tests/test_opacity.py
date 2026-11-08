"""Layout users and referrers, and the point of a schedule after which none is
left: `edges/layout_uses.ql`, `wavefront.opacity`, and the items' fields."""
from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_schedule_parity import _schedule, _scheduled_items
from test_selection import _config, _inventory, _modules, _rec

from wavefront import opacity
from wavefront.resources import data_root

FIXTURE = Path(__file__).parent / "fixtures" / "layout_uses"


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _key(r: dict) -> tuple:
    return tuple(r[k] for k in sorted(r))


class LayoutUsesQueryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("codeql"), "codeql not on PATH")
    def test_fixture_table_matches_golden(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, bqrs, out = (Path(td) / n for n in ("db", "q.bqrs", "q.csv"))
            subprocess.run(
                ["codeql", "database", "create", str(db), "--language=cpp",
                 "--source-root", str(FIXTURE),
                 "--command=gcc -std=c11 -c layout.c -o /dev/null"],
                check=True, capture_output=True)
            subprocess.run(
                ["codeql", "query", "run", f"--database={db}", f"--output={bqrs}",
                 str(data_root() / "edges/layout_uses.ql")],
                check=True, capture_output=True)
            subprocess.run(["codeql", "bqrs", "decode", "--format=csv",
                            f"--output={out}", str(bqrs)],
                           check=True, capture_output=True)
            got = [r for r in _rows(out) if r["type_def_file"] == "layout.c"]
            self.assertEqual(sorted(map(_key, got)),
                             sorted(map(_key, _rows(FIXTURE / "layout_uses.csv"))))


class LayoutUsesGoldenTests(unittest.TestCase):
    """What the golden table must say, so a regenerated one cannot drift."""

    rows = _rows(FIXTURE / "layout_uses.csv")

    def uses(self, user: str) -> set[tuple[str, str]]:
        return {(r["type_name"], r["use_kind"]) for r in self.rows
                if r["user_name"] == user}

    def test_every_kind_is_recorded(self) -> None:
        cases = {
            "field_read": {("Point", "field")},
            "field_addr": {("Point", "field")},
            "field_macro": {("Point", "field")},
            "field_anon": {("Conn", "field")},
            "size_type": {("Point", "size")},
            "size_expr": {("Point", "size")},
            "size_align": {("Str", "size")},
            "size_offsetof": {("Node", "size"), ("Node", "field")},
            "value_param": {("Point", "value")},
            "value_return": {("Point", "value")},
            "value_copy": {("Point", "value")},
            "value_literal": {("Point", "value")},
            "value_memcpy": {("Str", "size")},
            "index_add": {("Point", "index")},
            "index_incr": {("Point", "index")},
            "index_subscript": {("Point", "index"), ("Point", "field")},
            "index_diff": {("Point", "index")},
            "origin": {("Point", "value")},
            "table": {("Str", "value")},
            "Node": {("Base", "embed"), ("Point", "embed")},
        }
        for user, expected in cases.items():
            with self.subTest(user):
                self.assertEqual(self.uses(user), expected)

    def test_a_cast_through_a_pointer_is_no_layout_use(self) -> None:
        # `container_of` steps a `char *` and casts to `struct Node *`: it uses
        # Node's layout through offsetof, and nothing of Base's.
        self.assertEqual(self.uses("size_container"),
                         {("Node", "size"), ("Node", "field")})

    def test_pointer_only_uses_have_no_row(self) -> None:
        for user in ("opaque_pass", "opaque_cast", "opaque_null", "opaque_compare"):
            self.assertEqual(self.uses(user), set(), user)
        self.assertNotIn("Handle", {r["type_name"] for r in self.rows})


class OpacityTests(unittest.TestCase):
    def test_layout_users_close_over_embedding(self) -> None:
        base, node, outer = (("Base", "h.h", "type"), ("Node", "h.h", "type"),
                             ("Outer", "h.h", "type"))
        f, g, h = (("f", "a.c", "symbol"), ("g", "a.c", "symbol"),
                   ("h", "a.c", "symbol"))
        users = opacity.close_over_embedding({
            base: {node: {"embed"}, f: {"field"}},
            node: {outer: {"embed"}, g: {"size", "field"}},
            outer: {h: {"value"}, g: {"value"}},
        })
        self.assertEqual(users[base], {
            node: ({"embed"}, set()),
            f: ({"field"}, set()),
            outer: (set(), {node}),
            g: (set(), {node, outer}),
            h: (set(), {node, outer}),
        })
        self.assertEqual(users[outer], {h: ({"value"}, set()), g: ({"value"}, set())})

    def test_the_frontier_keeps_what_no_other_candidate_depends_on(self) -> None:
        order = opacity.Order({0: set(), 1: {0}, 2: {0}, 3: {1}})
        self.assertTrue(order.depends(3, 0))
        self.assertFalse(order.depends(3, 2))
        self.assertFalse(order.depends(0, 3))
        self.assertEqual(order.frontier({0, 1, 2}), [1, 2])
        self.assertEqual(order.frontier({0, 2, 3}), [2, 3])
        self.assertEqual(order.frontier({0, 1, 3}), [3])
        # A node the order does not hold is ordered against nothing.
        self.assertEqual(order.frontier({1, 3, 9}), [3, 9])


T = ("T", "h.c", "type")
A1, B1 = ("a1", "a.c", "symbol"), ("b1", "b.c", "symbol")

# T in h.c; a1 and b1, in modules A and B, read its layout; a2, in A, calls
# both. A's waves are a1's and a2's, and a2's depends on B's.
GRAPH = {"layers": [
    [_rec("T", "h.c", kind="type")],
    [_rec("a1", "a.c", types=[("T", "h.c")]), _rec("b1", "b.c", types=[("T", "h.c")])],
    [_rec("a2", "a.c", syms=[("a1", "a.c"), ("b1", "b.c")])]]}
INVENTORY = _inventory(functions=[("a1", "a.c"), ("a2", "a.c"), ("b1", "b.c")],
                       types=[("T", "h.c")])
FILES = ("a.c", "b.c", "h.c")


def _run(config: dict, **kwargs) -> dict:
    uses = {T: {A1: {"field"}, B1: {"value", "field"}}}
    with patch("wavefront.opacity.load_layout_uses", return_value=uses):
        return _schedule(GRAPH, INVENTORY, config=config, **kwargs)


def _items(schedule: dict) -> dict[str, dict]:
    return {i["name"]: i for i in _scheduled_items(schedule)}


def _wave(schedule: dict, name: str) -> int:
    return next(w["index"] for w in schedule["waves"]
                for b in w["batches"] for i in b["items"] if i["name"] == name)


def _item(name: str, defined_in: str, kind: str, module: str | None,
          wave: int | None = None) -> dict:
    out = {"name": name, "defined_in": defined_in, "kind": kind, "module": module}
    if wave is not None:
        out["wave"] = wave
    return out


class ReleasePointTests(unittest.TestCase):
    config = _modules(_config(files=FILES), ("A", "a.c"), ("B", "b.c"), ("H", "h.c"))

    def test_a_type_is_opaque_after_its_last_layout_users(self) -> None:
        schedule = _run(self.config)
        self.assertEqual(schedule["schema_version"], 5)
        items = _items(schedule)
        wa1, wb1 = _wave(schedule, "a1"), _wave(schedule, "b1")
        last = [_item("a1", "a.c", "symbol", "A", wa1), _item("b1", "b.c", "symbol", "B", wb1)]
        # a1 and b1 do not depend on each other, nor do their waves: both are
        # last. But A's run ends after B's, which a2 depends on: A is the last
        # module.
        self.assertEqual(items["T"]["opaque_after"], {
            "closure": {"users": 2, "items": last, "modules": ["A"]},
            "scheduled": {"users": 2, "items": last, "waves": sorted([wa1, wb1]),
                          "modules": ["A"]}})
        self.assertIsNone(items["T"]["unreferenced_after"])
        self.assertIsNone(items["a1"]["opaque_after"])
        self.assertNotIn("layout_users", items["T"])

    def test_a_symbol_is_unreferenced_after_its_last_referrers(self) -> None:
        schedule = _run(self.config)
        items = _items(schedule)
        wa2 = _wave(schedule, "a2")
        self.assertNotIn("referrers", items["b1"])
        a2 = [_item("a2", "a.c", "symbol", "A", wa2)]
        self.assertEqual(items["b1"]["unreferenced_after"], {
            "closure": {"users": 1, "items": a2, "modules": ["A"]},
            "scheduled": {"users": 1, "items": a2, "waves": [wa2], "modules": ["A"]}})
        # Nothing refers to a2: it is unreferenced after itself.
        self.assertEqual(items["a2"]["unreferenced_after"], {
            "closure": {"users": 0, "items": a2, "modules": ["A"]},
            "scheduled": {"users": 0, "items": a2, "waves": [wa2], "modules": ["A"]}})

    def test_a_narrow_schedule_tells_the_closure_from_itself(self) -> None:
        config = _modules(_config("h.c", files=FILES),
                          ("A", "a.c"), ("B", "b.c"), ("H", "h.c"))
        schedule = _run(config)
        wt = _wave(schedule, "T")
        # The closure still has both users, though the schedule holds neither
        # of them; the schedule has T alone.
        self.assertEqual(_items(schedule)["T"]["opaque_after"], {
            "closure": {"users": 2,
                        "items": [_item("a1", "a.c", "symbol", "A"),
                                  _item("b1", "b.c", "symbol", "B")],
                        "modules": ["A"]},
            "scheduled": {"users": 0, "items": [_item("T", "h.c", "type", "H", wt)],
                          "waves": [wt], "modules": ["H"]}})

    def test_without_modules_the_waves_still_answer(self) -> None:
        schedule = _run(_config(files=FILES))
        t = _items(schedule)["T"]["opaque_after"]
        w = _wave(schedule, "a1")
        last = [_item("a1", "a.c", "symbol", None, w), _item("b1", "b.c", "symbol", None, w)]
        self.assertEqual(t, {
            "closure": {"users": 2, "items": last, "modules": None},
            "scheduled": {"users": 2, "items": last, "waves": [w], "modules": None}})

    def test_an_api_schedule_has_no_release_points(self) -> None:
        # a2 is the API; it reaches every other unit.
        inventory = _inventory(functions=[("a1", "a.c"), ("a2", "a.c"), ("b1", "b.c")],
                               types=[("T", "h.c")])
        inventory["api"]["functions"] = [{"name": "a2", "defined_in": "a.c",
                                          "declared_in": ["a.c"]}]
        with patch("wavefront.opacity.load_layout_uses") as load:
            schedule = _schedule(GRAPH, inventory, config=self.config,
                                 api_headers_only=True)
        load.assert_not_called()
        self.assertEqual(len(_scheduled_items(schedule)), 4)
        for item in _scheduled_items(schedule):
            self.assertIsNone(item["opaque_after"], item["name"])
            self.assertIsNone(item["unreferenced_after"], item["name"])

    def test_the_closure_frontier_follows_the_units_order(self) -> None:
        # b1 and a2 both refer to x, and a2 depends on b1: only a2 is last,
        # in the closure's order and in the schedule's waves alike.
        graph = {"layers": [
            [_rec("x", "h.c")],
            [_rec("b1", "b.c", syms=[("x", "h.c")])],
            [_rec("a2", "a.c", syms=[("x", "h.c"), ("b1", "b.c")])]]}
        inventory = _inventory(functions=[("x", "h.c"), ("a2", "a.c"), ("b1", "b.c")])
        with patch("wavefront.opacity.load_layout_uses", return_value={}):
            schedule = _schedule(graph, inventory, config=self.config)
        x = _items(schedule)["x"]["unreferenced_after"]
        self.assertEqual(x["closure"]["users"], 2)
        self.assertEqual([i["name"] for i in x["closure"]["items"]], ["a2"])
        self.assertEqual([i["name"] for i in x["scheduled"]["items"]], ["a2"])
        self.assertEqual(x["closure"]["modules"], ["A"])


if __name__ == "__main__":
    unittest.main()
