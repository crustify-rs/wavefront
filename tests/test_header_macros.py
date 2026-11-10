"""A macro defined in a closure header is in the `closure` section, its
definition sitting there, yet it is not the target's own: a `#define` cannot
be re-exported Rust->C, so only a closure `.c` file's TU-local macro is owned,
body-walked and a unit (docs/scoping.md#closure, docs/batching.md#units).
A macro a published header defines is part of the API, expanded or not; its
include guard is not."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from compose import deps_dag, scope, scope_manifest, syms_manifest
from compose.filter_spec import FilterSpec


def _write(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


_FN = ["name", "kind", "def_file", "decl_files", "linkage"]
_TY = ["name", "kind", "def_file", "decl_files", "aliases", "unaliased_kind"]


class _Stop(Exception):
    pass


class HeaderMacroTests(unittest.TestCase):
    def _inventory(self) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            t1 = root / "t1"
            t1.mkdir()
            _write(t1 / "functions.csv", _FN, [
                {"name": "mem_alloc", "kind": "function", "def_file": "src/mem.c",
                 "decl_files": "include/mem.h", "linkage": "external"}])
            _write(t1 / "globals.csv", _FN, [])
            _write(t1 / "macros.csv", ["name", "def_file", "include_guard"], [
                {"name": "MEM_MAX", "def_file": "include/mem.h",
                 "include_guard": "0"},
                {"name": "MEM_H", "def_file": "include/mem.h",
                 "include_guard": "1"},
                {"name": "MEM_LOCAL", "def_file": "src/mem.c",
                 "include_guard": "0"},
                {"name": "SYS_MAX", "def_file": "/usr/include/sys.h",
                 "include_guard": "0"}])
            _write(t1 / "types.csv", _TY, [])
            path = root / "wavefront-config.json"
            path.write_text(json.dumps({
                "closure": {"impl_files": {"included": ["src/mem.c"]},
                            "api_headers": {"included": ["include/mem.h"]}}}))
            return scope_manifest.compose(path, t1, root)

    def test_a_header_macro_is_in_the_closure_but_not_owned(self) -> None:
        inventory = self._inventory()
        self.assertEqual(
            scope.load_entities(inventory, scope.CLOSURE, "macros"),
            {("MEM_MAX", "include/mem.h"), ("MEM_H", "include/mem.h"),
             ("MEM_LOCAL", "src/mem.c")})
        self.assertEqual(scope.owned_entities(inventory, "macros"),
                         {("MEM_LOCAL", "src/mem.c")})
        self.assertEqual(scope.owned_entities(inventory, "functions"),
                         {("mem_alloc", "src/mem.c")})

    def test_the_api_publishes_a_header_macro_but_no_include_guard(self) -> None:
        self.assertEqual(
            scope.load_entities(self._inventory(), scope.API, "macros"),
            {("MEM_MAX", "include/mem.h")})

    def test_a_published_macro_is_a_record_though_nothing_expands_it(self) -> None:
        inventory = self._inventory()
        with tempfile.TemporaryDirectory() as td:
            t1 = Path(td) / "t1"
            t1.mkdir()
            _write(t1 / "functions.csv", _FN, [])
            _write(t1 / "globals.csv", _FN, [])
            _write(t1 / "macros.csv", ["name", "def_file", "include_guard"], [
                {"name": "MEM_MAX", "def_file": "include/mem.h",
                 "include_guard": "0"},
                {"name": "MEM_H", "def_file": "include/mem.h",
                 "include_guard": "1"},
                {"name": "MEM_PRIV", "def_file": "src/mem_priv.h",
                 "include_guard": "0"}])
            _write(t1 / "types.csv", _TY, [])
            reach = MagicMock()
            reach.is_macro_port_reachable.return_value = False
            reach.all_macro_call_sites.return_value = set()
            reach.all_macro_file_sites.return_value = set()
            with patch.object(syms_manifest, "Reach", return_value=reach):
                entries, _scope, _ = syms_manifest.compose(
                    t1, Path(td) / "t2", FilterSpec(scope_json_path=inventory))
        names = {e["name"] for v in entries.values() for e in v}
        self.assertIn("MEM_MAX", names)
        self.assertNotIn("MEM_H", names)
        self.assertNotIn("MEM_PRIV", names)

    def test_the_default_graph_body_walks_only_owned_macros(self) -> None:
        inventory = self._inventory()
        seen = {}

        def collect(_root, port_syms, *_args, **_kw):
            seen["port_syms"] = port_syms
            raise _Stop

        with tempfile.TemporaryDirectory() as td, \
                patch.object(deps_dag, "_collect", side_effect=collect), \
                patch.object(deps_dag, "port_touched_fields", return_value={}):
            with self.assertRaises(_Stop):
                deps_dag.compose(([], []), scope_json=inventory,
                                 codeql_dir=Path(td))
        self.assertIn(("MEM_LOCAL", "src/mem.c"), seen["port_syms"])
        self.assertIn(("mem_alloc", "src/mem.c"), seen["port_syms"])
        self.assertNotIn(("MEM_MAX", "include/mem.h"), seen["port_syms"])


if __name__ == "__main__":
    unittest.main()
