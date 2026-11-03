"""A field keeps the callback typedef it is declared with, even when the
callback's signature names a struct that one translation unit completes and
another leaves opaque: the extractor then gives the field one routine type per
variant, none of them the typedef, and the typedef's field edge was lost."""
from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from wavefront.resources import data_root

FIXTURE = Path(__file__).parent / "fixtures" / "callback_typedefs"
QUERIES = ("entities/fields", "edges/field_type_uses")
SOURCES = ("api.h", "impl.c", "user.c")


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _golden(name: str) -> list[dict]:
    return _rows(FIXTURE / f"{name}.csv")


def _key(r: dict) -> tuple:
    return tuple(r[k] for k in sorted(r))


class CallbackTypedefQueryTests(unittest.TestCase):
    """The queries reproduce the golden tables for `impl.c` and `user.c`."""

    @unittest.skipUnless(shutil.which("codeql"), "codeql not on PATH")
    def test_fixture_tables_match_golden(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db"
            # Two translation units, so `handle` is complete in one and opaque
            # in the other.
            subprocess.run(
                ["codeql", "database", "create", str(db), "--language=cpp",
                 "--source-root", str(FIXTURE),
                 "--command=gcc -std=c11 -c impl.c -o /dev/null",
                 "--command=gcc -std=c11 -c user.c -o /dev/null"],
                check=True, capture_output=True)
            for q in QUERIES:
                name = q.split("/")[1]
                bqrs, out = Path(td) / f"{name}.bqrs", Path(td) / f"{name}.csv"
                subprocess.run(
                    ["codeql", "query", "run", f"--database={db}",
                     f"--output={bqrs}", str(data_root() / f"{q}.ql")],
                    check=True, capture_output=True)
                subprocess.run(
                    ["codeql", "bqrs", "decode", "--format=csv",
                     f"--output={out}", str(bqrs)],
                    check=True, capture_output=True)
                got = [r for r in _rows(out) if set(SOURCES) & set(r.values())]
                self.assertEqual(sorted(map(_key, got)),
                                 sorted(map(_key, _golden(name))), q)


class CallbackTypedefGoldenTests(unittest.TestCase):
    """What the golden tables must say, so a regenerated golden cannot
    silently drop the typedef again."""

    def _field_types(self) -> dict[str, str]:
        return {r["field_name"]: r["field_type"] for r in _golden("fields")
                if r["struct_name"] == "options"}

    def _edges(self) -> set[tuple[str, str]]:
        return {(r["field_name"], r["type_name"]) for r in _golden("field_type_uses")
                if r["struct_name"] == "options"}

    def test_a_typedefd_callback_naming_a_split_struct_keeps_its_typedef(self) -> None:
        self.assertEqual(self._field_types()["on_handle"], "handle_cb")
        self.assertIn(("on_handle", "handle_cb"), self._edges())

    def test_a_typedefd_callback_naming_no_struct_is_unchanged(self) -> None:
        self.assertEqual(self._field_types()["on_count"], "count_cb")
        self.assertIn(("on_count", "count_cb"), self._edges())

    def test_an_inline_function_pointer_still_reaches_its_signature(self) -> None:
        self.assertEqual(self._field_types()["inline_cb"], "..(*)(..)")
        self.assertIn(("inline_cb", "handle"), self._edges())

    def test_a_pointer_to_a_split_struct_names_it_as_declared(self) -> None:
        # One edge to the type as written, as a field whose struct one
        # translation unit alone sees gets.
        self.assertEqual(self._field_types()["owner"], "handle *")
        self.assertEqual({t for f, t in self._edges() if f == "owner"}, {"handle"})


if __name__ == "__main__":
    unittest.main()
