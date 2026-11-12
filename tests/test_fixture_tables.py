"""The committed fixture tables, and the check that keeps them current
(`codeql_fixtures.differences`), without CodeQL."""
from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

import codeql_fixtures as cf


class CommittedTablesTests(unittest.TestCase):
    def test_every_built_fixture_has_both_tiers(self) -> None:
        for name in cf.BUILDS:
            for tier in ("t1", "t2"):
                with self.subTest(fixture=name, tier=tier):
                    self.assertTrue(any((cf.tables(name) / tier).glob("*.csv")))

    def test_no_table_names_the_host_that_extracted_it(self) -> None:
        # System headers are absolute and stay; a temporary or home directory
        # would mean the extraction leaked where it ran.
        for name in cf.BUILDS:
            for p in sorted(cf.tables(name).glob("t*/*.csv")):
                text = p.read_text()
                with self.subTest(table=str(p.relative_to(cf.FIXTURES))):
                    self.assertNotIn("/tmp/", text)
                    self.assertNotIn("/home/", text)


class DifferencesTests(unittest.TestCase):
    NAME = "enum_constant_uses"

    def _copy(self, td: Path) -> Path:
        out = td / "codeql"
        shutil.copytree(cf.tables(self.NAME), out)
        return out

    def test_an_identical_extraction_has_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cf.differences(self.NAME, self._copy(Path(td))), [])

    def test_a_changed_fixture_row_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = self._copy(Path(td))
            table = out / "t2" / "enum_constant_uses.csv"
            body = cf.rows(table)
            body[0] = {**body[0], "use_line": "999"}
            with table.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(body[0]))
                w.writeheader()
                w.writerows(body)
            self.assertEqual(cf.differences(self.NAME, out),
                             ["t2/enum_constant_uses.csv"])

    def test_a_host_row_is_not_compared(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = self._copy(Path(td))
            table = out / "t1" / "types.csv"
            body = cf.rows(table)
            host = next(r for r in body if any(str(v).startswith("/") for v in r.values()))
            body.remove(host)
            with table.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(host))
                w.writeheader()
                w.writerows(body)
            self.assertEqual(cf.differences(self.NAME, out), [])

    def test_a_table_only_one_side_has_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = self._copy(Path(td))
            (out / "t2" / "casts.csv").unlink()
            (out / "t2" / "new_table.csv").write_text("a\n")
            self.assertEqual(cf.differences(self.NAME, out),
                             ["t2/casts.csv: only committed",
                              "t2/new_table.csv: only extracted"])


if __name__ == "__main__":
    unittest.main()
