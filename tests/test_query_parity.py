from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from wavefront.layout import set_config_path
from wavefront.query import query_dag


class QueryParityTests(unittest.TestCase):
    def test_dag_layer_output_is_byte_stable(self) -> None:
        dag = {"layers": [[
            {"id": "alpha_st", "node_kind": "type", "subkind": "struct",
             "defined_in": "include/alpha.h", "loc": 2,
             "deps": {"types": [], "syms": []}},
            {"id": "alpha_new", "node_kind": "symbol",
             "subkind": "function_def", "defined_in": "src/alpha.c",
             "loc": 4, "deps": {"types": [], "syms": []}},
        ]]}
        output = io.StringIO()
        with TemporaryDirectory() as tmp:
            config = Path(tmp) / "wavefront-config.json"
            config.write_text(json.dumps({"state_dir": "analysis"}))
            set_config_path(config)
            try:
                with patch("wavefront.dag.build", return_value=dag), \
                        patch("wavefront.query._scope_predicate",
                              return_value=lambda _node: True), \
                        redirect_stdout(output):
                    query_dag(Path(tmp), layer=0)
            finally:
                set_config_path(None)
        expected = json.dumps({
            "functions": [{"id": "alpha_new", "kind": "function",
                           "layer": 0, "defined_in": "src/alpha.c"}],
            "structs": [{"id": "alpha_st", "kind": "struct", "layer": 0,
                         "defined_in": "include/alpha.h"}],
        }, indent=2) + "\n"
        self.assertEqual(output.getvalue(), expected)


RECORDS = {
    "types": [{"name": "num_u", "kind": "union", "defined_in": "a.h", "declared_in": ["a.h"]},
              {"name": "pair_st", "kind": "struct", "defined_in": "a.h", "declared_in": ["a.h"]},
              {"name": "tag_e", "kind": "enum", "defined_in": "a.h", "declared_in": ["a.h"]}],
    "symbols": [{"name": "pair_new", "kind": "function_static", "defined_in": "a.c",
                 "declared_in": ["a.c"]},
                {"name": "MAX", "kind": "macro", "defined_in": "a.h", "declared_in": ["a.h"]},
                {"name": "visit_fn", "kind": "callback", "defined_in": "a.h",
                 "declared_in": ["a.h"]},
                {"name": "g_count", "kind": "global_extern", "defined_in": "a.c",
                 "declared_in": ["a.c", "a.h"]},
                {"name": "off_t2", "kind": "typedef", "defined_in": None,
                 "declared_in": ["a.h"]}],
}


def _listing(**kwargs) -> list[list[str]]:
    from wavefront.query import query, query_all
    output = io.StringIO()
    with TemporaryDirectory() as tmp:
        config = Path(tmp) / "wavefront-config.json"
        config.write_text(json.dumps({"state_dir": "analysis"}))
        set_config_path(config)
        try:
            with patch("wavefront.query._entries",
                       side_effect=lambda _l, _t, kind, **_k: RECORDS[
                           "types" if kind in ("type", "types") else "symbols"]), \
                    redirect_stdout(output):
                if kwargs:
                    query(Path(tmp), **kwargs)
                else:
                    query_all(Path(tmp))
        finally:
            set_config_path(None)
    return [line.split("\t") for line in output.getvalue().splitlines()]


class KindSubjectTests(unittest.TestCase):
    """Each kind is a `query` subject of its own, and a bare `query` lists
    every kind, grouped."""

    def test_a_subject_lists_its_kind_only(self) -> None:
        self.assertEqual(_listing(subject="unions"), [["num_u", "union", "a.h", "a.h"]])
        self.assertEqual(_listing(subject="function_pointers"),
                         [["visit_fn", "function_pointer", "a.h", "a.h"]])
        self.assertEqual(_listing(subject="typedefs"), [["off_t2", "typedef", "", "a.h"]])
        self.assertEqual(_listing(subject="globals"),
                         [["g_count", "global", "a.c", "a.c,a.h"]])

    def test_a_bare_query_groups_every_kind(self) -> None:
        self.assertEqual([(r[1], r[0]) for r in _listing()], [
            ("function", "pair_new"), ("global", "g_count"), ("macro", "MAX"),
            ("struct", "pair_st"), ("union", "num_u"), ("enum", "tag_e"),
            ("function_pointer", "visit_fn"), ("typedef", "off_t2")])

if __name__ == "__main__":
    unittest.main()
