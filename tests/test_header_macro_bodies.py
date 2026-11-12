"""A macro the closure defines, in a header as much as in a `.c` file, depends
on what its replacement list references: the functions, globals and macros it
names, and the types it names or reaches into a field of
(`edges/macro_references.ql`, docs/graph.md#edges). A constant references
nothing and depends on nothing; a macro an external header defines stays
signature-only, as an external function does."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import codeql_fixtures as cf
from compose import deps_dag, syms_manifest

NAME = "header_macro_bodies"
FIXTURE = cf.FIXTURES / NAME
SRC = Path(__file__).resolve().parents[1] / "src"

#: The fixture's own macro references, of its committed tables.
GOLDEN = cf.relative(cf.rows(cf.tables(NAME) / "t2" / "macro_references.csv"))


def _additions(name: str, def_file: str) -> dict:
    """`_port_additions_macro` over the golden table."""
    reach = MagicMock()
    reach.all_macro_call_sites.return_value = set()
    reach.all_macro_file_sites.return_value = set()
    reach.macro_references_of.side_effect = lambda n, df: sorted(
        (r["ref_kind"], r["ref_name"], r["ref_def_file"], r["field_name"])
        for r in GOLDEN if (r["macro_name"], r["macro_def_file"]) == (n, df))
    by_name = {"size_t": {"name": "size_t", "kind": "typedef", "def_file": "",
                          "decl_files": "/usr/include/stddef.h", "aliases": "",
                          "unaliased_kind": "primitive"}}
    return syms_manifest._port_additions_macro(
        {"name": name, "def_file": def_file}, reach, by_name, {})["depends_on"]


def _syms(dep: dict) -> set[tuple[str, str]]:
    return {(d["name"], d["defined_in"]) for d in dep["syms"]}


class MacroReferenceGoldenTests(unittest.TestCase):
    def test_a_macro_depends_on_the_functions_it_calls(self) -> None:
        self.assertEqual(_syms(_additions("MEM_NEW", "mem.h")),
                         {("mem_alloc", "mem.c"), ("mem_zero", "mem.c")})

    def test_a_macro_depends_on_globals_and_macros_it_names(self) -> None:
        self.assertEqual(_syms(_additions("MEM_DROP", "mem.h")),
                         {("mem_free", "mem.c"), ("mem_live", "mem.c")})
        # Not on what the macros it expands call.
        self.assertEqual(_syms(_additions("MEM_RENEW", "mem.h")),
                         {("MEM_DROP", "mem.h"), ("MEM_NEW", "mem.h")})

    def test_a_macro_depends_on_the_types_it_reaches_into(self) -> None:
        dep = _additions("MEM_POOL_RESET", "mem.h")
        self.assertEqual(dep["types"], [{"type": "pool", "fields": ["used"]}])
        self.assertEqual(_syms(dep), {("MEM_MAX", "mem.h")})

    def test_a_symbol_alias_depends_on_the_function_it_names(self) -> None:
        self.assertEqual(_syms(_additions("mem_release", "mem.h")),
                         {("mem_free", "mem.c")})

    def test_a_constant_depends_on_nothing(self) -> None:
        self.assertEqual(_additions("MEM_MAX", "mem.h"), {"syms": [], "types": []})

    def test_what_an_argument_names_is_the_callers(self) -> None:
        self.assertEqual(_additions("MEM_APPLY", "mem.h"), {"syms": [], "types": []})
        # A field of whatever the argument points at, too, and a global the
        # argument names that shares a name the replacement list writes.
        self.assertEqual(_additions("MEM_USED", "mem.h"), {"syms": [], "types": []})
        self.assertEqual(_additions("MEM_POOL_SET", "mem.h"), {"syms": [], "types": []})


class BodyWalkTests(unittest.TestCase):
    """Which macros the default graph gives body edges."""

    def _symbols(self, port_syms):
        recs = []
        for name, df in (("MEM_NEW", "mem.h"), ("SYS_LOG", "ext/sys.h"),
                         ("LOCAL_ZERO", "mem.c")):
            recs.append({"name": name, "kind": "macro", "defined_in": df,
                         "declared_in": [df], "loc": 0,
                         "depends_on": _additions(name, df)})
        for name, df in (("mem_alloc", "mem.c"), ("mem_zero", "mem.c"),
                         ("sys_log", "use.c")):
            recs.append({"name": name, "kind": "function_exported", "defined_in": df,
                         "declared_in": [df], "loc": 3,
                         "depends_on": {"syms": [], "types": []},
                         "ptr_args": [], "ptr_ret": None})

        def entries(_root, kind):
            return recs if kind == "symbols" else []

        with patch.object(deps_dag, "_entries_of", side_effect=entries):
            _types, syms, _aliases = deps_dag._collect(
                object(), port_syms=port_syms, port_fields={}, codeql_dir=None,
                in_scope_types=set(), layout_paths=set())
        return syms

    def test_a_closure_macro_has_body_edges_an_external_one_none(self) -> None:
        syms = self._symbols({("MEM_NEW", "mem.h"), ("LOCAL_ZERO", "mem.c")})
        self.assertEqual(syms[("MEM_NEW", "mem.h")].dep_on_syms,
                         {("mem_alloc", "mem.c"), ("mem_zero", "mem.c")})
        self.assertEqual(syms[("LOCAL_ZERO", "mem.c")].dep_on_syms,
                         {("mem_zero", "mem.c")})
        self.assertEqual(syms[("SYS_LOG", "ext/sys.h")].dep_on_syms, set())


class HeaderMacroScheduleTests(unittest.TestCase):
    """The fixture's committed tables scheduled end to end."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._td = tempfile.TemporaryDirectory()
        td = Path(cls._td.name)
        state = cf.state_dir(NAME, td)
        config = td / "wavefront-config.json"
        config.write_text(json.dumps({
            "state_dir": str(state),
            "closure": {"impl_files": {"included": ["mem.c", "mem.h", "use.c"]},
                        "api_headers": {"included": ["mem.h"]}}}))
        out = td / "schedule.json"
        env = dict(os.environ, PYTHONPATH=str(SRC), PYTHONHASHSEED="0")
        subprocess.run(
            [sys.executable, "-m", "wavefront.cli", str(FIXTURE), "--config",
             str(config), "schedule", "--output", str(out)],
            check=True, capture_output=True, env=env)
        cls.schedule = json.loads(out.read_text())
        cls.wave, cls.items = {}, {}
        for wave in cls.schedule["waves"]:
            for batch in wave["batches"]:
                for item in batch["items"]:
                    cls.wave[item["name"]] = wave["index"]
                    cls.items[item["name"]] = item

    @classmethod
    def tearDownClass(cls) -> None:
        cls._td.cleanup()

    def test_a_header_macro_orders_after_the_functions_it_calls(self) -> None:
        self.assertGreater(self.wave["MEM_NEW"], self.wave["mem_alloc"])
        self.assertGreater(self.wave["MEM_NEW"], self.wave["mem_zero"])
        self.assertGreater(self.wave["MEM_RENEW"], self.wave["MEM_NEW"])
        self.assertGreater(self.wave["mem_release"], self.wave["mem_free"])

    def test_a_constant_has_no_edges(self) -> None:
        self.assertEqual(self.items["MEM_MAX"]["depends_on"],
                         {"scheduled": [], "cut": []})

    def test_an_external_headers_macro_has_none(self) -> None:
        self.assertNotIn("SYS_LOG", self.items)
        self.assertIn("SYS_LOG", {d["name"] for d in
                                  self.items["widget_make"]["depends_on"]["scheduled"]})
        dag = subprocess.run(
            [sys.executable, "-m", "wavefront.cli", str(FIXTURE), "--config",
             str(Path(self._td.name) / "wavefront-config.json"),
             "query", "dag", "--name", "SYS_LOG", "--depth", "1"],
            check=True, capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=str(SRC), PYTHONHASHSEED="0"))
        self.assertNotIn("sys_log", dag.stdout)

    def test_a_macro_its_callee_expands_is_a_cut_cycle(self) -> None:
        macro, fn = self.items["MEM_TRACE"], self.items["mem_trace"]
        cut = ({d["name"] for d in macro["depends_on"]["cut"]}
               | {d["name"] for d in fn["depends_on"]["cut"]})
        self.assertTrue(cut & {"MEM_TRACE", "mem_trace"})


@unittest.skipUnless(cf.codeql_enabled(), cf.SKIP_REASON)
class HeaderMacroTablesTests(unittest.TestCase):
    """The committed tables are what the queries extract from the fixture."""

    def test_the_committed_tables_are_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cf.differences(NAME, cf.extract(NAME, Path(td))), [])


if __name__ == "__main__":
    unittest.main()
