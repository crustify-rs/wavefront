"""The findings shape: the example a user copies, and the record split."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from wavefront import findings, query as Q

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "findings.json"


def _example() -> dict:
    return json.loads(EXAMPLE.read_text())


class ExampleTests(unittest.TestCase):
    """`examples/findings.json` stays within, and covers, what --update takes."""

    def test_type_keys(self) -> None:
        seen_top, seen_field = set(), set()
        for doc in _example()["types"].values():
            seen_top |= set(doc)
            for fa in doc["fields"].values():
                seen_field |= set(fa)
        self.assertEqual(seen_top, Q._FINDINGS_TOP)
        self.assertEqual(seen_field, set(Q._FIELD_AGENT_KEYS))

    def test_symbol_keys(self) -> None:
        seen_top, seen_fork, seen_ptr = set(), set(), set()
        for doc in _example()["symbols"].values():
            seen_top |= set(doc)
            for fk in doc.get("forks") or []:
                seen_fork |= set(fk)
            blocks = [a["ptr"] for a in (doc.get("ptr_args") or {}).values()]
            blocks += [doc[k]["ptr"] for k in ("ptr_ret",) if k in doc]
            blocks += [doc["ptr"]] if doc.get("ptr") else []
            for b in blocks:
                seen_ptr |= set(b)
        self.assertEqual(seen_top, Q._SYM_FINDINGS_TOP)
        self.assertLessEqual(seen_fork, Q._FORK_KEYS)
        self.assertEqual(seen_ptr, Q._PTR_AGENT_KEYS)

    def test_blocks_pass_the_validator_rules(self) -> None:
        ex = _example()
        for tname, doc in ex["types"].items():
            for fname, fa in doc["fields"].items():
                if "ptr" in fa:
                    self.assertEqual(Q._ptr_invariant_errors(fname, fa["ptr"], "uint8_t *"), [])
                if fa.get("locked_by"):
                    self.assertEqual(Q._locked_by_errors(fname, fa["locked_by"]), [])
        new = ex["symbols"]["widget_new"]
        args = {n: a["ptr"] for n, a in new["ptr_args"].items()}
        for n, b in args.items():
            self.assertEqual(Q._sym_ptr_invariant_errors(
                n, b, True, is_ret=False, arg_names=set(args)), [])
        self.assertEqual(Q._sym_ptr_invariant_errors(
            "ret", new["ptr_ret"]["ptr"], False, is_ret=True, arg_names=set(args)), [])
        self.assertEqual(Q._lifetime_errors(
            "lifetime", new["lifetime"], args, ret_ptr=new["ptr_ret"]["ptr"],
            has_ret=True, arg_depth_by_name={"opts": 1}), [])


class SplitTests(unittest.TestCase):
    TYPE = {"name": "widget_st", "defined_in": "w.h", "kind": "struct",
            "_comment_user": "note",
            "fields": [
                {"name": "buf", "type": "uint8_t *", "ref": "pointer",
                 "ptr": {"owned": True}, "refcount": False, "locked_by": None},
                {"name": "refs", "refcount": True},
            ],
            "_analysis": {"submitted": True, "pending": []}}
    FUNC = {"name": "widget_new", "kind": "function_exported", "defined_in": "w.c",
            "ptr_args": [{"position": 0, "name": "opts", "type": "widget_opts",
                          "ptr": None}],
            "ptr_ret": {"type": "widget_st", "ptr": {"owned": True}},
            "lifetime": None, "_analysis": {"submitted": False, "pending": []}}

    def test_type_split(self) -> None:
        out = findings.split_type(self.TYPE)
        self.assertNotIn("_comment_user", out["composed"])
        for f in out["composed"]["fields"]:
            self.assertFalse(set(f) & set(findings.FIELD_KEYS))
        self.assertEqual(out["findings"], {
            "_comment_user": "note",
            "fields": {"buf": {"ptr": {"owned": True}, "refcount": False, "locked_by": None},
                       "refs": {"refcount": True, "locked_by": None}}})
        self.assertLessEqual(set(out["findings"]), Q._FINDINGS_TOP)

    def test_symbol_split(self) -> None:
        out = findings.split_symbol(self.FUNC)
        self.assertNotIn("lifetime", out["composed"])
        self.assertNotIn("ptr", out["composed"]["ptr_args"][0])
        self.assertNotIn("ptr", out["composed"]["ptr_ret"])
        self.assertEqual(out["findings"], {
            "ptr_args": {"opts": {"ptr": None}},
            "ptr_ret": {"ptr": {"owned": True}}, "lifetime": None})
        self.assertLessEqual(set(out["findings"]), Q._SYM_FINDINGS_TOP)

    def test_callback_primary_lists_its_forks(self) -> None:
        cb = {**self.FUNC, "kind": "callback", "ptr_ret": None}
        fork = {**cb, "variant": 1, "used_by": {"call": ["widget_reset"]}}
        out = findings.split_symbol(cb, [fork])
        self.assertEqual(out["findings"]["forks"], [{
            "ptr_args": {"opts": {"ptr": None}}, "lifetime": None,
            "callsites": ["widget_reset"]}])

    def test_global_takes_ptr_and_lock(self) -> None:
        g = {"name": "g", "kind": "global_extern", "ptr": None, "locked_by": None}
        self.assertEqual(findings.split_symbol(g)["findings"],
                         {"ptr": None, "locked_by": None})

    def test_key_sets_agree_with_the_validator(self) -> None:
        self.assertEqual(set(findings.FIELD_KEYS), set(Q._FIELD_AGENT_KEYS))


if __name__ == "__main__":
    unittest.main()


class StoreExampleTests(unittest.TestCase):
    """`examples/ownership-store.json` records exactly `examples/findings.json`."""

    def test_store_example_holds_the_findings_example(self) -> None:
        from types import SimpleNamespace
        from wavefront import store

        doc = store.load(SimpleNamespace(root=EXAMPLE.parent))
        self.assertEqual(store.normalize(json.loads(json.dumps(doc))), doc)

        def sym(rec: dict) -> dict:
            out = {k: rec[k] for k in ("lifetime", "ptr", "locked_by", "callsites")
                   if k in rec}
            if "ptr_args" in rec:
                out["ptr_args"] = {a["name"]: {"ptr": a["ptr"]} for a in rec["ptr_args"]}
            if "ptr_ret" in rec:
                out["ptr_ret"] = rec["ptr_ret"]
            return out

        types = {r["name"]: {"_comment_user": r.get("_comment_user"),
                             "fields": {f["name"]: {k: v for k, v in f.items() if k != "name"}
                                        for f in r.get("fields") or []}}
                 for r in doc["types"]}
        symbols: dict = {}
        for r in doc["symbols"]:
            if r.get("variant"):
                symbols[r["name"]].setdefault("forks", []).append(sym(r))
            else:
                symbols[r["name"]] = sym(r)
        ex = _example()
        self.assertEqual(types, ex["types"])
        self.assertEqual(symbols, ex["symbols"])
