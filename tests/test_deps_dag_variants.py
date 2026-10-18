from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compose import deps_dag, t3
from test_deps_dag_slot_casts import SLOT_COLS, _slot_row
from test_t3 import FIELD_COLS, FN_COLS, PARAM_COLS, TYPE_COLS, _type, _write, chased

H = "log.h"


def _end(kind: str, name: str, member: str = "", ctype: str = "void *") -> dict:
    if kind == "type":
        return {"kind": kind, "name": name, "def_file": H, "member": "",
                "decl": name, "ctype": ""}
    return {"kind": kind, "name": name, "def_file": "log.c" if kind == "param" else H,
            "member": member, "decl": "", "ctype": ctype}


class VariantDagTests(unittest.TestCase):
    """`Side.data` (`uint8_t *`) is read as Stereo and as the pun union
    Pun; one muxer parks a Packet in `Stream.priv_data`, another the Fmt
    whose typed `streams` field holds Stream; `vlog` reads its `void *` as
    Class and as Pun; Ctx is cast to Class. Every one of those is a derived
    cast edge -- a variant depends on its field's owner, as a derived type
    on its base -- and a T3 `drop` row removes it."""

    def _graph(self, api: bool, rows=(), off_graph=()):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codeql = root / "codeql"
            names = ("Class", "Ctx", "Side", "Stereo", "Pun", "Stream", "Packet", "Fmt")
            _write(codeql / "t1" / "types.csv", TYPE_COLS, [_type(n, H) for n in names])
            _write(codeql / "t1" / "functions.csv", FN_COLS, [
                {"name": "vlog", "def_file": "log.c", "decl_files": H}])
            _write(codeql / "t1" / "params.csv", PARAM_COLS, [
                {"function_name": "vlog", "function_def_file": "log.c", "position": "0",
                 "param_type": "void *", "ptr_depth": "1", "is_erased": "true"}])
            _write(codeql / "t1" / "fields.csv", FIELD_COLS, [
                {"struct_name": "Side", "struct_def_file": H, "field_name": "data",
                 "field_type": "uint8_t *", "is_scalar": "true", "ptr_depth": "1",
                 "is_erased": "false"},
                {"struct_name": "Stream", "struct_def_file": H, "field_name": "priv_data",
                 "field_type": "void *", "is_scalar": "true", "ptr_depth": "1",
                 "is_erased": "true"}])
            _write(codeql / "t2" / "casts.csv", ["from_tag", "to_tag"],
                   [{"from_tag": "Ctx", "to_tag": "Class"}])
            _write(codeql / "t2" / "field_type_uses.csv",
                   ["struct_name", "struct_def_file", "field_name", "type_name",
                    "type_kind", "type_def_file"],
                   [{"struct_name": "Fmt", "struct_def_file": H, "field_name": "streams",
                     "type_name": "Stream", "type_kind": "struct", "type_def_file": H}])
            _write(codeql / "t2" / "signature_type_uses.csv",
                   ["function_name", "function_def_file", "type_name", "type_kind",
                    "type_def_file", "position"], [])
            data = _end("field", "Side", "data", "uint8_t *")
            _write(codeql / "t2" / "field_casts.csv", SLOT_COLS, [
                _slot_row("to", data, _end("type", "Stereo")),
                _slot_row("to", data, _end("type", "Pun")),
                _slot_row("from", _end("type", "Packet"),
                          _end("field", "Stream", "priv_data")),
                _slot_row("from", _end("type", "Fmt"),
                          _end("field", "Stream", "priv_data")),
            ])
            _write(codeql / "t2" / "arg_casts.csv", SLOT_COLS, [
                _slot_row("to", _end("param", "vlog", "0"), _end("type", "Class")),
                _slot_row("to", _end("param", "vlog", "0"), _end("type", "Pun")),
            ])
            _write(root / "t3" / t3.CHASED, list(t3.CHASED_COLS), list(rows))
            t3.configure(root / "t3")
            self.addCleanup(t3.configure, None)
            api_paths = {H} if api else None
            meta = deps_dag.collect_types_csv(codeql, api_paths)[0]
            syms = [{"name": "vlog", "kind": "function", "defined_in": "log.c",
                     "declared_in": H, "loc": 3, "depends_on": {"types": [], "syms": []},
                     "ptr_args": [], "ptr_ret": None}]

            def entries(_root, kind):
                return syms if kind == "symbols" else []

            with patch.object(deps_dag, "_entries_of", side_effect=entries):
                types, symbols, aliases = deps_dag._collect(
                    object(), port_syms=set() if api else None,
                    port_fields={} if api else None, codeql_dir=codeql,
                    in_scope_types=set(meta) - {(n, H) for n in off_graph},
                    layout_paths={H} if api else set(), api_paths=api_paths)
                amap = deps_dag._alias_map(object(), types, aliases)
                deps_dag._build_edges(types, symbols, amap)
            stale = deps_dag.t3_stale(codeql)
            return ({k[0]: {d[0] for d in n.dep_types} for k, n in types.items()},
                    symbols[("vlog", "log.c")].dep_types, stale)

    def test_variants_depend_on_the_owner(self) -> None:
        for api in (False, True):
            types, vlog, stale = self._graph(api)
            self.assertEqual(types["Stereo"], {"Side"}, api)
            self.assertEqual(types["Pun"], {"Side"}, api)
            self.assertEqual(types["Packet"], {"Stream"}, api)
            self.assertEqual(types["Side"], set(), api)
            self.assertEqual(types["Ctx"], {"Class"}, api)
            self.assertEqual({d[0] for d in vlog}, {"Class", "Pun"}, api)
            self.assertEqual(stale, [])

    def test_a_variant_holding_its_container_closes_no_cycle(self) -> None:
        # Fmt holds Stream in a typed field and is parked in Stream's erased
        # one: both edges run Fmt -> Stream.
        for api in (False, True):
            types, _, _ = self._graph(api)
            self.assertEqual(types["Fmt"], {"Stream"}, api)
            self.assertEqual(types["Stream"], set(), api)

    def test_drop_rows_remove_derived_edges(self) -> None:
        rows = [chased("erased_field", ("Side", H, "data"), ("Pun", H), op="drop"),
                chased("erased_field", ("Stream", H, "priv_data"), ("Packet", H), op="drop"),
                chased("erased_arg", ("vlog", "log.c", "0"), ("Pun", H), op="drop"),
                chased("base_derived", base=("Class", H), derived=("Ctx", H), op="drop")]
        for api in (False, True):
            types, vlog, stale = self._graph(api, rows)
            self.assertEqual(types["Stereo"], {"Side"}, api)
            self.assertEqual(types["Pun"], set(), api)
            self.assertEqual(types["Packet"], set(), api)
            self.assertEqual(types["Ctx"], set(), api)
            self.assertEqual({d[0] for d in vlog}, {"Class"}, api)
            self.assertEqual(stale, [])

    def test_variants_off_the_graph_are_pruned(self) -> None:
        for api in (False, True):
            types, _, _ = self._graph(api, off_graph=["Side"])
            self.assertEqual(types["Stereo"], set(), api)
            self.assertEqual(types["Pun"], set(), api)

    def test_rows_that_correct_nothing_are_stale(self) -> None:
        rows = [chased("erased_field", ("Side", H, "data"), ("Ctx", H), op="drop"),
                chased("erased_field", ("Side", H, "data"), ("Stereo", H)),
                chased("erased_arg", ("vlog", "log.c", "0"), ("Ctx", H), op="drop"),
                chased("erased_arg", ("vlog", "log.c", "0"), ("Class", H)),
                chased("base_derived", base=("Stereo", H), derived=("Pun", H), op="drop")]
        _, _, stale = self._graph(False, rows)
        self.assertEqual(sorted(stale), sorted([
            "drop erased_field Side.data -> Ctx: no such variant",
            "add erased_field Side.data -> Stereo: already a variant",
            "drop erased_arg vlog.0 -> Ctx: no such read",
            "add erased_arg vlog -> Class: already read in its body",
            "drop base_derived Stereo / Pun: no cast between them",
        ]))


if __name__ == "__main__":
    unittest.main()
