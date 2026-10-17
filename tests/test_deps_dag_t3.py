from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compose import deps_dag, t3
from test_t3 import _write, chased, generator, inventory


class T3DagTests(unittest.TestCase):
    """Each T3 row is one edge, in the body-deep and the API graph."""

    def _graph(self, api: bool, casts=(), pairs=True):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codeql = inventory(root).parent
            for name, cols in (("casts.csv", ["from_tag", "to_tag"]),
                               ("field_type_uses.csv", ["struct_name", "struct_def_file",
                                                        "field_name", "type_name",
                                                        "type_kind", "type_def_file"]),
                               ("signature_type_uses.csv", ["function_name",
                                                            "function_def_file", "type_name",
                                                            "type_kind", "type_def_file",
                                                            "position"])):
                _write(codeql / "t2" / name, cols,
                       [dict(zip(cols, c)) for c in casts] if name == "casts.csv" else [])
            d = root / "t3"
            _write(d / t3.CHASED, list(t3.CHASED_COLS), [
                chased("erased_arg", ("vlog", "log.c", "0"), ("Class", "log.h")),
                chased("erased_field", ("Holder", "log.h", "opaque"), ("Ctx", "log.h")),
            ] + ([chased("base_derived", base=("Class", "log.h"), derived=("Ctx", "log.h"))]
                 if pairs else []))
            _write(d / t3.GENERATORS, list(t3.GENERATOR_COLS), [
                generator(("PUB_GEN", "log.h"), "type", ("Inner", "log.h"))])
            t3.configure(d)
            self.addCleanup(t3.configure, None)
            api_paths = {"log.h"} if api else None
            meta = deps_dag.collect_types_csv(codeql, api_paths)[0]
            syms = [{"name": n, "kind": k, "defined_in": df, "declared_in": "log.h",
                     "loc": 3, "depends_on": {"types": [], "syms": []},
                     "ptr_args": [], "ptr_ret": None}
                    for n, k, df in (("vlog", "function", "log.c"),
                                     ("PUB_GEN", "macro", "log.h"))]

            def entries(_root, kind):
                return syms if kind == "symbols" else []

            with patch.object(deps_dag, "_entries_of", side_effect=entries):
                types, symbols, aliases = deps_dag._collect(
                    object(), port_syms=set() if api else None,
                    port_fields={} if api else None, codeql_dir=codeql,
                    in_scope_types=set(meta), layout_paths={"log.h"} if api else set(),
                    api_paths=api_paths)
                amap = deps_dag._alias_map(object(), types, aliases)
                deps_dag._build_edges(types, symbols, amap)
            return types, symbols

    def test_rows_are_edges(self) -> None:
        cls, ctx = ("Class", "log.h"), ("Ctx", "log.h")
        for api in (False, True):
            types, symbols = self._graph(api)
            self.assertIn(cls, symbols[("vlog", "log.c")].dep_types, api)     # erased_arg
            self.assertIn(ctx, types[("Holder", "log.h")].dep_types, api)     # erased_field
            self.assertIn(cls, types[ctx].dep_types, api)                     # base_derived
            self.assertNotIn(ctx, types[cls].dep_types, api)
            self.assertIn(("PUB_GEN", "log.h"),                               # generator
                          types[("Inner", "log.h")].dep_syms, api)

    def test_stated_pair_overrides_the_centrality_guess(self) -> None:
        # Class is downcast to Ctx, and Ctx is cast to two siblings: Ctx is
        # the more cast-central, so the guess makes the BASE depend on it.
        casts = [("Class", "Ctx"), ("Ctx", "Holder"), ("Ctx", "Inner")]
        cls, ctx = ("Class", "log.h"), ("Ctx", "log.h")
        guessed, _ = self._graph(False, casts, pairs=False)
        self.assertIn(ctx, guessed[cls].dep_types)
        for api in (False, True):
            types, _ = self._graph(api, casts)
            self.assertNotIn(ctx, types[cls].dep_types, api)
            self.assertIn(cls, types[ctx].dep_types, api)

    def test_centrality_only_breaks_cast_cycles(self) -> None:
        # Priv <-> Ctx are cast both ways (a cycle); Inner is also cast to
        # Ctx, so Ctx is the hub and only Priv -> Ctx survives. Class is
        # cast to Inner, outside any cycle: kept as written although Inner is
        # no more cast-central than Class.
        casts = [("Priv", "Ctx"), ("Ctx", "Priv"), ("Inner", "Ctx"), ("Class", "Inner")]
        types, _ = self._graph(False, casts, pairs=False)
        priv, ctx = ("Priv", "priv.c"), ("Ctx", "log.h")
        inner, cls = ("Inner", "log.h"), ("Class", "log.h")
        self.assertIn(ctx, types[priv].dep_types)
        self.assertNotIn(priv, types[ctx].dep_types)
        self.assertIn(ctx, types[inner].dep_types)
        self.assertIn(inner, types[cls].dep_types)

    def test_api_mode_drops_casts_with_an_internal_side(self) -> None:
        # Ctx is downcast to the internal Priv: the edge exists in the whole
        # program, not in the API graph.
        ctx, priv = ("Ctx", "log.h"), ("Priv", "priv.c")
        whole, _ = self._graph(False, [("Ctx", "Priv")], pairs=False)
        self.assertIn(priv, whole[ctx].dep_types)
        api, _ = self._graph(True, [("Ctx", "Priv")], pairs=False)
        self.assertNotIn(priv, api[ctx].dep_types)

if __name__ == "__main__":
    unittest.main()
