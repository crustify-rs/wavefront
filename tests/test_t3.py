from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from compose import t3


def _write(path: Path, cols: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


TYPE_COLS = ["name", "kind", "def_file", "decl_files", "aliases", "unaliased_kind"]
FN_COLS = ["name", "linkage", "def_file", "decl_files", "signature", "loc", "is_variadic"]
PARAM_COLS = ["function_name", "function_def_file", "position", "param_name",
              "param_type", "ptr_depth", "is_erased"]
FIELD_COLS = ["struct_name", "struct_def_file", "field_name", "field_type",
              "is_scalar", "ptr_depth", "is_erased"]
MACRO_COLS = ["name", "head", "body", "def_file"]


def _type(name: str, df: str, decls: str = "") -> dict:
    return {"name": name, "kind": "struct", "def_file": df,
            "decl_files": decls or df, "aliases": "", "unaliased_kind": ""}


def inventory(root: Path) -> Path:
    """`log.h` publishes Class, Ctx and `vlog`; `priv.c` holds the rest."""
    t1 = root / "codeql" / "t1"
    _write(t1 / "types.csv", TYPE_COLS, [
        _type("Class", "log.h"), _type("Ctx", "log.h"), _type("Priv", "priv.c"),
        _type("Holder", "log.h"), _type("Inner", "log.h"),
        {"name": "Class", "kind": "typedef", "def_file": "", "decl_files": "log.h",
         "aliases": "Class", "unaliased_kind": ""},
    ])
    _write(t1 / "functions.csv", FN_COLS, [
        {"name": "vlog", "def_file": "log.c", "decl_files": "log.h"},
        {"name": "helper", "def_file": "priv.c", "decl_files": ""},
    ])
    _write(t1 / "params.csv", PARAM_COLS, [
        {"function_name": "vlog", "function_def_file": "log.c", "position": "0",
         "param_type": "void *", "ptr_depth": "1", "is_erased": "true"},
        {"function_name": "vlog", "function_def_file": "log.c", "position": "1",
         "param_type": "int", "ptr_depth": "0", "is_erased": "false"},
        {"function_name": "helper", "function_def_file": "priv.c", "position": "0",
         "param_type": "voidpf", "ptr_depth": "1", "is_erased": "true"},
    ])
    _write(t1 / "fields.csv", FIELD_COLS, [
        {"struct_name": "Holder", "struct_def_file": "log.h", "field_name": "opaque",
         "field_type": "void *", "ptr_depth": "1", "is_erased": "true"},
        {"struct_name": "Holder", "struct_def_file": "log.h", "field_name": "u.raw",
         "field_type": "void **", "ptr_depth": "2", "is_erased": "true"},
        {"struct_name": "Holder", "struct_def_file": "log.h", "field_name": "in",
         "field_type": "struct Inner", "ptr_depth": "0", "is_erased": "false"},
        {"struct_name": "Holder", "struct_def_file": "log.h", "field_name": "n",
         "field_type": "int", "ptr_depth": "0", "is_erased": "false"},
        {"struct_name": "Holder", "struct_def_file": "log.h", "field_name": "buf",
         "field_type": "uint8_t *", "is_scalar": "true", "ptr_depth": "1",
         "is_erased": "false"},
        {"struct_name": "Inner", "struct_def_file": "log.h", "field_name": "p",
         "field_type": "void *", "ptr_depth": "1", "is_erased": "true"},
    ])
    _write(t1 / "macros.csv", MACRO_COLS, [
        {"name": "GEN", "def_file": "gen.h"}, {"name": "GEN_STR", "def_file": "gen.h"},
        {"name": "PUB_GEN", "def_file": "log.h"},
    ])
    return t1


def chased(kind, slot=("", "", ""), base=("", ""), derived=("", ""), op="") -> dict:
    return dict(zip(t3.CHASED_COLS, (kind, *slot, *base, *derived, op)))


def generator(macro, dk, derived) -> dict:
    return dict(zip(t3.GENERATOR_COLS, (*macro, dk, *derived)))


class T3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.t1 = inventory(self.root)
        self.dir = self.root / "t3"
        t3.configure(self.dir)
        self.addCleanup(t3.configure, None)

    def load(self, chased_rows=(), gen_rows=(), api=None):
        _write(self.dir / t3.CHASED, list(t3.CHASED_COLS), list(chased_rows))
        _write(self.dir / t3.GENERATORS, list(t3.GENERATOR_COLS), list(gen_rows))
        return t3.load(self.t1, api)

    def errors(self, *args, **kw) -> str:
        with self.assertRaises(SystemExit) as cm:
            self.load(*args, **kw)
        return str(cm.exception)

    def test_unconfigured_is_empty(self) -> None:
        t3.configure(None)
        self.assertEqual(t3.load(self.t1), t3.EMPTY)

    def test_rows_become_relations(self) -> None:
        tables = self.load([
            chased("erased_arg", ("vlog", "log.c", "0"), ("Class", "log.h")),
            chased("erased_field", ("Holder", "log.h", "u.raw"), ("Ctx", "log.h")),
            chased("base_derived", base=("Class", "log.h"), derived=("Ctx", "log.h")),
        ], [
            generator(("GEN", "gen.h"), "type", ("Priv", "priv.c")),
            generator(("GEN", "gen.h"), "macro", ("GEN_STR", "gen.h")),
        ])
        self.assertEqual(tables.erased_args, {("vlog", "log.c"): {("Class", "log.h")}})
        self.assertEqual(tables.erased_fields,
                         {("Holder", "log.h"): {("u.raw", "Ctx", "log.h")}})
        self.assertEqual(tables.bases, {("Ctx", "log.h"): {("Class", "log.h")}})
        self.assertEqual(tables.generates, {("GEN", "gen.h"): {
            ("type", "Priv", "priv.c"), ("macro", "GEN_STR", "gen.h")}})

    def test_typedef_erased_parameter_is_accepted(self) -> None:
        # `voidpf` reads as a name in the signature; params.csv resolved it.
        tables = self.load([chased("erased_arg", ("helper", "priv.c", "0"), ("Priv", "priv.c"))])
        self.assertIn(("helper", "priv.c"), tables.erased_args)

    def test_tagged_embedded_field_is_its_own_struct(self) -> None:
        tables = self.load([chased("erased_field", ("Holder", "log.h", "in.p"), ("Ctx", "log.h"))])
        self.assertEqual(tables.erased_fields, {("Inner", "log.h"): {("p", "Ctx", "log.h")}})

    def test_every_bad_row_is_reported(self) -> None:
        msg = self.errors([
            chased("erased_ptr", ("vlog", "log.c", "0"), ("Class", "log.h")),
            chased("erased_arg", ("vlog", "log.c", "1"), ("Class", "log.h")),
            chased("erased_arg", ("vlog", "log.c", "7"), ("Class", "log.h")),
            chased("erased_arg", ("vlog", "x.c", "0"), ("Class", "log.h")),
            chased("erased_arg", ("vlog", "log.c", "0"), ("Nope", "log.h")),
            chased("erased_arg", ("vlog", "log.c", "0"), ("Class", "")),
            chased("erased_field", ("Holder", "log.h", "n"), ("Ctx", "log.h")),
            chased("erased_field", ("Holder", "log.h", "gone"), ("Ctx", "log.h")),
            chased("base_derived", base=("Ctx", "log.h"), derived=("Ctx", "log.h")),
            chased("base_derived", ("vlog", "log.c", "0"), ("Ctx", "log.h"), ("Class", "log.h")),
        ], [
            generator(("NOPE", "gen.h"), "type", ("Priv", "priv.c")),
            generator(("GEN", "gen.h"), "macro", ("GEN", "gen.h")),
            generator(("GEN", "gen.h"), "alias", ("Priv", "priv.c")),
        ])
        for line, needle in [
            (2, "kind 'erased_ptr'"), (3, "is 'int', not void *"),
            (4, "no parameter '7'"), (5, "not defined in 'x.c'"),
            (6, "'Nope' is not in t1/types.csv"), (7, "defined in ['log.h']"),
            (8, "Holder.n is 'int'"), (9, "no field 'gone'"),
            (10, "same type"), (11, "must leave ['slot_name', 'slot_def_file', 'slot_member'] empty"),
        ]:
            self.assertIn(f"{t3.CHASED}:{line}: ", msg)
            self.assertIn(needle, msg)
        for line, needle in [(2, "'NOPE' is not defined"), (3, "does not generate itself"),
                             (4, "derived_kind 'alias'")]:
            self.assertIn(f"{t3.GENERATORS}:{line}: ", msg)
            self.assertIn(needle, msg)

    def test_api_mode_projects_onto_public_nodes(self) -> None:
        # Same rows, both modes: every row is checked and kept for the records;
        # API mode leaves out the ones naming an internal function, type,
        # layout or macro -- never an error.
        rows = [chased("erased_arg", ("vlog", "log.c", "0"), ("Class", "log.h")),
                chased("erased_arg", ("helper", "priv.c", "0"), ("Priv", "priv.c")),
                chased("base_derived", base=("Class", "log.h"), derived=("Ctx", "log.h")),
                chased("base_derived", base=("Class", "log.h"), derived=("Priv", "priv.c"))]
        gens = [generator(("PUB_GEN", "log.h"), "type", ("Ctx", "log.h")),
                generator(("GEN", "gen.h"), "type", ("Priv", "priv.c"))]
        whole = self.load(rows, gens)
        self.assertEqual(set(whole.erased_args), {("vlog", "log.c"), ("helper", "priv.c")})
        self.assertEqual(set(whole.bases), {("Ctx", "log.h"), ("Priv", "priv.c")})
        self.assertEqual(set(whole.generates), {("PUB_GEN", "log.h"), ("GEN", "gen.h")})
        api = self.load(rows, gens, api={"log.h"})
        self.assertEqual(set(api.erased_args), {("vlog", "log.c")})
        self.assertEqual(set(api.bases), {("Ctx", "log.h")})
        self.assertEqual(set(api.generates), {("PUB_GEN", "log.h")})

    def test_api_mode_still_reports_bad_rows(self) -> None:
        msg = self.errors([chased("erased_arg", ("helper", "priv.c", "9"), ("Priv", "priv.c"))],
                          api={"log.h"})
        self.assertIn("helper has no parameter '9'", msg)

    def test_op_splits_rows_into_adds_and_drops(self) -> None:
        tables = self.load([
            chased("erased_arg", ("vlog", "log.c", "0"), ("Class", "log.h"), op="add"),
            chased("erased_arg", ("vlog", "log.c", "0"), ("Ctx", "log.h"), op="drop"),
            chased("erased_field", ("Holder", "log.h", "in.p"), ("Ctx", "log.h"), op="drop"),
            chased("base_derived", base=("Class", "log.h"), derived=("Ctx", "log.h"),
                   op="drop"),
        ])
        self.assertEqual(tables.erased_args, {("vlog", "log.c"): {("Class", "log.h")}})
        self.assertEqual(tables.drop_args, {("vlog", "log.c"): {("0", "Ctx", "log.h")}})
        self.assertEqual(tables.drop_fields, {("Inner", "log.h"): {("p", "Ctx", "log.h")}})
        self.assertEqual(tables.drop_bases, {("Ctx", "log.h"): {("Class", "log.h")}})
        self.assertEqual((tables.erased_fields, tables.bases), ({}, {}))

    def test_a_table_without_the_op_column_adds(self) -> None:
        cols = [c for c in t3.CHASED_COLS if c != "op"]
        row = chased("erased_arg", ("vlog", "log.c", "0"), ("Class", "log.h"))
        _write(self.dir / t3.CHASED, cols, [{c: row[c] for c in cols}])
        tables = t3.load(self.t1)
        self.assertEqual(tables.erased_args, {("vlog", "log.c"): {("Class", "log.h")}})
        self.assertEqual(tables.drop_args, {})

    def test_a_table_in_the_earlier_spelling_loads(self) -> None:
        # `base_name` / `base_def_file` were renamed `type_name` / `type_def_file`.
        cols = [{"type_name": "base_name", "type_def_file": "base_def_file"}.get(c, c)
                for c in t3.CHASED_COLS]
        row = chased("erased_arg", ("vlog", "log.c", "0"), ("Class", "log.h"))
        _write(self.dir / t3.CHASED, cols,
               [dict(zip(cols, (row[c] for c in t3.CHASED_COLS)))])
        tables = t3.load(self.t1)
        self.assertEqual(tables.erased_args, {("vlog", "log.c"): {("Class", "log.h")}})

    def test_a_scalar_pointer_field_holds_variants(self) -> None:
        # `uint8_t *buf` names no struct: wavefront records variants for it,
        # so a row may add or drop one. `int n` is no pointer.
        tables = self.load([chased("erased_field", ("Holder", "log.h", "buf"),
                                   ("Ctx", "log.h"), op="drop")])
        self.assertEqual(tables.drop_fields, {("Holder", "log.h"): {("buf", "Ctx", "log.h")}})
        msg = self.errors([chased("erased_field", ("Holder", "log.h", "n"), ("Ctx", "log.h"))])
        self.assertIn("not void * / void ** or a scalar pointer", msg)

    def test_bad_ops_and_contradictions_are_reported(self) -> None:
        msg = self.errors([
            chased("erased_arg", ("vlog", "log.c", "0"), ("Class", "log.h"), op="keep"),
            chased("erased_arg", ("vlog", "log.c", "0"), ("Ctx", "log.h"), op="add"),
            chased("erased_arg", ("vlog", "log.c", "0"), ("Ctx", "log.h"), op="drop"),
            chased("erased_arg", ("vlog", "log.c", "0"), ("Ctx", "log.h")),
        ])
        self.assertIn(f"{t3.CHASED}:2: op 'keep' is not one of", msg)
        self.assertIn(f"{t3.CHASED}:4: drop contradicts add of the same edge at "
                      f"{t3.CHASED}:3", msg)
        self.assertNotIn(f"{t3.CHASED}:5:", msg)

    def test_missing_params_table_asks_for_extraction(self) -> None:
        (self.t1 / "params.csv").unlink()
        msg = self.errors([chased("erased_arg", ("vlog", "log.c", "0"), ("Class", "log.h"))])
        self.assertIn("t1/params.csv is missing; run extract-ql", msg)


if __name__ == "__main__":
    unittest.main()
