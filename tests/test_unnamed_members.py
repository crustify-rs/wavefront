"""C11 unnamed members (`struct { union { int a; }; }`) add no field-path
segment and name no field of their own, while named members of anonymous
type (`struct { int h; } ext;`) keep their `ext.h` paths."""
from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from wavefront.resources import data_root

FIXTURE = Path(__file__).parent / "fixtures" / "unnamed_members"
QUERIES = ("entities/fields", "edges/field_type_uses", "edges/fa_with_root")
UNNAMED = "(unknown field)"


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _golden(name: str) -> list[dict]:
    return _rows(FIXTURE / f"{name}.csv")


def _fields(struct: str) -> set[str]:
    return {r["field_name"] for r in _golden("fields") if r["struct_name"] == struct}


def _key(r: dict) -> tuple:
    return tuple(r[k] for k in sorted(r))


class UnnamedMemberQueryTests(unittest.TestCase):
    """The queries reproduce the golden tables for `members.c`."""

    @unittest.skipUnless(shutil.which("codeql"), "codeql not on PATH")
    def test_fixture_tables_match_golden(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db"
            subprocess.run(
                ["codeql", "database", "create", str(db), "--language=cpp",
                 "--source-root", str(FIXTURE),
                 "--command=gcc -std=c11 -c members.c -o /dev/null"],
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
                # Compiler builtins (`__va_list_tag`) are not the fixture's.
                got = [r for r in _rows(out) if "members.c" in r.values()]
                self.assertEqual(sorted(map(_key, got)),
                                 sorted(map(_key, _golden(name))), q)


class UnnamedMemberGoldenTests(unittest.TestCase):
    """What the golden tables must say, so a regenerated golden cannot
    silently bring the `(unknown field)` paths back."""

    def test_no_table_names_an_unnamed_member(self) -> None:
        for name in ("fields", "field_type_uses", "fa_with_root"):
            for r in _golden(name):
                self.assertNotIn(UNNAMED, " ".join(r.values()), (name, r))

    def test_unnamed_union_members_are_direct_fields(self) -> None:
        self.assertEqual(_fields("Data"), {"level", "l1", "l2"})
        self.assertEqual(_fields("Expr"), {"type", "func0", "func1"})

    def test_nested_unnamed_members_flatten_to_the_named_struct(self) -> None:
        self.assertEqual(_fields("Nest"), {"x", "y", "z"})

    def test_typedef_named_anonymous_struct_keeps_its_identity(self) -> None:
        self.assertEqual(_fields("Shape"), {"k", "p", "q"})

    def test_named_member_of_anonymous_type_keeps_its_segment(self) -> None:
        # `ext` is a real member: it stays a field and prefixes its members;
        # the unnamed union inside it adds nothing.
        self.assertEqual(_fields("Conn"),
                         {"ext", "ext.hostname", "ext.port", "ext.inner"})

    def test_plain_and_named_nested_fields_are_unchanged(self) -> None:
        self.assertEqual(_fields("Plain"), {"a", "in"})
        self.assertEqual(_fields("Inner"), {"v"})

    def test_type_edges_follow_the_flattened_names(self) -> None:
        edges = {(r["struct_name"], r["field_name"], r["type_name"])
                 for r in _golden("field_type_uses")}
        self.assertEqual(edges, {("Data", "l1", "Level1"), ("Data", "l2", "Level2"),
                                 ("Conn", "ext.inner", "Inner"),
                                 ("Plain", "in", "Inner")})

    def test_access_paths_match_declared_fields(self) -> None:
        # The declaration side (fields.ql) and the access side (fa_with_root.ql)
        # must key a flattened member identically.
        declared = {(r["struct_name"], r["field_name"]) for r in _golden("fields")}
        for r in _golden("fa_with_root"):
            self.assertIn((r["root_struct_name"], r["field_path"]), declared, r)

    def test_accesses_through_unnamed_members_resolve_to_the_named_root(self) -> None:
        paths = {(r["enclosing_name"], r["root_struct_name"], r["field_path"],
                  r["access_kind"])
                 for r in _golden("fa_with_root")}
        for row in (("use_data", "Data", "l1", "read"),
                    ("use_expr", "Expr", "func1", "read"),
                    ("use_nest", "Nest", "x", "read"),
                    ("use_conn", "Conn", "ext.port", "write"),
                    ("use_conn", "Conn", "ext.hostname", "read"),
                    ("use_shape", "Shape", "p", "write")):
            self.assertIn(row, paths)
        # The unnamed member itself is never an access of its own.
        self.assertFalse([r for r in _golden("fa_with_root") if r["field_name"] == ""])


if __name__ == "__main__":
    unittest.main()
