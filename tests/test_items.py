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


class ItemsTests(unittest.TestCase):
    """`items.included` and `items.excluded` narrow a config to entities, so that
    two configs can share a file and split what it defines (docs/scoping.md#items)."""

    def _compose(self, **narrowing) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            t1 = root / "t1"
            t1.mkdir()
            _write(t1 / "functions.csv", _FN, [
                _fn("mem_alloc"), _fn("mem_free"), _fn("str_dup"),
                # Declared in the public header, with no body in the database.
                _fn("mem_hook", df="", decls="include/mem.h")])
            # A struct tag and a global of one name in one file.
            _write(t1 / "globals.csv", _FN, [_fn("pool", df="src/mem.c", decls="src/mem.c")])
            _write(t1 / "macros.csv", ["name", "def_file", "decl_files"], [
                {"name": "MEM_MAX", "def_file": "include/mem.h", "decl_files": ""}])
            _write(t1 / "types.csv", _TY, [
                {"name": "pool", "kind": "struct", "def_file": "src/mem.c",
                 "decl_files": "include/mem.h", "aliases": "", "unaliased_kind": "struct"},
                {"name": "pool_t", "kind": "typedef", "def_file": "include/mem.h",
                 "decl_files": "", "aliases": "pool", "unaliased_kind": "struct"}])
            config = {"state_dir": ".wavefront",
                      "impl_files": {"included": ["src/mem.c"]},
                      "api_headers": {"included": ["include/mem.h"]}, **narrowing}
            path = root / "wavefront-config.json"
            path.write_text(json.dumps(config))
            return scope_manifest.compose(path, t1, root)

    @staticmethod
    def _names(section: dict, kind: str) -> set[str]:
        return {e["name"] for e in section[kind]}

    def test_a_config_without_lists_owns_its_files_whole(self) -> None:
        m = self._compose()
        self.assertEqual(self._names(m["targeted"], "functions"),
                         {"mem_alloc", "mem_free", "str_dup", "mem_hook"})
        self.assertFalse(any(m[scope_manifest.NARROWED].values()))

    def test_items_narrow_the_targeted_section_to_the_listed_entities(self) -> None:
        m = self._compose(items={"included": [
            {"name": "mem_alloc", "defined_in": "src/mem.c", "kind": "symbol"},
            {"name": "mem_hook", "defined_in": "include/mem.h", "kind": "symbol"}]})
        self.assertEqual(self._names(m["targeted"], "functions"), {"mem_alloc", "mem_hook"})
        self.assertEqual(self._names(m[scope_manifest.NARROWED], "functions"),
                         {"mem_free", "str_dup"})
        self.assertEqual(self._names(m["targeted"], "types"), set())
        # The api view is publication, not ownership: it is not narrowed.
        self.assertIn("str_dup", self._names(m["api"], "functions"))

    def test_out_of_scope_items_exclude_the_listed_entities(self) -> None:
        m = self._compose(items={"excluded": [
            {"name": "str_dup", "defined_in": "src/mem.c", "kind": "symbol"}]})
        self.assertEqual(self._names(m["targeted"], "functions"),
                         {"mem_alloc", "mem_free", "mem_hook"})
        self.assertEqual(self._names(m[scope_manifest.NARROWED], "functions"), {"str_dup"})

    def test_a_typedef_and_its_type_are_one_entity(self) -> None:
        for entry in ({"name": "pool_t", "defined_in": "include/mem.h", "kind": "type"},
                      {"name": "pool", "defined_in": "src/mem.c", "kind": "type"}):
            m = self._compose(items={"included": [entry]})
            self.assertEqual(self._names(m["targeted"], "types"), {"pool", "pool_t"})

    def test_narrowed_entities_are_filed_as_imported(self) -> None:
        m = self._compose(items={"excluded": [
            {"name": "str_dup", "defined_in": "src/mem.c", "kind": "symbol"}]})
        m["imported"] = {"files": [], "functions": [], "globals": [],
                         "macros": [], "types": []}
        scope_manifest.file_narrowed(m)
        self.assertEqual(self._names(m["imported"], "functions"), {"str_dup"})
        self.assertNotIn(scope_manifest.NARROWED, m)

    def test_kind_tells_a_struct_from_a_global_of_its_name(self) -> None:
        m = self._compose(items={"included": [
            {"name": "pool", "defined_in": "src/mem.c", "kind": "symbol"}]})
        self.assertEqual(self._names(m["targeted"], "globals"), {"pool"})
        self.assertEqual(self._names(m["targeted"], "types"), set())
        m = self._compose(items={"excluded": [
            {"name": "pool", "defined_in": "src/mem.c", "kind": "type"}]})
        self.assertEqual(self._names(m["targeted"], "globals"), {"pool"})
        self.assertEqual(self._names(m["targeted"], "types"), set())

    def test_excluded_files_leave_a_directory_entry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for f in ("src/a.c", "src/tests/t.c", "include/a.h"):
                (root / f).parent.mkdir(parents=True, exist_ok=True)
                (root / f).write_text("")
            config = {"impl_files": {"included": ["src/"], "excluded": ["src/tests/"]},
                      "api_headers": {"included": ["include/a.h"]}}
            self.assertEqual(scope_manifest.targeted_candidates(config, root),
                             ["include/a.h", "src/a.c"])

    def test_errors(self) -> None:
        sym = {"name": "str_dup", "defined_in": "src/mem.c", "kind": "symbol"}
        cases = {
            "do not define": {"items": {"included": [
                {"name": "nope", "defined_in": "src/mem.c", "kind": "symbol"}]}},
            "header macro": {"items": {"included": [
                {"name": "MEM_MAX", "defined_in": "include/mem.h", "kind": "symbol"}]}},
            "both name": {"items": {"included": [sym], "excluded": [sym]}},
            "must be": {"items": {"included": [{"name": "str_dup", "defined_in": "src/mem.c"}]}},
            "repeats": {"items": {"included": [sym] * 2}},
            "kind": {"items": {"included": [dict(sym, kind="function")]}},
            "no longer read": {"out_of_scope": {"paths": ["src/tests/"]}},
            "must be an object": {"items": [sym]},
        }
        for message, narrowing in cases.items():
            with self.subTest(message), self.assertRaisesRegex(SystemExit, message):
                self._compose(**narrowing)


if __name__ == "__main__":
    unittest.main()
