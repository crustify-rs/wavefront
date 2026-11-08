"""Two file-local types of one tag are two types, wherever an edge names one.

FFmpeg's shapes: a demuxer's `APEContext` (ape.c) is parked in
`AVFormatContext.priv_data` and a decoder's (apedec.c) in
`AVCodecContext.priv_data`; `libavutil/executor.c` and `libavcodec/executor.c`
each define a file-local `ThreadInfo`, named by a typedef in a field of their
own executor. Each edge reaches the type its file defines, and only that one.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compose import deps_dag, slot_casts, t3
from test_deps_dag_slot_casts import SLOT_COLS, _slot_row
from test_t3 import FIELD_COLS, FN_COLS, PARAM_COLS, TYPE_COLS, _type, _write, chased

FMT, CODEC = "libavformat/avformat.h", "libavcodec/avcodec.h"
DEMUX, DEC = "libavformat/ape.c", "libavcodec/apedec.c"
UEXEC, CEXEC = "libavutil/executor.c", "libavcodec/executor.c"
EXR, EXRENC = "libavcodec/exr.c", "libavcodec/exrenc.c"
FTU_COLS = ["struct_name", "struct_def_file", "field_name", "type_name",
            "type_kind", "type_def_file", "type_decl_file"]


def _type_end(name: str, df: str) -> dict:
    return {"kind": "type", "name": name, "def_file": df, "member": "",
            "decl": name, "ctype": ""}


def _field_end(owner: str, df: str, member: str) -> dict:
    return {"kind": "field", "name": owner, "def_file": df, "member": member,
            "decl": "", "ctype": "void *"}


def _param_end(fn: str, df: str) -> dict:
    return {"kind": "param", "name": fn, "def_file": df, "member": "0",
            "decl": "", "ctype": "void *"}


def _typedef(name: str, decl: str, under: str) -> dict:
    return {"name": name, "kind": "typedef", "def_file": "", "decl_files": decl,
            "aliases": under, "unaliased_kind": ""}


class TagCollisionDagTests(unittest.TestCase):
    def _graph(self, *, decl_column: bool = True, rows=()):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codeql = root / "codeql"
            _write(codeql / "t1" / "types.csv", TYPE_COLS, [
                _type("AVFormatContext", FMT), _type("AVCodecContext", CODEC),
                _type("APEContext", DEMUX), _type("APEContext", DEC),
                _type("AVExecutor", UEXEC), _type("FFExecutor", CEXEC),
                _type("ThreadInfo", UEXEC), _type("ThreadInfo", CEXEC),
                _typedef("ThreadInfo", UEXEC, "ThreadInfo"),
                _typedef("ThreadInfo", CEXEC, "ThreadInfo"),
                _type("EXRContext", EXR), _type("Compr", EXR), _type("Compr", EXRENC)])
            _write(codeql / "t1" / "functions.csv", FN_COLS, [
                {"name": "read_header", "def_file": DEMUX, "decl_files": DEMUX},
                {"name": "decode_init", "def_file": DEC, "decl_files": DEC}])
            _write(codeql / "t1" / "params.csv", PARAM_COLS, [
                {"function_name": fn, "function_def_file": df, "position": "0",
                 "param_type": "void *", "ptr_depth": "1", "is_erased": "true"}
                for fn, df in (("read_header", DEMUX), ("decode_init", DEC))])
            _write(codeql / "t1" / "fields.csv", FIELD_COLS, [
                {"struct_name": owner, "struct_def_file": df, "field_name": "priv_data",
                 "field_type": "void *", "is_scalar": "true", "ptr_depth": "1",
                 "is_erased": "true"} for owner, df in (("AVFormatContext", FMT),
                                                        ("AVCodecContext", CODEC))])
            _write(codeql / "t2" / "casts.csv", ["from_tag", "to_tag"], [])
            uses = [{"struct_name": "AVExecutor", "struct_def_file": UEXEC,
                     "field_name": "threads", "type_name": "ThreadInfo",
                     "type_kind": "typedef", "type_def_file": "", "type_decl_file": UEXEC},
                    {"struct_name": "FFExecutor", "struct_def_file": CEXEC,
                     "field_name": "threads", "type_name": "ThreadInfo",
                     "type_kind": "typedef", "type_def_file": "", "type_decl_file": CEXEC}]
            # CodeQL merged exr.c's and exrenc.c's identical `Compr`: one field
            # use, a row per definition.
            uses += [{"struct_name": "EXRContext", "struct_def_file": EXR,
                      "field_name": "compression", "type_name": "Compr",
                      "type_kind": "struct", "type_def_file": f, "type_decl_file": ""}
                     for f in (EXR, EXRENC)]
            cols = FTU_COLS if decl_column else FTU_COLS[:-1]
            _write(codeql / "t2" / "field_type_uses.csv", cols,
                   [{c: u[c] for c in cols} for u in uses])
            _write(codeql / "t2" / "signature_type_uses.csv",
                   ["function_name", "function_def_file", "type_name", "type_kind",
                    "type_def_file", "position"], [])
            _write(codeql / "t2" / "field_casts.csv", SLOT_COLS, [
                _slot_row("from", _type_end("APEContext", DEMUX),
                          _field_end("AVFormatContext", FMT, "priv_data")),
                _slot_row("to", _field_end("AVCodecContext", CODEC, "priv_data"),
                          _type_end("APEContext", DEC))])
            _write(codeql / "t2" / "arg_casts.csv", SLOT_COLS, [
                _slot_row("to", _param_end("read_header", DEMUX),
                          _type_end("APEContext", DEMUX)),
                _slot_row("to", _param_end("decode_init", DEC),
                          _type_end("APEContext", DEC))])
            _write(root / "t3" / t3.CHASED, list(t3.CHASED_COLS), list(rows))
            t3.configure(root / "t3")
            self.addCleanup(t3.configure, None)
            meta = deps_dag.collect_types_csv(codeql)[0]
            syms = [{"name": fn, "kind": "function", "defined_in": df, "declared_in": df,
                     "loc": 3, "depends_on": {"types": [], "syms": []},
                     "ptr_args": [], "ptr_ret": None}
                    for fn, df in (("read_header", DEMUX), ("decode_init", DEC))]

            def entries(_root, kind):
                return syms if kind == "symbols" else []

            with patch.object(deps_dag, "_entries_of", side_effect=entries):
                types, symbols, aliases = deps_dag._collect(
                    object(), port_syms=None, port_fields=None, codeql_dir=codeql,
                    in_scope_types=set(meta), layout_paths=set(), api_paths=None)
                amap = deps_dag._alias_map(object(), types, aliases)
                deps_dag._build_edges(types, symbols, amap)
            self.stale = deps_dag.t3_stale(codeql)
            return ({k: set(n.dep_types) for k, n in types.items()},
                    {k: set(n.dep_types) for k, n in symbols.items()})

    def test_a_variant_depends_on_the_owner_of_its_own_field(self) -> None:
        types, _ = self._graph()
        self.assertEqual(types[("APEContext", DEMUX)], {("AVFormatContext", FMT)})
        self.assertEqual(types[("APEContext", DEC)], {("AVCodecContext", CODEC)})

    def test_an_erased_parameter_depends_on_the_type_its_body_reads(self) -> None:
        _, syms = self._graph()
        self.assertEqual(syms[("read_header", DEMUX)], {("APEContext", DEMUX)})
        self.assertEqual(syms[("decode_init", DEC)], {("APEContext", DEC)})

    def test_a_typedef_field_reaches_the_type_its_file_defines(self) -> None:
        types, _ = self._graph()
        self.assertEqual(types[("AVExecutor", UEXEC)], {("ThreadInfo", UEXEC)})
        self.assertEqual(types[("FFExecutor", CEXEC)], {("ThreadInfo", CEXEC)})

    def test_a_merged_field_type_is_the_owner_s_own_definition(self) -> None:
        types, _ = self._graph()
        self.assertEqual(types[("EXRContext", EXR)], {("Compr", EXR)})

    def test_a_table_without_the_declaring_file_resolves_by_name(self) -> None:
        # An older field_type_uses: both typedefs land on one ThreadInfo.
        types, _ = self._graph(decl_column=False)
        self.assertEqual(types[("AVExecutor", UEXEC)], types[("FFExecutor", CEXEC)])

    def test_a_drop_row_names_the_definition_it_drops(self) -> None:
        rows = [chased("erased_field", ("AVCodecContext", CODEC, "priv_data"),
                       ("APEContext", DEMUX), op="drop"),
                chased("erased_arg", ("decode_init", DEC, "0"),
                       ("APEContext", DEC), op="drop")]
        types, syms = self._graph(rows=rows)
        # The demuxer's APEContext was never in the codec's field: nothing to
        # drop, and the row is stale.
        self.assertEqual(types[("APEContext", DEC)], {("AVCodecContext", CODEC)})
        self.assertEqual(syms[("decode_init", DEC)], set())
        self.assertEqual(syms[("read_header", DEMUX)], {("APEContext", DEMUX)})
        self.assertEqual(self.stale, [
            "drop erased_field AVCodecContext.priv_data -> APEContext: no such variant"])


class MergedDefinitionTests(unittest.TestCase):
    """CodeQL merges identical definitions of a tag from several translation
    units into one type, so a cast to it names every definition's file: one
    row each. The cast's own translation unit sees one of them."""

    def _read(self, site: str, files) -> list[dict]:
        rows = []
        for f in files:
            row = _slot_row("to", _param_end("filter_slice", site),
                            _type_end("ThreadData", f))
            row["site_file"] = site
            rows.append(row)
        return rows

    def _reads(self, rows) -> set:
        return set(slot_casts.compose(rows).param_reads[
            ("param", "filter_slice", rows[0]["src_def_file"], "0")])

    def test_the_definition_in_the_cast_s_own_file_is_kept(self) -> None:
        files = ("vf_a.c", "vf_b.c", "vf_c.c")
        self.assertEqual(self._reads(self._read("vf_b.c", files)), {("ThreadData", "vf_b.c")})

    def test_a_header_definition_is_kept_when_the_file_defines_none(self) -> None:
        files = ("vf_a.c", "thread.h", "vf_c.c")
        self.assertEqual(self._reads(self._read("vf_b.c", files)), {("ThreadData", "thread.h")})

    def test_with_no_visible_definition_the_tag_stands_alone(self) -> None:
        files = ("vf_a.c", "vf_c.c")
        self.assertEqual(self._reads(self._read("vf_b.c", files)), {("ThreadData", "")})

    def test_a_single_definition_is_kept_whatever_the_site(self) -> None:
        self.assertEqual(self._reads(self._read("vf_b.c", ("vf_a.c",))),
                         {("ThreadData", "vf_a.c")})


class DroppedTests(unittest.TestCase):
    def test_a_row_without_a_file_drops_the_tag_anywhere(self) -> None:
        rows = [("priv", "Ctx", "")]
        self.assertTrue(slot_casts.dropped(("Ctx", "a.c"), "priv", rows))
        self.assertFalse(slot_casts.dropped(("Ctx", "a.c"), "other", rows))

    def test_a_row_with_a_file_drops_that_definition_only(self) -> None:
        rows = [("priv", "Ctx", "a.c")]
        self.assertTrue(slot_casts.dropped(("Ctx", "a.c"), "priv", rows))
        self.assertFalse(slot_casts.dropped(("Ctx", "b.c"), "priv", rows))
        self.assertTrue(slot_casts.dropped(("Ctx", ""), "priv", rows))


if __name__ == "__main__":
    unittest.main()
