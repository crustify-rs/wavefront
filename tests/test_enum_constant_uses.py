"""A function, global or macro that names an enum's constant depends on the
enum, as one that declares a local of its type does
(`edges/enum_constant_uses.ql`, docs/graph.md#edges): `return FX_OUT_OF_MEMORY`
from a function returning `int` names no enum type, but cannot be written
before the enum. The enum lists those users in its record's `non_opaque_in`.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from compose import syms_manifest
from compose.extract_csvs import extract_t1_t2
from compose.reach import Reach
from wavefront.resources import data_root

FIXTURE = Path(__file__).parent / "fixtures" / "enum_constant_uses"
SRC = Path(__file__).resolve().parents[1] / "src"
BUILD = ("--command=gcc -std=c11 -I. -c buf.c -o /dev/null",)


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _key(r: dict) -> tuple:
    return tuple(r[k] for k in sorted(r))


GOLDEN = _rows(FIXTURE / "enum_constant_uses.csv")


def _reach() -> Reach:
    """A `Reach` holding only the golden enum-constant index."""
    reach = Reach.__new__(Reach)
    reach._build_enum_constant_indexes(FIXTURE / "enum_constant_uses.csv")
    return reach


class ReachIndexTests(unittest.TestCase):
    def test_forward_is_keyed_by_user_and_kind(self) -> None:
        reach = _reach()
        self.assertEqual(reach.enums_named_by("fx_buf_grow", "buf.c", "function"),
                         [("fx_error", "err.h")])
        self.assertEqual(reach.enums_named_by("fx_codes", "buf.c", "global"),
                         [("fx_error", "err.h")])
        self.assertEqual(reach.enums_named_by("FX_CHECK_ALLOC", "err.h", "macro"),
                         [("fx_error", "err.h")])
        self.assertEqual(reach.enums_named_by("fx_codes", "buf.c", "function"), [])

    def test_inverse_lists_every_user(self) -> None:
        self.assertEqual(_reach().users_naming_enum("fx_error", "err.h"), {
            ("fx_buf_grow", "buf.c", "function"),
            ("fx_check", "buf.c", "function"),
            ("fx_codes", "buf.c", "global"),
            ("FX_CHECK_ALLOC", "err.h", "macro"),
        })

    def test_a_typedef_named_enum_is_keyed_by_its_typedef(self) -> None:
        self.assertEqual(_reach().users_naming_enum("fx_kind", "err.h"),
                         {("fx_kind_of", "buf.c", "function")})

    def test_a_missing_table_is_empty(self) -> None:
        reach = Reach.__new__(Reach)
        reach._build_enum_constant_indexes(FIXTURE / "absent.csv")
        self.assertEqual(reach.enums_named_by("fx_buf_grow", "buf.c", "function"), [])


class DependsOnTests(unittest.TestCase):
    """The users' `depends_on.types`, over the golden table."""

    def _reach(self) -> MagicMock:
        real = _reach()
        reach = MagicMock()
        reach.types_in_signature_of.return_value = []
        reach.types_in_body_of.return_value = []
        reach.types_in_global_type.return_value = []
        reach.addr_targets_of.return_value = set()
        reach.globals_used_by.return_value = set()
        reach.all_accessors_of.return_value = set()
        reach.all_macro_call_sites.return_value = set()
        reach.all_macro_file_sites.return_value = set()
        reach.macro_references_of.return_value = []
        reach.enums_named_by.side_effect = real.enums_named_by
        return reach

    def test_a_function_returning_a_constant_through_int_depends_on_its_enum(self) -> None:
        self.assertEqual(
            syms_manifest._compose_dep_types(self._reach(), "fx_buf_grow", "buf.c", {}, None),
            [{"type": "fx_error", "fields": []}])

    def test_a_typedef_named_enum_is_its_typedef(self) -> None:
        self.assertEqual(
            syms_manifest._compose_dep_types(self._reach(), "fx_kind_of", "buf.c", {}, None),
            [{"type": "fx_kind", "fields": []}])

    def test_an_enum_the_signature_names_is_not_repeated(self) -> None:
        reach = self._reach()
        reach.types_in_signature_of.return_value = [
            ("fx_error", "enum", "err.h", "return")]
        self.assertEqual(
            syms_manifest._compose_dep_types(reach, "fx_buf_grow", "buf.c", {}, None),
            [{"type": "fx_error", "fields": []}])

    def test_a_global_initializer_depends_on_its_enum(self) -> None:
        dep = syms_manifest._port_additions_global(
            {"name": "fx_codes", "def_file": "buf.c"}, self._reach(), {}, {})["depends_on"]
        self.assertEqual(dep["types"], [{"type": "fx_error", "fields": []}])

    def test_a_macro_depends_on_the_enum_its_replacement_list_names(self) -> None:
        dep = syms_manifest._port_additions_macro(
            {"name": "FX_CHECK_ALLOC", "def_file": "err.h"}, self._reach(), {}, {})["depends_on"]
        self.assertEqual(dep, {"syms": [], "types": [{"type": "fx_error", "fields": []}]})
        # What an argument or a nested macro names is not the macro's.
        for name in ("FX_PASS", "FX_CHECK_TWICE"):
            dep = syms_manifest._port_additions_macro(
                {"name": name, "def_file": "err.h"}, self._reach(), {}, {})["depends_on"]
            self.assertEqual(dep, {"syms": [], "types": []})


