from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compose import deps_dag


class ApiSignatureGraphTests(unittest.TestCase):
    def test_body_local_empty_field_use_is_not_an_api_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            codeql = Path(td)
            (codeql / "t2").mkdir()
            with (codeql / "t2" / "signature_type_uses.csv").open(
                "w", newline=""
            ) as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "function_name", "function_def_file", "type_name",
                        "type_kind", "type_def_file", "position",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "function_name": "public_api",
                    "function_def_file": "src/api.c",
                    "type_name": "SignatureType",
                    "type_kind": "struct",
                    "type_def_file": "include/api.h",
                    "position": "param_0",
                })
            with (codeql / "t2" / "callback_signature_type_uses.csv").open(
                "w", newline=""
            ) as f:
                csv.writer(f).writerow([
                    "callback_name", "callback_def_file", "type_name",
                    "type_kind", "type_def_file", "position",
                ])

            meta = {
                ("SignatureType", "include/api.h"): {
                    "kind": "struct", "uak": "struct",
                    "decls": {"include/api.h"},
                },
                ("BodyOnly", "src/private.h"): {
                    "kind": "struct", "uak": "struct",
                    "decls": {"src/private.h"},
                },
            }
            symbol = {
                "name": "public_api",
                "kind": "function_exported",
                "defined_in": "src/api.c",
                "declared_in": ["include/api.h"],
                "depends_on": {
                    "types": [
                        {"type": "SignatureType", "fields": []},
                        {"type": "BodyOnly", "fields": []},
                    ],
                    "syms": [],
                },
                "ptr_args": [],
                "ptr_ret": None,
            }

            def entries(_root, kind):
                return [symbol] if kind == "symbols" else []

            with patch.object(
                deps_dag, "collect_types_csv",
                return_value=(meta, {}, {}, {}, {}),
            ), patch.object(deps_dag, "_entries_of", side_effect=entries):
                types, symbols, aliases = deps_dag._collect(
                    object(), port_syms=set(), port_fields={},
                    codeql_dir=codeql,
                    in_scope_types=set(meta), layout_paths=set(),
                )
                amap = deps_dag._alias_map(object(), types, aliases)
                deps_dag._build_edges(types, symbols, amap)

            self.assertEqual(
                symbols[("public_api", "src/api.c")].dep_types,
                {("SignatureType", "include/api.h")},
            )


if __name__ == "__main__":
    unittest.main()
