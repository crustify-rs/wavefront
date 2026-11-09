"""A union is a union: `cpp-all` makes `Union` a subclass of `Struct`, so a
query that tests `instanceof Struct` first classified every union as a struct,
and `types.csv` had no union at all. Every query that classifies a type tests
`Union` first (`identity.qll`'s `userTypeKind`)."""
from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from wavefront.resources import data_root

FIXTURE = Path(__file__).parent / "fixtures" / "union_kinds"

#: Each query, the column naming its type, and the column classifying it.
QUERIES = {
    "entities/types": ("name", "kind"),
    "edges/field_type_uses": ("type_name", "type_kind"),
    "edges/global_type_uses": ("type_name", "type_kind"),
    "edges/local_type_uses": ("type_name", "type_kind"),
    "edges/signature_type_uses": ("type_name", "type_kind"),
    "edges/callback_signature_type_uses": ("type_name", "type_kind"),
}
KINDS = {"Num": "union", "Pair": "struct", "Tag": "enum"}


def _run(db: Path, query: str, out: Path) -> list[dict]:
    bqrs = out.with_suffix(".bqrs")
    subprocess.run(["codeql", "query", "run", f"--database={db}",
                    f"--output={bqrs}", str(data_root() / f"{query}.ql")],
                   check=True, capture_output=True)
    subprocess.run(["codeql", "bqrs", "decode", "--format=csv",
                    f"--output={out}", str(bqrs)], check=True, capture_output=True)
    with out.open(newline="") as f:
        return list(csv.DictReader(f))


@unittest.skipUnless(shutil.which("codeql"), "codeql not on PATH")
class UnionKindQueryTests(unittest.TestCase):
    tables: dict[str, list[dict]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls._td = tempfile.TemporaryDirectory()
        td = Path(cls._td.name)
        db = td / "db"
        subprocess.run(
            ["codeql", "database", "create", str(db), "--language=cpp",
             "--source-root", str(FIXTURE),
             "--command=gcc -std=c11 -c kinds.c -o /dev/null"],
            check=True, capture_output=True)
        cls.tables = {q: _run(db, q, td / f"{q.replace('/', '_')}.csv")
                      for q in QUERIES}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._td.cleanup()

    def test_every_query_tells_a_union_from_a_struct(self) -> None:
        for query, (name_col, kind_col) in QUERIES.items():
            rows = self.tables[query]
            for name, kind in KINDS.items():
                with self.subTest(query=query, type=name):
                    got = {r[kind_col] for r in rows if r[name_col] == name}
                    self.assertEqual(got, {kind})

    def test_a_typedef_named_union_is_union_anonymous(self) -> None:
        word = [r for r in self.tables["entities/types"] if r["name"] == "Word"]
        self.assertEqual({(r["kind"], r["unaliased_kind"]) for r in word},
                         {("typedef", "union_anonymous")})


if __name__ == "__main__":
    unittest.main()
