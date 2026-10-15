from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from compose import slot_casts
from wavefront.resources import data_root

FIXTURE = Path(__file__).parent / "fixtures" / "slot_casts"
QUERIES = ("arg_casts", "field_casts")


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _key(r: dict) -> tuple:
    return tuple(r[k] for k in sorted(r))


def _edge(rel: str, src: tuple, dst: tuple) -> dict:
    row = {"rel": rel}
    for side, (kind, name, member, decl) in (("src", src), ("dst", dst)):
        row.update({f"{side}_kind": kind, f"{side}_name": name,
                    f"{side}_file": "" if kind == "type" else "f.c",
                    f"{side}_member": member, f"{side}_decl": decl})
    return row


class SlotCastQueryTests(unittest.TestCase):
    """The queries reproduce the golden tables for `slots.c`."""

    @unittest.skipUnless(shutil.which("codeql"), "codeql not on PATH")
    def test_fixture_tables_match_golden(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db"
            subprocess.run(
                ["codeql", "database", "create", str(db), "--language=cpp",
                 "--source-root", str(FIXTURE),
                 "--command=gcc -c slots.c -o /dev/null"],
                check=True, capture_output=True)
            for q in QUERIES:
                bqrs, out = Path(td) / f"{q}.bqrs", Path(td) / f"{q}.csv"
                subprocess.run(
                    ["codeql", "query", "run", f"--database={db}",
                     f"--output={bqrs}", str(data_root() / "edges" / f"{q}.ql")],
                    check=True, capture_output=True)
                subprocess.run(
                    ["codeql", "bqrs", "decode", "--format=csv",
                     f"--output={out}", str(bqrs)],
                    check=True, capture_output=True)
                self.assertEqual(sorted(map(_key, _rows(out))),
                                 sorted(map(_key, _rows(FIXTURE / f"{q}.csv"))), q)


class SlotCastComposeTests(unittest.TestCase):
    def _golden_pairs(self) -> dict:
        rows = _rows(FIXTURE / "arg_casts.csv") + _rows(FIXTURE / "field_casts.csv")
        return slot_casts.compose(rows).pairs

    def _golden_variants(self) -> dict:
        rows = _rows(FIXTURE / "arg_casts.csv") + _rows(FIXTURE / "field_casts.csv")
        return slot_casts.by_field(slot_casts.compose(rows).variants)

    def test_erased_parameter_chain_reaches_the_class_header(self) -> None:
        # CtxA/CtxB -> log_.0 -> vlog.0 -> (const Class **): both siblings
        # are cast to their shared header through two void* parameters.
        pairs = self._golden_pairs()
        for ctx, param in (("CtxA", "0"), ("CtxB", "1")):
            entry, exit_ = pairs[(ctx, "Class")]
            self.assertEqual(entry[:2] + entry[3:], ("param", "use_log", param))
            self.assertEqual(exit_[:2] + exit_[3:], ("param", "vlog", "0"))

    def test_typed_slot_downcast_and_erased_return(self) -> None:
        pairs = self._golden_pairs()
        self.assertIn(("Base", "Derived"), pairs)
        # Holder.opaque <- Payload, read back as Payload: no self pair.
        self.assertNotIn(("Payload", "Payload"), pairs)

    def test_guarded_shapes_produce_no_pairs(self) -> None:
        # `reassigned`, `via_local`, `identity` and `same_type` emit no rows,
        # so nothing beyond the three intended pairs exists.
        self.assertEqual(sorted(self._golden_pairs()),
                         [("Base", "Derived"), ("CtxA", "Class"), ("CtxB", "Class")])

    def test_forward_cycle_converges(self) -> None:
        # a.0 -> b.0 -> c.0 -> a.0, D enters at a.0, c.0 is read as T: every
        # slot of the cycle reaches T, and the cycle adds no other pairs.
        rows = [
            _edge("from", ("type", "D", "", "D"), ("param", "a", "0", "")),
            _edge("forward", ("param", "a", "0", ""), ("param", "b", "0", "")),
            _edge("forward", ("param", "b", "0", ""), ("param", "c", "0", "")),
            _edge("forward", ("param", "c", "0", ""), ("param", "a", "0", "")),
            _edge("to", ("param", "c", "0", ""), ("type", "T", "", "T")),
            _edge("from", ("type", "E", "", "E"), ("param", "b", "0", "")),
        ]
        pairs = slot_casts.compose(rows).pairs
        self.assertEqual(sorted(pairs), [("D", "T"), ("E", "T")])
        self.assertEqual(pairs[("D", "T")],
                         (("param", "a", "f.c", "0"), ("param", "c", "f.c", "0")))

    def test_declared_struct_seeds_the_slot(self) -> None:
        # `f(Base *b) { g(b); }` and g reads its void* as T: Base reaches T
        # with no explicit `from` row -- the slot's decl is the entry.
        rows = [
            _edge("forward", ("param", "f", "0", "Base"), ("param", "g", "0", "")),
            _edge("to", ("param", "g", "0", ""), ("type", "T", "", "T")),
        ]
        self.assertEqual(sorted(slot_casts.compose(rows).pairs), [("Base", "T")])

    def test_erased_field_records_variants_never_pairs(self) -> None:
        # One writer stores D, another reader converts to T: a field is one
        # slot for every instance, so that relates no single value.
        rows = [
            _edge("from", ("type", "D", "", "D"), ("field", "S", "priv", "")),
            _edge("to", ("field", "S", "priv", ""), ("type", "T", "", "T")),
            _edge("to", ("field", "S", "priv", ""), ("type", "U", "", "U")),
        ]
        composed = slot_casts.compose(rows)
        self.assertEqual(composed.pairs, {})
        self.assertEqual(slot_casts.by_field(composed.variants),
                         {("S", "priv"): {"stored": ["D"], "read_as": ["T", "U"]}})

    def test_erased_field_does_not_propagate_into_parameters(self) -> None:
        # D stored into an erased field whose read is passed to g, which
        # converts its parameter to T: still no pair through the field.
        rows = [
            _edge("from", ("type", "D", "", "D"), ("field", "S", "priv", "")),
            _edge("forward", ("field", "S", "priv", ""), ("param", "g", "0", "")),
            _edge("to", ("param", "g", "0", ""), ("type", "T", "", "T")),
        ]
        self.assertEqual(slot_casts.compose(rows).pairs, {})

    def test_named_field_read_enters_a_parameter(self) -> None:
        # av_log(s->avctx): a named field's read passed on is an entry of its
        # decl -- not propagation through the field.
        rows = [
            _edge("forward", ("field", "S", "avctx", "Ctx"), ("param", "log", "0", "")),
            _edge("to", ("param", "log", "0", ""), ("type", "Class", "", "Class")),
        ]
        self.assertEqual(sorted(slot_casts.compose(rows).pairs), [("Ctx", "Class")])

    def test_named_field_pairs_both_directions(self) -> None:
        # `Base *b` field: read as Derived (downcast), Derived stored (upcast).
        rows = [
            _edge("to", ("field", "S", "b", "Base"), ("type", "Derived", "", "Derived")),
            _edge("from", ("type", "Derived", "", "Derived"), ("field", "S", "b", "Base")),
        ]
        self.assertEqual(sorted(slot_casts.compose(rows).pairs),
                         [("Base", "Derived"), ("Derived", "Base")])

    def test_fixture_erased_fields(self) -> None:
        self.assertEqual(self._golden_variants(), {
            ("Holder", "opaque"): {"stored": ["Payload"], "read_as": ["Payload"]},
            ("Holder", "other"): {"stored": ["Payload"], "read_as": []},
        })

    def test_by_type_mirrors_pairs(self) -> None:
        to, from_ = slot_casts.by_type(self._golden_pairs())
        self.assertEqual([r["type"] for r in to["CtxA"]], ["Class"])
        self.assertEqual(sorted(r["type"] for r in from_["Class"]), ["CtxA", "CtxB"])
        self.assertEqual(to["Base"][0]["via"], ["param:derived_extra.0@slots.c"])


if __name__ == "__main__":
    unittest.main()
