from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from wavefront.dag import Node
from wavefront.schedule import (
    Unit, _coalesce, _used_fields, _pack, build_schedule, write_wave,
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


class _Layout:
    """A layout over an empty state dir, whose config is written to a
    temporary file."""

    def __init__(self, directory: Path, config: dict | None = None) -> None:
        self.repo_root = directory
        self.root = directory
        self.t1 = directory / "t1"
        self.t2 = directory / "t2"
        self._config = directory / "wavefront-config.json"
        self._config.write_text(json.dumps(config or {}))

    def config(self, _target=None) -> Path:
        return self._config

    @staticmethod
    def config_provenance():
        return {"path": "wavefront-config.json", "sha256": "0" * 64}


def _whole(inventory: dict) -> dict:
    """A config whose closure is the inventory's files, scheduling all."""
    files = sorted({e["defined_in"] for bucket in ("functions", "globals", "types")
                    for e in inventory["closure"].get(bucket, [])})
    return {"closure": {"impl_files": {"included": files}}}


def _schedule(graph: dict, inventory: dict, *, config: dict | None = None,
              **kwargs) -> dict:
    config = config or _whole(inventory)
    with TemporaryDirectory() as directory, \
            patch("wavefront.scope.build", return_value=inventory), \
            patch("wavefront.dag.build", return_value=graph), \
            patch("wavefront.manifests.entries", return_value=[]), \
            patch("wavefront.schedule._used_fields", return_value={}):
        return build_schedule(_Layout(Path(directory), config), None, **kwargs)


def _scheduled_items(schedule: dict) -> list[dict]:
    return [
        item
        for scheduled_wave in schedule["waves"]
        for batch in scheduled_wave["batches"]
        for item in batch["items"]
    ]


class SchedulePackingParityTests(unittest.TestCase):
    def test_adjacent_layers_fold_independently_of_closure_selection(self) -> None:
        producer = _node("producer")
        consumer = _node("consumer")
        consumer.layer = 1
        by_layer = {
            0: [Unit(producer, scope="closure")],
            1: [Unit(consumer, scope="closure")],
        }
        budgets = {
            "max_syms": 2, "max_loc": 1000,
            "max_types": 2, "min_fields": 20,
        }

        self.assertEqual(_coalesce(by_layer, [0, 1], budgets=budgets), [[0, 1]])

        budgets["max_syms"] = 1
        self.assertEqual(_coalesce(by_layer, [0, 1], budgets=budgets), [[0], [1]])

    def test_documented_schedule_example_is_structurally_consistent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        schedule = json.loads((root / "examples" / "schedule.json").read_text())

        self.assertEqual(schedule["schema_version"], 5)
        items = _scheduled_items(schedule)
        waves = schedule["waves"]
        summary = schedule["summary"]
        self.assertEqual(summary["unit_count"], len(items))
        self.assertEqual(summary["wave_count"], len(waves))
        self.assertEqual(summary["batch_count"],
                         sum(len(wave["batches"]) for wave in waves))
        self.assertEqual(summary["module_count"], len(schedule["modules"]))
        for index, wave in enumerate(waves):
            self.assertEqual(wave["index"], index)
            self.assertEqual(wave["unit_count"], sum(
                len(batch["items"]) for batch in wave["batches"]))
            self.assertIn("sublayer" if wave["module"] else "layer", wave)
            for dep in wave["depends_on"]["scheduled"]:
                self.assertLess(dep, index)
            for dep in wave["depends_on"]["cut"]:
                self.assertGreater(dep, index)
            for item in (i for b in wave["batches"] for i in b["items"]):
                self.assertEqual(item["module"], wave["module"])
        for module in schedule["modules"]:
            for index in module["waves"]:
                self.assertEqual(waves[index]["module"], module["name"])
        keys = {"name", "defined_in", "declared_in", "kind", "source_kind",
                "seeded", "module", "loc", "stats", "depends_on", "depended_on_by",
                "type_generator_for", "used_fields", "opaque_after",
                "unmanaged_after", "unreferenced_after"}
        for item in items:
            self.assertEqual(set(item), keys)

    def test_write_wave_requires_an_existing_output_directory(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "missing" / "wave.json"
            with self.assertRaisesRegex(
                    SystemExit, "output directory does not exist"):
                write_wave(output, {"schema_version": 3, "waves": []})
            self.assertFalse(output.parent.exists())

    def test_write_wave_uses_an_orchestrator_scaffolded_directory(self) -> None:
        with TemporaryDirectory() as directory:
            campaign_dir = Path(directory) / "campaigns"
            campaign_dir.mkdir()
            output = campaign_dir / "wave.json"
            wave = {"schema_version": 3, "waves": []}
            write_wave(output, wave)
            self.assertEqual(output.read_text(),
                             '{\n  "schema_version": 3,\n  "waves": []\n}\n')

    def test_api_used_fields_keep_only_public_definitions(self) -> None:
        inventory = {
            "api": {"files": ["include/public.h"]},
            "closure": {},
            "external": {},
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

        with patch("wavefront.scope.build", return_value=inventory), \
                patch("wavefront.manifests.entries",
                      return_value=entries):
            used = _used_fields(
                object(), None, api_headers_only=True)

        self.assertEqual(used[("opaque_st", "src/private.c", "type")], [])
        self.assertEqual(
            used[("visible_st", "include/public.h", "type")],
            ["public_field"],
        )
        self.assertEqual(used[("collision_st", "src/one.c", "type")], [])
        self.assertEqual(
            used[("collision_st", "include/public.h", "type")],
            ["public_collision"],
        )

    def test_old_batch_boundaries_are_preserved(self) -> None:
        units = [
            Unit(_node("opaque_a", kind="type", home="include/a.h"), []),
            Unit(_node("opaque_b", kind="type", home="include/b.h"), []),
            Unit(_node("wide", kind="type", home="include/wide.h"),
                 ["x", "y", "z"]),
            Unit(_node("target_a", loc=4), scope="closure"),
            Unit(_node("target_b", loc=7), scope="closure"),
            Unit(_node("import_a", home="dep/a.c", loc=1), scope="external"),
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
            "closure": {
                "files": ["src/private.c", "src/public.c"],
                "functions": [
                    {"name": dependency.id,
                     "defined_in": dependency.defined_in},
                    {"name": public.id, "defined_in": public.defined_in},
                ],
                "globals": [], "macros": [], "types": [],
            },
            "external": {
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

        wave = _schedule(graph, inventory, api_headers_only=True)

        self.assertEqual(wave["schema_version"], 5)
        self.assertEqual([w["layer"] for w in wave["waves"]], [0, 1])
        self.assertEqual(
            [item["name"] for item in _scheduled_items(wave)],
            [dependency.id, public.id],
        )
        folded = _schedule(graph, inventory, api_headers_only=True,
                           caps={"max_syms": 50})
        self.assertEqual([w["layer"] for w in folded["waves"]], [0, 1])
        public_item = next(
            item for item in _scheduled_items(wave) if item["name"] == public.id
        )
        dependencies = {
            item["name"]: item["scope"]
            for item in public_item["depends_on"]["scheduled"]["symbols"]
            if item["name"] == macro.id
        }
        self.assertEqual(
            dependencies,
            {macro.id: "external"},
        )

    def test_external_items_are_left_to_their_owner(self) -> None:
        # The public Holder (this config's api_headers) reaches the external
        # Option (another library's). Either schedule holds Holder alone, and
        # Holder still lists Option among its deps, outside the closure.
        option = {"id": "Option", "node_kind": "type", "subkind": "struct",
                  "defined_in": "include/opt.h", "loc": 0,
                  "deps": {"types": [], "syms": []}}
        holder = {"id": "Holder", "node_kind": "type", "subkind": "struct",
                  "defined_in": "include/holder.h", "loc": 0,
                  "deps": {"types": [{"name": "Option",
                                      "defined_in": "include/opt.h"}],
                           "syms": []}}
        graph = {"layers": [[option], [holder]]}
        none = {"files": [], "functions": [], "globals": [], "macros": [], "types": []}
        inventory = {
            "closure": {**none, "files": ["include/holder.h"], "types": [
                {"name": "Holder", "defined_in": "include/holder.h"}]},
            "external": {**none, "files": ["include/opt.h"], "types": [
                {"name": "Option", "defined_in": "include/opt.h"}]},
            "api": {**none, "files": ["include/holder.h"], "types": [
                {"name": "Holder", "defined_in": "include/holder.h"}]},
        }

        for api in (True, False):
            items = _scheduled_items(
                _schedule(graph, inventory, api_headers_only=api))
            self.assertEqual([item["name"] for item in items], ["Holder"])
            self.assertEqual(items[0]["depends_on"]["scheduled"]["types"], [
                {"name": "Option", "defined_in": "include/opt.h",
                 "scope": "external"}])


if __name__ == "__main__":
    unittest.main()
