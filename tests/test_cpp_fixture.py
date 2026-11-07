"""A small C++ key-value store (`fixtures/cpp_kv`), extracted and scheduled.

The queries reproduce the golden tables for the fixture's own entities, and
the schedule orders what the type system states without data-flow: a base
before its derived classes, a template before its users, a class's
lifecycle in its node, its members after it, an override after the function
it overrides, and a free function as a consumer.

Rows that name an entity outside the fixture (the standard library, whose
spelling varies with its version) are left out of the comparison.
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

from wavefront.resources import data_root

FIXTURE = Path(__file__).parent / "fixtures" / "cpp_kv"
GOLDEN = FIXTURE / "golden"
TUS = ("src/db.cc", "src/memtable.cc", "src/misc.cc")
COMPARED = ("t1/types", "t1/functions", "t1/fields", "t1/cpp_classes", "t1/cpp_members",
            "t2/cpp_bases", "t2/cpp_overrides", "t2/cpp_slots", "t2/function_calls",
            "t2/signature_type_uses", "t2/field_type_uses")
CONFIG = {
    "closure": {"impl_files": {"included": ["src/"]},
                "api_headers": {"included": ["include/kv/"]}},
    "modules": [
        {"name": "src/misc.cc", "files": ["src/misc.cc", "include/kv/slice.h",
                                          "include/kv/status.h", "include/kv/comparator.h",
                                          "include/kv/iterator.h", "src/arena.h"]},
        {"name": "src/memtable.cc", "files": ["src/memtable.cc", "src/memtable.h",
                                              "src/skiplist.h"]},
        {"name": "src/db.cc", "files": ["src/db.cc", "src/db.h"]},
    ],
}


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _local(rows: list[dict]) -> list[tuple]:
    """The rows that name only the fixture's entities: a row with a path
    outside it, or one naming the standard library, is environment-bound."""
    keep = []
    for r in rows:
        vals = list(r.values())
        if any(v.startswith("/") for v in vals):
            continue
        if not any(v.startswith(("src/", "include/")) for v in vals):
            continue
        if any("std::" in v or "__gnu" in v for v in vals):
            continue
        keep.append(tuple(sorted(r.items())))
    return sorted(set(keep))


@unittest.skipUnless(shutil.which("codeql"), "codeql not on PATH")
class CppFixtureTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.td = tempfile.TemporaryDirectory()
        root = Path(cls.td.name)
        db, state = root / "db", root / "state"
        cmds = [f"--command=clang++ -std=c++17 -I include -I . -c {tu} -o /dev/null"
                for tu in TUS]
        subprocess.run(["codeql", "database", "create", str(db), "--language=cpp",
                        "--source-root", str(FIXTURE), *cmds],
                       check=True, capture_output=True)
        queries = sorted((data_root() / "entities").glob("*.ql")) + \
            sorted((data_root() / "edges").glob("*.ql"))
        subprocess.run(["codeql", "database", "run-queries", "--threads=0", str(db),
                        *map(str, queries)], check=True, capture_output=True)
        cls.tables = state / "codeql"
        for q in queries:
            tier = "t1" if q.parent.name == "entities" else "t2"
            bqrs = next((db / "results").rglob(f"{q.stem}.bqrs"))
            out = cls.tables / tier / f"{q.stem}.csv"
            out.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["codeql", "bqrs", "decode", "--format=csv",
                            f"--output={out}", str(bqrs)], check=True, capture_output=True)
        config = root / "wavefront-config.json"
        config.write_text(json.dumps({"state_dir": str(state), **CONFIG}))
        cls.schedule_path = root / "schedule.json"
        src = str(Path(__file__).parent.parent / "src")
        subprocess.run([sys.executable, "-m", "wavefront.cli", str(FIXTURE), "--config",
                        str(config), "schedule", "--output", str(cls.schedule_path)],
                       check=True, capture_output=True,
                       env={**os.environ, "PYTHONPATH": src})
        cls.schedule = json.loads(cls.schedule_path.read_text())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.td.cleanup()

    def test_tables_match_golden(self) -> None:
        for name in COMPARED:
            with self.subTest(table=name):
                got = _local(_rows(self.tables / f"{name}.csv"))
                want = _local(_rows(GOLDEN / f"{name.split('/')[1]}.csv"))
                self.assertEqual(got, want)

    # ------------------------------------------------------------ schedule

    def _items(self) -> dict:
        out = {}
        for w in self.schedule["waves"]:
            for b in w["batches"]:
                for it in b["items"]:
                    out[it["name"]] = (w["index"], it)
        return out

    def _before(self, a: str, b: str) -> None:
        items = self._items()
        self.assertLess(items[a][0], items[b][0], f"{a} before {b}")

    def test_bases_before_derived(self) -> None:
        self._before("kv::Iterator", "kv::EmptyIterator")
        self._before("kv::Iterator", "kv::MemTableIterator")
        self._before("kv::Comparator", "kv::BytewiseComparatorImpl")

    def test_template_before_its_users(self) -> None:
        self._before("kv::SkipList", "kv::MemTable")
        items = self._items()
        self.assertEqual(items["kv::SkipList"][1]["cpp"]["template_params"],
                         ["Key", "Comparator"])
        self.assertEqual(items["kv::SkipList<int, int>"][1]["cpp"]["specializes"]["name"],
                         "kv::SkipList")

    def test_lifecycle_in_the_class_node(self) -> None:
        items = self._items()
        status = items["kv::Status"][1]["cpp"]
        kinds = {m["member_kind"] for m in status["lifecycle"]}
        self.assertEqual(kinds, {"constructor", "copy_constructor", "move_constructor",
                                 "copy_assignment", "move_assignment", "destructor"})
        for m in status["lifecycle"]:
            self.assertNotIn(m["name"], items)
        db = items["kv::DB"][1]["cpp"]
        self.assertEqual((db["copyable"], db["movable"]), (False, True))
        self.assertEqual(db["special_members"]["copy_ctor"], "deleted")
        self.assertTrue(items["kv::Snapshot"][1]["cpp"]["trivial"])

    def test_members_implement_consumers_consume(self) -> None:
        items = self._items()
        self._before("kv::Slice", "kv::Slice::compare")
        size = items["kv::Slice::size"][1]["member"]
        self.assertEqual(size["implements"]["name"], "kv::Slice")
        self.assertEqual(size["accessor"], {"kind": "getter", "field": "size_"})
        self.assertEqual(items["kv::Status::OK"][1]["member"]["member_kind"], "factory")
        self.assertNotIn("member", items["kv::NewEmptyIterator"][1])
        self.assertNotIn("member", items["kv::CountKeys(const DB &)"][1])

    def test_override_after_overridden(self) -> None:
        self._before("kv::Iterator::Next", "kv::EmptyIterator::Next")
        self._before("kv::Comparator::Compare", "kv::BytewiseComparatorImpl::Compare")

    def test_lambda_is_its_writers_body(self) -> None:
        # `MemTable::NewIterator` calls `Unref` only inside a lambda.
        self._before("kv::MemTable::Unref", "kv::MemTable::NewIterator")

    def test_cycle_is_cut_once(self) -> None:
        # DB holds snapshots, a Snapshot points back at its DB.
        cut = self._items()["kv::DB"][1]["depends_on"]["cut"]["types"]
        self.assertEqual([c["name"] for c in cut], ["kv::Snapshot"])


if __name__ == "__main__":
    unittest.main()
