from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from compose import syms_manifest
from compose.filter_spec import FilterSpec


def _write(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


class PublishedCallbackTests(unittest.TestCase):
    """A callback the target's own API header publishes gets a record even when
    no target body reaches it -- e.g. it is invoked only by another subsystem."""

    def _compose(self, targeted_functions: list[dict], *, names: list[str] | None = None):
        with tempfile.TemporaryDirectory() as td:
            t1 = Path(td) / "t1"
            t1.mkdir()
            fn_header = ["name", "kind", "def_file", "decl_files", "linkage"]
            _write(t1 / "functions.csv", fn_header, [])
            _write(t1 / "globals.csv", fn_header, [])
            _write(t1 / "macros.csv", ["name", "def_file", "decl_files"], [])
            _write(t1 / "types.csv",
                   ["name", "kind", "def_file", "decl_files", "aliases", "unaliased_kind"],
                   [{"name": "pub_cb", "kind": "typedef", "def_file": "",
                     "decl_files": "include/pub.h", "aliases": "",
                     "unaliased_kind": "callback"}])
            scope_doc = {
                "targeted": {"files": ["include/pub.h", "src/pub.c"],
                             "functions": targeted_functions, "globals": [],
                             "macros": [], "types": []},
                "imported": {"files": [], "functions": [], "globals": [],
                             "macros": [], "types": []},
            }
            spec = FilterSpec(scope_json_path=scope_doc, names=names or [])
            reach = MagicMock()
            reach.callback_callsites_of.return_value = set()
            reach.callback_sig_types_of.return_value = []
            reach.callbacks_invoked_by.return_value = set()
            with patch.object(syms_manifest, "Reach", return_value=reach), \
                    patch("compose.types_manifest._import_reachable", return_value=False):
                entries, _scope, _ = syms_manifest.compose(t1, Path(td) / "t2", spec)
        return [e["name"] for v in entries.values() for e in v]

    def test_targeted_callback_emitted_without_body_reach(self) -> None:
        cb = {"name": "pub_cb", "defined_in": "", "declared_in": ["include/pub.h"]}
        self.assertIn("pub_cb", self._compose([cb]))

    def test_targeted_callback_admitted_as_named_seed(self) -> None:
        cb = {"name": "pub_cb", "defined_in": "", "declared_in": ["include/pub.h"]}
        self.assertIn("pub_cb", self._compose([cb], names=["pub_cb"]))

    def test_unpublished_unreached_callback_still_dropped(self) -> None:
        self.assertNotIn("pub_cb", self._compose([]))


if __name__ == "__main__":
    unittest.main()
