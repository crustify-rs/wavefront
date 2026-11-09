"""A name can name several nodes: across files, and across kinds in one file
(``static const struct typelen {...} typelen[]``). Every node keeps its own
identity, and a reading query reports each one."""
from __future__ import annotations

import unittest

import contextlib
import io
import tempfile
from pathlib import Path

from compose import deps_dag
from test_t3 import TYPE_COLS, _type, _write
from wavefront.dag import ambiguous, load_nodes, select


def _rec(name, kind, home, *, types=(), syms=()):
    return {"id": name, "node_kind": kind,
            "subkind": "struct" if kind == "type" else "global_static",
            "defined_in": home,
            "deps": {"types": [{"name": n, "defined_in": h} for n, h in types],
                     "syms": [{"name": n, "defined_in": h} for n, h in syms]}}


DAG = {"layers": [
    [_rec("typelen", "type", "src/date.c"),
     _rec("set_error", "symbol", "src/tree.c"),
     _rec("set_error", "symbol", "src/errors.c")],
    [_rec("typelen", "symbol", "src/date.c", types=[("typelen", "src/date.c")])],
    [_rec("match", "symbol", "src/date.c",
          types=[("typelen", "src/date.c")], syms=[("typelen", "src/date.c")])],
]}


class NameCollisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.by_key, self.by_name = load_nodes(DAG)

    def test_a_type_and_a_symbol_of_one_name_and_file_are_two_nodes(self) -> None:
        self.assertIn(("typelen", "src/date.c", "type"), self.by_key)
        self.assertIn(("typelen", "src/date.c", "symbol"), self.by_key)

    def test_dependencies_resolve_to_their_own_kind(self) -> None:
        match = self.by_key[("match", "src/date.c", "symbol")]
        self.assertEqual(match.dep_types, [("typelen", "src/date.c", "type")])
        self.assertEqual(match.dep_syms, [("typelen", "src/date.c", "symbol")])

    def test_select_returns_every_match_and_narrows_by_file_and_kind(self) -> None:
        keys, unknown = select(["typelen", "set_error", "nope"],
                               self.by_key, self.by_name)
        self.assertEqual(len(keys), 4)
        self.assertEqual(unknown, ["nope"])
        keys, _ = select(["typelen"], self.by_key, self.by_name, kind="struct")
        self.assertEqual(keys, [("typelen", "src/date.c", "type")])
        keys, _ = select(["set_error"], self.by_key, self.by_name,
                         files={"src/errors.c"})
        self.assertEqual(keys, [("set_error", "src/errors.c", "symbol")])

    def test_only_nodes_in_different_files_are_ambiguous(self) -> None:
        keys, _ = select(["typelen"], self.by_key, self.by_name)
        ambiguous(keys, stage="t")
        keys, _ = select(["set_error"], self.by_key, self.by_name)
        with self.assertRaises(SystemExit) as cm:
            ambiguous(keys, stage="t")
        self.assertIn("src/tree.c", str(cm.exception))


class ForwardDeclarationTests(unittest.TestCase):
    """A forward declaration names no definition in C: each unit that
    includes it sees whichever one it includes. Folding it into a tag with
    several definitions is a guess, so it is reported."""

    def _meta(self, types: list[dict]) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as td:
            codeql = Path(td) / "codeql"
            _write(codeql / "t1" / "types.csv", TYPE_COLS, types)
            for name, cols in (("casts.csv", ["from_tag", "to_tag"]),
                               ("field_type_uses.csv",
                                ["struct_name", "struct_def_file", "field_name",
                                 "type_name", "type_kind", "type_def_file"])):
                _write(codeql / "t2" / name, cols, [])
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                meta = deps_dag.collect_types_csv(codeql)[0]
            return meta, err.getvalue()

    def test_a_forward_declaration_of_one_definition_folds_silently(self) -> None:
        meta, err = self._meta([_type("repo", "src/repo.h"),
                                _type("repo", "", "include/types.h")])
        self.assertEqual(meta[("repo", "src/repo.h")]["decls"],
                         {"src/repo.h", "include/types.h"})
        self.assertEqual(err, "")

    def test_a_forward_declaration_of_several_definitions_warns(self) -> None:
        meta, err = self._meta([_type("entry", "a.c"), _type("entry", "b.c"),
                                _type("entry", "", "include/entry.h")])
        self.assertIn("include/entry.h", meta[("entry", "a.c")]["decls"])
        self.assertIn("include/entry.h", meta[("entry", "b.c")]["decls"])
        self.assertIn("forward declaration of `entry` (include/entry.h)", err)
        self.assertIn("2 definitions (a.c, b.c)", err)


if __name__ == "__main__":
    unittest.main()
