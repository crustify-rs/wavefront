from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compose import deps_dag

SLOT_COLS = ["rel",
             "src_kind", "src_name", "src_def_file", "src_member", "src_decl", "src_ctype",
             "dst_kind", "dst_name", "dst_def_file", "dst_member", "dst_decl", "dst_ctype",
             "site_fn", "site_file", "line"]


def _write(path: Path, cols: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _end(kind: str, name: str, member: str = "", decl: str = "") -> dict:
    file = "include/log.h" if kind == "type" else "src/log.c"
    return {"kind": kind, "name": name, "def_file": file, "member": member,
            "decl": decl if kind != "type" else name,
            "ctype": "" if kind == "type" else "void *"}


def _slot_row(rel: str, src: dict, dst: dict) -> dict:
    row = {"rel": rel, "site_fn": "", "site_file": "src/log.c", "line": 1}
    for side, end in (("src", src), ("dst", dst)):
        row.update({f"{side}_{k}": v for k, v in end.items()})
    return row


class SlotCastDagTests(unittest.TestCase):
    """`av_vlog(avcl)` reads `*(Class **) avcl`; two classed contexts call it
    directly, and `av_log(avcl)` only hands its erased value on. In API and
    non-API graphs, and projected onto the public API."""

    def _codeql(self, td: str) -> Path:
        codeql = Path(td)
        types = [{"name": n, "kind": "struct", "def_file": "include/log.h",
                  "decl_files": "include/log.h", "aliases": "", "unaliased_kind": ""}
                 for n in ("Class", "CtxA", "CtxB")]
        _write(codeql / "t1" / "functions.csv", ["name", "def_file", "decl_files"], [
            {"name": "log", "def_file": "src/log.c", "decl_files": "include/log.h"},
            {"name": "vlog", "def_file": "src/log.c", "decl_files": "src/internal.h"}])
        _write(codeql / "t1" / "types.csv",
               ["name", "kind", "def_file", "decl_files", "aliases", "unaliased_kind"],
               types)
        _write(codeql / "t2" / "casts.csv", ["from_tag", "to_tag"], [])
        _write(codeql / "t2" / "field_type_uses.csv",
               ["struct_name", "struct_def_file", "field_name", "type_name",
                "type_kind", "type_def_file"], [])
        _write(codeql / "t2" / "signature_type_uses.csv",
               ["function_name", "function_def_file", "type_name", "type_kind",
                "type_def_file", "position"], [])
        _write(codeql / "t2" / "arg_casts.csv", SLOT_COLS, [
            _slot_row("from", _end("type", "CtxA"), _end("param", "vlog", "0")),
            _slot_row("from", _end("type", "CtxB"), _end("param", "vlog", "0")),
            _slot_row("forward", _end("param", "log", "0"), _end("param", "vlog", "0")),
            _slot_row("to", _end("param", "vlog", "0"), _end("type", "Class")),
        ])
        return codeql

    def _graph(self, port_syms):
        with tempfile.TemporaryDirectory() as td:
            codeql = self._codeql(td)
            meta = deps_dag.collect_types_csv(codeql)[0]
            syms = [{"name": n, "kind": "function", "defined_in": "src/log.c",
                     "declared_in": "include/log.h", "loc": 3,
                     "depends_on": {"types": [], "syms": []},
                     "ptr_args": [], "ptr_ret": None} for n in ("log", "vlog")]

            def entries(_root, kind):
                return syms if kind == "symbols" else []

            with patch.object(deps_dag, "_entries_of", side_effect=entries):
                types, symbols, aliases = deps_dag._collect(
                    object(), port_syms=port_syms, port_fields={},
                    codeql_dir=codeql, in_scope_types=set(meta), layout_paths=set())
                amap = deps_dag._alias_map(object(), types, aliases)
                deps_dag._build_edges(types, symbols, amap)
            return types, symbols

    def test_slot_pairs_join_the_cast_graph(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            casts = deps_dag.collect_types_csv(self._codeql(td))[2]
        self.assertEqual(casts["CtxA"][0], {"Class"})
        self.assertEqual(casts["Class"][1], {"CtxA", "CtxB"})

    def test_classed_contexts_order_after_their_header(self) -> None:
        # Class is cast to from two types, each context to one: the
        # cast-centrality edge runs context -> Class, in both modes.
        cls = ("Class", "include/log.h")
        for port_syms in (set(), None):
            types, _ = self._graph(port_syms)
            for ctx in ("CtxA", "CtxB"):
                self.assertIn(cls, types[(ctx, "include/log.h")].dep_types, port_syms)
            self.assertEqual(types[cls].dep_types, set(), port_syms)

    def test_erased_parameters_depend_on_the_type_they_are_read_as(self) -> None:
        # vlog reads its void* as Class and orders after it, in both modes;
        # log only hands its value on, which is not a cast.
        cls = ("Class", "include/log.h")
        for port_syms in (set(), None):
            _, symbols = self._graph(port_syms)
            self.assertIn(cls, symbols[("vlog", "src/log.c")].dep_types, port_syms)
            self.assertNotIn(cls, symbols[("log", "src/log.c")].dep_types, port_syms)

    def test_api_projection_drops_internal_functions(self) -> None:
        # vlog is declared only in src/internal.h: off the public API, its
        # parameter is no node, so neither its read nor the pairs through it
        # survive projection onto include/log.h.
        with tempfile.TemporaryDirectory() as td:
            codeql = self._codeql(td)
            api = {"include/log.h"}
            self.assertEqual(deps_dag.collect_types_csv(codeql, api)[2], {})
            refs = deps_dag.collect_signature_type_refs_csv(codeql, api)
            self.assertNotIn(("vlog", "src/log.c"), refs)
            refs = deps_dag.collect_signature_type_refs_csv(codeql)
            self.assertEqual(refs[("vlog", "src/log.c")], {"Class"})


if __name__ == "__main__":
    unittest.main()
