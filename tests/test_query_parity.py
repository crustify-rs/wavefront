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
            "types": [{"id": "alpha_st", "layer": 0,
                       "defined_in": "include/alpha.h"}],
            "functions": [{"id": "alpha_new", "layer": 0,
                           "defined_in": "src/alpha.c"}],
        }, indent=2) + "\n"
        self.assertEqual(output.getvalue(), expected)


if __name__ == "__main__":
    unittest.main()
