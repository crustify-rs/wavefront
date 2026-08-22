from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from crustify_oracle.query import query_dag


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
        with patch("crustify_oracle.dag.build", return_value=dag), \
                patch("crustify_oracle.query._scope_predicate",
                      return_value=lambda _node: True), \
                redirect_stdout(output):
            query_dag(Path("/tmp"), layer=0)
        expected = json.dumps({
            "types": [{"id": "alpha_st", "layer": 0,
                       "defined_in": "include/alpha.h"}],
            "functions": [{"id": "alpha_new", "layer": 0,
                           "defined_in": "src/alpha.c"}],
        }, indent=2) + "\n"
        self.assertEqual(output.getvalue(), expected)


if __name__ == "__main__":
    unittest.main()
