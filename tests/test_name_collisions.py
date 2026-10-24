"""A name can name several nodes: across files, and across kinds in one file
(``static const struct typelen {...} typelen[]``). Every node keeps its own
identity, and a reading query reports each one."""
from __future__ import annotations

import unittest

from wavefront.dag import ambiguous, load_nodes, select
from wavefront.schedule import _resolve, _skips


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
        keys, _ = select(["typelen"], self.by_key, self.by_name, kind="type")
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

    def test_schedule_selects_both_kinds_of_one_file(self) -> None:
        out = _resolve(["typelen"], self.by_key, self.by_name, lambda n: True)
        self.assertEqual(sorted(n.node_kind for n in out), ["symbol", "type"])

    def test_skip_by_kind(self) -> None:
        self.assertEqual(_skips(["a", "type:b", "symbol:c"]),
                         {None: {"a"}, "type": {"b"}, "symbol": {"c"}})
        with self.assertRaises(SystemExit):
            _skips(["field:x"])


if __name__ == "__main__":
    unittest.main()
