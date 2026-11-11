"""Functions that once shared a key.

`use(left::Tag)` and `use(right::Tag)` collided as `use(Tag)`, the two
`apply` overloads as `apply(..(*)(..))`, the two `point` overloads as
`point(const left::Tag * *)`, and the two lambdas' call operators as
`operator()`. The function key spells parameter types with their scope,
function pointers with their signature, specifiers where C++ writes them,
and a closure member under its closure type, so each is one of its own.

`Hidden` and `hide(Hidden)` sit in an anonymous namespace, whose name starts
with `(`; a key that kept it would read as an anonymous tag and be dropped.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from . import support

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cpp_overloads"
SOURCES = ("overloads.cpp", "wavefront-config.json")
MARKERS = ("overloads.cpp", "left::", "right::", "lambda [] type")

LEFT = "use(left::Tag)"
RIGHT = "use(right::Tag)"
APPLY_LEFT = "apply(int (*)(left::Tag))"
APPLY_RIGHT = "apply(int (*)(right::Tag))"
POINT_TO_CONST = "point(const left::Tag * *)"
CONST_POINTER = "point(left::Tag * const *)"
# The closure types are named by the lambdas' positions in overloads.cpp.
FIRST_LAMBDA = "lambda [] type at line 30, col. 18::operator()(int) const"
SECOND_LAMBDA = "lambda [] type at line 31, col. 19::operator()(int) const"
HIDE = "hide(Hidden)"
BOTH, CALLBACKS, POINTERS, LAMBDAS = "both()", "callbacks()", "pointers()", "lambdas()"
HIDDEN = "hidden()"
CALLS = {
    (BOTH, LEFT), (BOTH, RIGHT),
    (CALLBACKS, APPLY_LEFT), (CALLBACKS, APPLY_RIGHT),
    (POINTERS, POINT_TO_CONST), (POINTERS, CONST_POINTER),
    (LAMBDAS, FIRST_LAMBDA), (LAMBDAS, SECOND_LAMBDA),
    (HIDDEN, HIDE),
}


def _golden(tier: str, name: str) -> list[dict]:
    return support.rows(FIXTURE / tier / f"{name}.csv")


class OverloadGoldenTests(unittest.TestCase):
    """What the recorded tables must say."""

    def test_each_function_has_its_own_key(self) -> None:
        defined = [r["name"] for r in _golden("t1", "functions") if r["def_file"] == "overloads.cpp"]
        self.assertEqual(len(defined), len(set(defined)), "a key is shared")
        expected = {caller for caller, _ in CALLS} | {callee for _, callee in CALLS}
        self.assertTrue(expected <= set(defined), expected - set(defined))
        self.assertFalse({"use(Tag)", "apply(..(*)(..))", "operator()"} & set(defined))

    def test_each_caller_reaches_its_callees(self) -> None:
        calls = {(r["caller_name"], r["callee_name"]) for r in _golden("t2", "function_calls")}
        self.assertEqual(calls, CALLS)

    def test_derived_parameter_types_keep_the_scope_of_their_base(self) -> None:
        # Compiler-declared special members spell a reference to a qualified
        # type around that type: `const left::Tag &`, `right::Tag &&`.
        names = {r["name"] for r in _golden("t1", "functions")}
        self.assertTrue({"left::Tag::operator=(const left::Tag &)",
                         "right::Tag::operator=(right::Tag &&)"} <= names, sorted(names))

    def test_members_of_closure_types_name_their_closure(self) -> None:
        by_name = {r["name"]: r for r in _golden("t1", "functions")}
        for name in (FIRST_LAMBDA, SECOND_LAMBDA):
            self.assertEqual(by_name[name]["member_kind"], "method", name)
            self.assertEqual(by_name[name]["declaring_type"], name.split("::operator")[0], name)

    def test_types_keep_their_namespace_unless_it_is_anonymous(self) -> None:
        tags = {r["name"] for r in _golden("t1", "types") if r["def_file"] == "overloads.cpp"}
        self.assertEqual(tags, {"left::Tag", "right::Tag", "Hidden"})

    def test_no_key_reads_as_an_anonymous_tag(self) -> None:
        for table in ("types", "functions"):
            for row in _golden("t1", table):
                if row["def_file"] == "overloads.cpp":
                    self.assertFalse(row["name"].startswith("("), row["name"])


class OverloadPipelineTests(unittest.TestCase):
    """The closure and the schedule keep the overloads apart."""

    def test_closures_hold_both_overloads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            support.stage(FIXTURE, repo, SOURCES)
            # `callbacks()` also takes the address of both `use` overloads, a
            # dependency in its own right.
            for caller, callees in ((BOTH, {LEFT, RIGHT}),
                                    (CALLBACKS, {APPLY_LEFT, APPLY_RIGHT, LEFT, RIGHT}),
                                    (POINTERS, {POINT_TO_CONST, CONST_POINTER})):
                closure = json.loads(support.wavefront(repo, "query", "dag", "--name", caller))
                self.assertEqual({f["id"] for f in closure["functions"]}, callees, caller)
            closure = json.loads(support.wavefront(repo, "query", "dag", "--name", BOTH))
            self.assertEqual({t["id"] for t in closure["types"]}, {"left::Tag", "right::Tag"})
            closure = json.loads(support.wavefront(repo, "query", "dag", "--name", HIDDEN))
            self.assertEqual({f["id"] for f in closure["functions"]}, {HIDE})
            self.assertEqual({t["id"] for t in closure["types"]}, {"Hidden"})

    def test_schedule_orders_each_caller_after_its_callees(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            support.stage(FIXTURE, repo, SOURCES)
            support.wavefront(repo, "schedule", "--name", BOTH, CALLBACKS, POINTERS, LAMBDAS,
                              HIDDEN, "--transitive", "--output", str(repo / "schedule.json"))
            schedule = json.loads((repo / "schedule.json").read_text())
            items = {i["name"]: i for w in schedule["waves"] for b in w["batches"]
                     for i in b["items"]}
            for caller, callee in CALLS:
                self.assertIn(callee, {d["name"] for d in items[caller]["deps"]["symbols"]}, caller)
                self.assertLess(items[callee]["layer"], items[caller]["layer"], (caller, callee))
            self.assertEqual({d["name"] for d in items[LEFT]["deps"]["types"]}, {"left::Tag"})
            self.assertEqual({d["name"] for d in items[RIGHT]["deps"]["types"]}, {"right::Tag"})
            self.assertEqual({d["name"] for d in items[HIDE]["deps"]["types"]}, {"Hidden"})


class OverloadQueryTests(unittest.TestCase):
    """The queries reproduce the recorded tables for the reproducer."""

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
