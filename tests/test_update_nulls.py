"""An explicit null in a submission clears what was recorded."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from wavefront import query as Q, store

PTR = {"scalar": {"by_val": True}, "array": None, "string": False,
       "owned": True, "borrowed": None, "nullable": False, "mutable": True,
       "note": "n"}
FUNC = {"name": "widget_free", "defined_in": "w.c", "kind": "function_exported",
        "type": "void (widget_st *)",
        "ptr_args": [{"position": 0, "name": "w", "type": "widget_st",
                      "const": False, "depth": 1, "ptr": None}],
        "ptr_ret": None, "lifetime": None}
GLOBAL = {"name": "widget_default", "defined_in": "w.c", "kind": "global_extern",
          "type": "widget_st *", "ptr": None, "locked_by": None}


class NullClearsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.layout = SimpleNamespace(root=self.root)

    def _submit(self, entry: dict, findings: dict) -> dict:
        src = self.root / "f.json"
        src.write_text(json.dumps(findings))
        # The validator reads the composed record merged with the store, as
        # `query` does.
        doc = store.load(self.layout)
        merged = json.loads(json.dumps(entry))
        store.overlay_sym(merged, store.index(doc)[1].get(store.sym_key(merged)))
        with mock.patch.object(Q, "_entries", return_value=[merged]), \
                redirect_stdout(io.StringIO()):
            Q._update_sym(self.layout, Path("."), entry["name"],
                          entry["defined_in"], str(src))
        return next(r for r in store.load(self.layout)["symbols"]
                    if r["name"] == entry["name"])

    def test_null_clears_lifetime_and_arg_ptr(self) -> None:
        rec = self._submit(FUNC, {
            "ptr_args": {"w": {"ptr": PTR}},
            "lifetime": {"for": "w", "is_dropper": True, "is_disposer": False,
                         "is_cloner": None, "is_constructor": None}})
        self.assertTrue(rec["lifetime"]["is_dropper"])
        self.assertEqual(rec["ptr_args"][0]["ptr"], PTR)
        rec = self._submit(FUNC, {"lifetime": None})
        self.assertNotIn("lifetime", rec)
        self.assertEqual(rec["ptr_args"][0]["ptr"], PTR)
        rec = self._submit(FUNC, {"ptr_args": {"w": {"ptr": None}}})
        self.assertNotIn("ptr_args", rec)

    def test_omitted_slot_is_kept(self) -> None:
        self._submit(FUNC, {"ptr_args": {"w": {"ptr": PTR}}})
        rec = self._submit(FUNC, {})
        self.assertEqual(rec["ptr_args"][0]["ptr"], PTR)

    def test_null_clears_a_global_ptr(self) -> None:
        blk = {**PTR, "owned": False, "borrowed": {"lifetime": "static"}}
        rec = self._submit(GLOBAL, {"ptr": blk})
        self.assertEqual(rec["ptr"], blk)
        rec = self._submit(GLOBAL, {"ptr": None})
        self.assertNotIn("ptr", rec)


if __name__ == "__main__":
    unittest.main()
