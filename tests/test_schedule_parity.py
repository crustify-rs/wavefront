from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from crustify_oracle.dag import Node
from crustify_oracle.schedule import (
    Unit, _field_anchors, _pack, _resolve, build_raw_lifetime_wave, build_wave,
    write_wave,
)


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
    def test_write_wave_requires_an_existing_output_directory(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "missing" / "wave.json"
            with self.assertRaisesRegex(
                    SystemExit, "output directory does not exist"):
                write_wave(output, {"schema_version": 2, "steps": []})
            self.assertFalse(output.parent.exists())

    def test_write_wave_uses_an_orchestrator_scaffolded_directory(self) -> None:
        with TemporaryDirectory() as directory:
            campaign_dir = Path(directory) / "campaigns"
            campaign_dir.mkdir()
            output = campaign_dir / "wave.json"
            wave = {"schema_version": 2, "steps": []}
            write_wave(output, wave)
            self.assertEqual(output.read_text(),
                             '{\n  "schema_version": 2,\n  "steps": []\n}\n')

    def test_raw_lifetime_wave_uses_v2_steps(self) -> None:
        class Layout:
            @staticmethod
            def rel_target(_target):
                return "."

        wave = build_raw_lifetime_wave(Layout(), None, "void")
        self.assertEqual(wave["schema_version"], 2)
        self.assertEqual(wave["steps"][0]["batches"][0]["kind"],
                         "raw-lifetime")
        self.assertNotIn("waves", wave)

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
            wave = build_wave(
                Layout(), None, names=[public.id], transitive=True,
                api_headers_only=True, max_syms=50, max_loc=1000,
                max_types=5, min_fields=10,
            )

        self.assertEqual(wave["schema_version"], 2)
        self.assertIn("steps", wave)
        self.assertNotIn("waves", wave)
        self.assertEqual(
            [item["name"] for item in wave["plan_items"]],
            [dependency.id, public.id],
        )
        dependencies = {
            item["name"]: item["in_scope"]
            for item in wave["dependency_nodes"]
        }
        self.assertEqual(
            dependencies,
            {macro.id: False},
        )

    def test_file_surface_is_the_seed_not_the_dependency_filter(self) -> None:
        dependency = _node("shared_dependency", home="src/shared.c", loc=3)
        selected = _node("selected_function", home="src/selected.c", loc=4)
        selected.layer = 1
        selected.dep_syms = [dependency.key]
        graph = {
            "layers": [
                [{
                    "id": dependency.id, "node_kind": dependency.node_kind,
                    "subkind": dependency.subkind,
                    "defined_in": dependency.defined_in, "loc": dependency.loc,
                    "deps": {"types": [], "syms": []},
                }],
                [{
                    "id": selected.id, "node_kind": selected.node_kind,
                    "subkind": selected.subkind,
                    "defined_in": selected.defined_in, "loc": selected.loc,
                    "deps": {"types": [], "syms": [{
                        "name": dependency.id,
                        "defined_in": dependency.defined_in,
                    }]},
                }],
            ],
        }
        inventory = {
            "targeted": {
                "files": ["src/shared.c", "src/selected.c"],
                "functions": [
                    {"name": dependency.id,
                     "defined_in": dependency.defined_in},
                    {"name": selected.id, "defined_in": selected.defined_in},
                ],
                "globals": [], "macros": [], "types": [],
            },
            "imported": {
                "files": [], "functions": [], "globals": [],
                "macros": [], "types": [],
            },
            "api": {
                "files": [], "functions": [], "globals": [],
                "macros": [], "types": [],
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
            wave = build_wave(
                Layout(), None, names=None, files=[selected.defined_in],
                transitive=True, max_syms=50, max_loc=1000,
                max_types=5, min_fields=10,
            )

        self.assertCountEqual(
            [item["name"] for item in wave["plan_items"]],
            [dependency.id, selected.id],
        )

    def test_file_surface_keeps_same_named_nodes_distinct(self) -> None:
        first = _node("command", home="src/first.c", loc=3)
        second = _node("command", home="src/second.c", loc=4)
        graph = {
            "layers": [[{
                "id": node.id, "node_kind": node.node_kind,
                "subkind": node.subkind, "defined_in": node.defined_in,
                "loc": node.loc, "deps": {"types": [], "syms": []},
            } for node in (first, second)]],
        }
        inventory = {
            "targeted": {
                "files": [first.defined_in, second.defined_in],
                "functions": [
                    {"name": first.id, "defined_in": first.defined_in},
                    {"name": second.id, "defined_in": second.defined_in},
                ],
                "globals": [], "macros": [], "types": [],
            },
            "imported": {
                "files": [], "functions": [], "globals": [],
                "macros": [], "types": [],
            },
            "api": {
                "files": [], "functions": [], "globals": [],
                "macros": [], "types": [],
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
            wave = build_wave(
                Layout(), None, names=None,
                files=[first.defined_in, second.defined_in],
                max_syms=50, max_loc=1000, max_types=5, min_fields=10,
            )

        self.assertEqual(len(wave["plan_items"]), 2)


if __name__ == "__main__":
    unittest.main()


class ResolveTwinTests(unittest.TestCase):
    """A closure name must resolve to the node the walk reached.

    `ossl_provider_st` is defined both by the library and by
    `test/property_test.c`. Both pass scope, so resolving the closure by bare
    name used to schedule the test double as if it were the library struct.
    """

    def _pair(self):
        real = _node("ossl_provider_st", kind="type",
                     home="crypto/provider_core.c")
        twin = _node("ossl_provider_st", kind="type",
                     home="test/property_test.c")
        by_key = {real.key: real, twin.key: twin}
        by_name = {"ossl_provider_st": [real.key, twin.key]}
        return real, twin, by_key, by_name

    def test_prefer_keys_narrows_to_the_walked_node(self) -> None:
        real, twin, by_key, by_name = self._pair()
        out = _resolve(["ossl_provider_st"], by_key, by_name, lambda n: True,
                       require_unambiguous=False,
                       prefer_keys={real.key})
        self.assertEqual([n.defined_in for n in out], ["crypto/provider_core.c"])
        self.assertNotIn(twin.key, {n.key for n in out})

    def test_without_prefer_keys_both_twins_survive(self) -> None:
        _real, _twin, by_key, by_name = self._pair()
        out = _resolve(["ossl_provider_st"], by_key, by_name, lambda n: True,
                       require_unambiguous=False)
        self.assertEqual(len(out), 2)

    def test_prefer_keys_is_ignored_when_the_walk_reached_neither(self) -> None:
        # An unrelated preference must not silently empty the selection.
        _real, _twin, by_key, by_name = self._pair()
        out = _resolve(["ossl_provider_st"], by_key, by_name, lambda n: True,
                       require_unambiguous=False,
                       prefer_keys={("something_else", "x.c")})
        self.assertEqual(len(out), 2)

