from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from compose import scope_manifest


def _write(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


_FN = ["name", "kind", "def_file", "decl_files", "linkage"]
_TY = ["name", "kind", "def_file", "decl_files", "aliases", "unaliased_kind"]


def _fn(name: str, df: str = "src/mem.c", decls: str = "include/mem.h") -> dict:
    return {"name": name, "kind": "function", "def_file": df,
            "decl_files": decls, "linkage": "external"}


class ClosureTests(unittest.TestCase):
    """`closure` names the program Wavefront analyzes: its files' entities are
    the closure section, whole (docs/scoping.md#files)."""

    def _compose(self, **config) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            t1 = root / "t1"
            t1.mkdir()
            _write(t1 / "functions.csv", _FN, [
                _fn("mem_alloc"), _fn("mem_free"), _fn("str_dup"),
                # Declared in the public header, with no body in the database.
                _fn("mem_hook", df="", decls="include/mem.h")])
            _write(t1 / "globals.csv", _FN, [_fn("pool", df="src/mem.c", decls="src/mem.c")])
            _write(t1 / "macros.csv", ["name", "def_file", "decl_files"], [
                {"name": "MEM_MAX", "def_file": "include/mem.h", "decl_files": ""}])
            _write(t1 / "types.csv", _TY, [
                {"name": "pool", "kind": "struct", "def_file": "src/mem.c",
                 "decl_files": "include/mem.h", "aliases": "", "unaliased_kind": "struct"}])
            config = config or {
                "state_dir": ".wavefront",
                "closure": {"impl_files": {"included": ["src/mem.c"]},
                            "api_headers": {"included": ["include/mem.h"]}}}
            path = root / "wavefront-config.json"
            path.write_text(json.dumps(config))
            return scope_manifest.compose(path, t1, root)

    @staticmethod
    def _names(section: dict, kind: str) -> set[str]:
        return {e["name"] for e in section[kind]}

    def test_the_closure_owns_its_files_whole(self) -> None:
        m = self._compose()
        self.assertEqual(self._names(m["closure"], "functions"),
                         {"mem_alloc", "mem_free", "str_dup", "mem_hook"})
        self.assertEqual(self._names(m["closure"], "globals"), {"pool"})
        self.assertEqual(self._names(m["closure"], "types"), {"pool"})

    def test_excluded_files_leave_a_directory_entry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for f in ("src/a.c", "src/tests/t.c", "include/a.h"):
                (root / f).parent.mkdir(parents=True, exist_ok=True)
                (root / f).write_text("")
            config = {"closure": {
                "impl_files": {"included": ["src/"], "excluded": ["src/tests/"]},
                "api_headers": {"included": ["include/a.h"]}}}
            self.assertEqual(scope_manifest.closure_candidates(config, root),
                             ["include/a.h", "src/a.c"])

    def test_errors(self) -> None:
        files = {"impl_files": {"included": ["src/mem.c"]}}
        cases = {
            "unknown top-level keys \\['impl_files'\\]": files,
            "unknown top-level keys \\['items'\\]": {
                "closure": files, "items": {"excluded": []}},
            "unknown top-level keys \\['out_of_scope'\\]": {
                "closure": files, "out_of_scope": {"paths": []}},
            "`closure` must be an object": {"closure": ["src/mem.c"]},
            "must be an object of `included`": {
                "closure": {"impl_files": ["src/mem.c"]}},
        }
        for message, config in cases.items():
            with self.subTest(message), self.assertRaisesRegex(SystemExit, message):
                self._compose(**config)


if __name__ == "__main__":
    unittest.main()
