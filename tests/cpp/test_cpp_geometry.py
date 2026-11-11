"""The C++ geometry example as a regression test.

The recorded tables must drive the example's queries and schedule to the
output its checker accepts, and must say what the demo claims: one key per
overload, members that name their class, and a scope-exit destructor call.
With `codeql` on PATH, the queries must reproduce the recorded tables.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from wavefront.resources import data_root

from . import support

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cpp_geometry"
EXAMPLE = data_root().parent / "examples" / "cpp_geometry"
SOURCES = ("geometry.hpp", "geometry.cpp", "wavefront-config.json")
MARKERS = ("geometry.", "geometry::")

POINT = "geometry::Point"
RECTANGLE = "geometry::Rectangle"
CONSTRUCTOR = "geometry::Rectangle::Rectangle(geometry::Point, geometry::Point)"
DESTRUCTOR = "geometry::Rectangle::~Rectangle()"
AREA = "geometry::Rectangle::area() const"
SCALED_AREA = "geometry::Rectangle::area(double) const"
CALLER = "geometry::calculate_area(geometry::Point, geometry::Point, double)"
MEMBERS = (CONSTRUCTOR, DESTRUCTOR, AREA, SCALED_AREA)


def _golden(tier: str, name: str) -> list[dict]:
    return support.rows(FIXTURE / tier / f"{name}.csv")


class GeometryGoldenTests(unittest.TestCase):
    """What the recorded tables must say."""

    def test_fixture_sources_are_the_example_sources(self) -> None:
        for name in SOURCES:
            self.assertEqual((FIXTURE / name).read_text(), (EXAMPLE / name).read_text(), name)

    def test_types_keep_their_namespace_and_kind(self) -> None:
        kinds = {r["name"]: r["kind"] for r in _golden("t1", "types")
                 if r["def_file"] == "geometry.hpp"}
        self.assertEqual(kinds, {POINT: "struct", RECTANGLE: "class"})

    def test_each_overload_has_its_own_key(self) -> None:
        defined = {r["name"] for r in _golden("t1", "functions") if r["def_file"] == "geometry.cpp"}
        self.assertEqual(defined, {*MEMBERS, CALLER})

    def test_members_name_their_class(self) -> None:
        by_name = {r["name"]: r for r in _golden("t1", "functions")}
        for name, kind in ((CONSTRUCTOR, "constructor"), (DESTRUCTOR, "destructor"),
                           (AREA, "method"), (SCALED_AREA, "method")):
            self.assertEqual(by_name[name]["member_kind"], kind, name)
            self.assertEqual(by_name[name]["declaring_type"], RECTANGLE, name)
        self.assertEqual(by_name[CALLER]["member_kind"], "")
        owners = {(r["function_name"], r["type_name"])
                  for r in _golden("t2", "signature_type_uses") if r["position"] == "declaring_type"}
        self.assertTrue({(m, RECTANGLE) for m in MEMBERS} <= owners)

    def test_scope_exit_destructor_call_is_an_edge(self) -> None:
        calls = {(r["caller_name"], r["callee_name"]) for r in _golden("t2", "function_calls")}
        self.assertEqual(calls, {(CALLER, CONSTRUCTOR), (CALLER, SCALED_AREA),
                                 (CALLER, DESTRUCTOR), (SCALED_AREA, AREA)})

    def test_rectangle_embeds_two_points(self) -> None:
        fields = {(r["field_name"], r["type_name"]) for r in _golden("t2", "field_type_uses")
                  if r["struct_name"] == RECTANGLE}
        self.assertEqual(fields, {("lower_", POINT), ("upper_", POINT)})


class GeometryPipelineTests(unittest.TestCase):
    """The CLI composes the recorded tables into the demo's output."""

    def test_demo_checker_accepts_the_composed_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            support.stage(FIXTURE, repo, SOURCES)
            (repo / "types.json").write_text(
                support.wavefront(repo, "query", "types", "--name", POINT, RECTANGLE))
            (repo / "symbols.json").write_text(
                support.wavefront(repo, "query", "symbols", "--name", *MEMBERS, CALLER))
            (repo / "dependencies.json").write_text(
                support.wavefront(repo, "query", "dag", "--name", CALLER))
            support.wavefront(repo, "schedule", "--name", CALLER, "--transitive",
                              "--output", str(repo / "schedule.json"))
            with contextlib.redirect_stdout(io.StringIO()):
                support.load_module(EXAMPLE / "verify.py").verify(repo)

            closure = json.loads((repo / "dependencies.json").read_text())
            self.assertEqual({t["id"] for t in closure["types"]}, {POINT, RECTANGLE})
            self.assertEqual({f["id"] for f in closure["functions"]}, set(MEMBERS))
            schedule = json.loads((repo / "schedule.json").read_text())
            self.assertEqual(schedule["summary"], {
                "unit_count": 7, "layer_count": 5, "batch_count": 2, "file_count": 2})
            self.assertEqual([b["kind"] for w in schedule["waves"] for b in w["batches"]],
                             ["type", "symbol"])


class GeometryQueryTests(unittest.TestCase):
    """The queries reproduce the recorded tables for the example sources."""

    @unittest.skipUnless(shutil.which("codeql"), "codeql not on PATH")
    def test_queries_reproduce_the_recorded_tables(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tables = support.extract(FIXTURE, Path(td), SOURCES)
            for tier in support.TIERS:
                for golden in sorted((FIXTURE / tier).glob("*.csv")):
                    self.assertEqual(
                        support.in_repo(support.rows(tables / tier / golden.name), MARKERS),
                        support.in_repo(support.rows(golden), MARKERS), f"{tier}/{golden.name}")


if __name__ == "__main__":
    unittest.main()
