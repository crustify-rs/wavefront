from __future__ import annotations

import unittest
from unittest.mock import patch

from crustify_oracle.dag import Node
from crustify_oracle.schedule import Unit, _field_anchors, _pack, build_campaign


def _node(name: str, *, kind: str = "symbol", home: str = "src/a.c",
          loc: int = 0) -> Node:
    return Node(
        id=name,
        node_kind=kind,
        subkind="struct" if kind == "type" else "function_def",
        defined_in=home,
        layer=0,
        dep_types=[],
        dep_syms=[],
        loc=loc,
    )


class SchedulePackingParityTests(unittest.TestCase):
    def test_api_field_anchors_keep_only_public_definitions(self) -> None:
        inventory = {
            "api": {"files": ["include/public.h"]},
            "targeted": {},
            "imported": {},
        }
        entries = [{
            "name": "opaque_st",
            "defined_in": "src/private.c",
            "fields": [{"name": "private_field"}],
        }, {
            "name": "visible_st",
            "defined_in": "include/public.h",
            "fields": [{"name": "public_field"}],
        }, {
            "name": "collision_st",
            "defined_in": "src/one.c",
            "fields": [{"name": "private_collision"}],
        }, {
            "name": "collision_st",
            "defined_in": "include/public.h",
            "fields": [{"name": "public_collision"}],
        }]

        with patch("crustify_oracle.scope.build", return_value=inventory), \
                patch("crustify_oracle.manifests.entries",
                      return_value=entries):
            anchors = _field_anchors(
                object(), None, api_headers_only=True)

        self.assertEqual(anchors[("opaque_st", "src/private.c")], [])
        self.assertEqual(
            anchors[("visible_st", "include/public.h")],
            ["public_field"],
        )
        self.assertEqual(anchors[("collision_st", "src/one.c")], [])
        self.assertEqual(
            anchors[("collision_st", "include/public.h")],
            ["public_collision"],
        )

    def test_old_batch_boundaries_are_preserved(self) -> None:
        units = [
            Unit(_node("opaque_a", kind="type", home="include/a.h"), []),
            Unit(_node("opaque_b", kind="type", home="include/b.h"), []),
            Unit(_node("wide", kind="type", home="include/wide.h"),
                 ["x", "y", "z"]),
            Unit(_node("target_a", loc=4), scope="targeted"),
            Unit(_node("target_b", loc=7), scope="targeted"),
            Unit(_node("import_a", home="dep/a.c", loc=1), scope="imported"),
        ]

        batches = _pack(
            units, max_syms=2, max_loc=10, max_types=2, min_fields=3)

        self.assertEqual(
            [[unit.node.id for unit in batch.units] for batch in batches],
            [
                ["opaque_a", "opaque_b"],
                ["wide"],
                ["target_a"],
                ["target_b"],
                ["import_a"],
            ],
        )
        self.assertEqual(
            [batch.file for batch in batches],
            ["include/a.h", "include/wide.h", None, None, None],
        )

    def test_api_surface_is_the_seed_not_the_dependency_filter(self) -> None:
        dependency = _node("private_dep", home="src/private.c", loc=3)
        public = _node("public_api", home="src/public.c", loc=4)
        public.layer = 1
        macro = _node("PUBLIC_MACRO", home="include/public.h")
        macro.subkind = "macro_function"
        public.dep_syms = [dependency.key, macro.key]
        graph = {
            "layers": [
                [{
                    "id": dependency.id, "node_kind": dependency.node_kind,
                    "subkind": dependency.subkind,
                    "defined_in": dependency.defined_in, "loc": dependency.loc,
                    "deps": {"types": [], "syms": []},
                }, {
                    "id": macro.id, "node_kind": macro.node_kind,
                    "subkind": macro.subkind,
                    "defined_in": macro.defined_in, "loc": macro.loc,
                    "deps": {"types": [], "syms": []},
                }],
                [{
                    "id": public.id, "node_kind": public.node_kind,
                    "subkind": public.subkind,
                    "defined_in": public.defined_in, "loc": public.loc,
                    "deps": {"types": [], "syms": [{
                        "name": dependency.id,
                        "defined_in": dependency.defined_in,
                    }, {
                        "name": macro.id,
                        "defined_in": macro.defined_in,
                    }]},
                }],
            ],
        }
        inventory = {
            "targeted": {
                "files": ["src/private.c", "src/public.c"],
                "functions": [
                    {"name": dependency.id,
                     "defined_in": dependency.defined_in},
                    {"name": public.id, "defined_in": public.defined_in},
                ],
                "globals": [], "macros": [], "types": [],
            },
            "imported": {
                "files": [], "functions": [], "globals": [],
                "macros": [], "types": [],
            },
            "api": {
                "files": ["include/public.h"],
                "functions": [
                    {"name": public.id, "defined_in": public.defined_in},
                ],
                "globals": [], "macros": [], "types": [],
            },
        }

        class Layout:
            @staticmethod
            def rel_target(_target):
                return "."

        with patch("crustify_oracle.scope.build", return_value=inventory), \
                patch("crustify_oracle.dag.build", return_value=graph), \
                patch("crustify_oracle.manifests.entries", return_value=[]), \
                patch("crustify_oracle.schedule._field_anchors",
                      return_value={}):
            campaign = build_campaign(
                Layout(), None, names=[public.id], transitive=True,
                api_headers_only=True, max_syms=50, max_loc=1000,
                max_types=5, min_fields=10,
            )

        self.assertEqual(
            [item["name"] for item in campaign["plan_items"]],
            [dependency.id, public.id],
        )
        dependencies = {
            item["name"]: item["in_scope"]
            for item in campaign["dependency_nodes"]
        }
        self.assertEqual(
            dependencies,
            {macro.id: False},
        )


if __name__ == "__main__":
    unittest.main()
