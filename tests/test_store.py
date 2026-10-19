from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from wavefront import store


class StoreLoadTests(unittest.TestCase):
    def test_legacy_comment_key_is_read_as_comment_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ownership-store.json").write_text(json.dumps({
                "types": [{"name": "widget_st", "defined_in": "w.h",
                           "_comment_agent": "type note",
                           "fields": [{"name": "buf", "_comment_agent": "field note"}]}],
                "symbols": [{"name": "widget_new", "defined_in": "w.c",
                             "_comment_agent": "symbol note"}],
            }))
            doc = store.load(SimpleNamespace(root=root))
        rec = doc["types"][0]
        self.assertEqual(rec["_comment_user"], "type note")
        self.assertEqual(rec["fields"][0]["_comment_user"], "field note")
        self.assertEqual(doc["symbols"][0]["_comment_user"], "symbol note")
        self.assertNotIn("_comment_agent", json.dumps(doc))


if __name__ == "__main__":
    unittest.main()