@unittest.skipUnless(shutil.which("codeql") and shutil.which("gcc"),
                     "codeql or gcc not on PATH")
class EnumConstantScheduleTests(unittest.TestCase):
    """The fixture extracted, queried and scheduled end to end."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._td = tempfile.TemporaryDirectory()
        td = Path(cls._td.name)
        db = td / "db"
        subprocess.run(
            ["codeql", "database", "create", str(db), "--language=cpp",
             "--source-root", str(FIXTURE), *BUILD],
            check=True, capture_output=True)
        state = td / "state"
        _ok, failed = extract_t1_t2(db, data_root(), state / "codeql")
        assert not failed, f"{failed} queries failed"
        cls.table = [r for r in _rows(state / "codeql" / "t2" / "enum_constant_uses.csv")
                     if not any(str(v).startswith("/") for v in r.values())]
        cls.config = td / "wavefront-config.json"
        cls.config.write_text(json.dumps({
            "state_dir": str(state),
            "closure": {"impl_files": {"included": ["buf.c", "err.h"]},
                        "api_headers": {"included": ["err.h"]}}}))
        out = td / "schedule.json"
        cls._wavefront("schedule", "--output", str(out))
        cls.schedule = json.loads(out.read_text())
        cls.wave, cls.items = {}, {}
        for wave in cls.schedule["waves"]:
            for batch in wave["batches"]:
                for item in batch["items"]:
                    cls.wave[item["name"]] = wave["index"]
                    cls.items[item["name"]] = item

    @classmethod
    def _wavefront(cls, *args: str) -> str:
        env = dict(os.environ, PYTHONPATH=str(SRC), PYTHONHASHSEED="0")
        return subprocess.run(
            [sys.executable, "-m", "wavefront.cli", str(FIXTURE), "--config",
             str(cls.config), *args],
            check=True, capture_output=True, text=True, env=env).stdout

    @classmethod
    def tearDownClass(cls) -> None:
        cls._td.cleanup()

    def _deps(self, name: str) -> set[str]:
        return {d["name"] for d in self.items[name]["depends_on"]["scheduled"]}

    def test_the_table_matches_the_golden(self) -> None:
        self.assertEqual(sorted(map(_key, self.table)), sorted(map(_key, GOLDEN)))

    def test_a_function_returning_a_constant_through_int_follows_the_enum(self) -> None:
        self.assertIn("fx_error", self._deps("fx_buf_grow"))
        self.assertGreater(self.wave["fx_buf_grow"], self.wave["fx_error"])
        record = json.loads(self._wavefront("query", "functions", "--name", "fx_buf_grow"))
        self.assertIn({"type": "fx_error", "fields": []},
                      record["composed"]["depends_on"]["types"])

    def test_a_typedef_named_enum_orders_its_users(self) -> None:
        self.assertIn("fx_kind", self._deps("fx_kind_of"))
        self.assertGreater(self.wave["fx_kind_of"], self.wave["fx_kind"])

    def test_a_global_and_a_macro_follow_the_enum(self) -> None:
        self.assertIn("fx_error", self._deps("fx_codes"))
        self.assertIn("fx_error", self._deps("FX_CHECK_ALLOC"))
        # A function that expands the macro names the constant itself.
        self.assertIn("fx_error", self._deps("fx_check"))

    def test_the_enum_lists_its_users(self) -> None:
        record = json.loads(self._wavefront("query", "enums", "--name", "fx_error"))
        self.assertEqual(record["composed"]["non_opaque_in"], {
            "buf.c": ["fx_buf_grow", "fx_check", "fx_codes"],
            "err.h": ["FX_CHECK_ALLOC"],
        })
        # A local of the enum's type, no constant named: an opaque user.
        self.assertEqual(record["composed"]["opaque_in"], {"buf.c": ["fx_hold"]})
        users = self._wavefront("query", "enums", "--name", "fx_error", "--users")
        self.assertEqual(users.split(),
                         ["FX_CHECK_ALLOC", "fx_buf_grow", "fx_check", "fx_codes",
                          "fx_hold"])

    def test_an_untagged_enum_no_typedef_names_orders_nothing(self) -> None:
        self.assertNotIn("fx_error", self._deps("fx_anon"))
        self.assertEqual(self.items["fx_anon"]["depends_on"]["scheduled"], [])


if __name__ == "__main__":
    unittest.main()
