from __future__ import annotations

import unittest

from compose import deps_dag
from compose.deps_dag import SymNode, TypeNode


class ApiClosureCastTests(unittest.TestCase):
    """An API graph keeps a cast edge only between two nodes of its API
    closure, which casts never widen: the closure is what the public
    signatures and fields reach (`_build_api_edges`)."""

    def _graph(self):
        # Ctx (public) holds a Class through a typed field, so Class is in the
        # closure. Ctx is also cast to Class (an AVClass-headed context) and
        # downcast to the internal Priv, which nothing public names. vlog
        # (public) reads its void* as Class; ivlog (internal) reads its own as
        # Priv.
        def t(tag, df):
            n = TypeNode(tag, df)
            n.kind, n.defined_in = "struct", df
            return n
        ctx, cls, priv = t("Ctx", "log.h"), t("Class", "log.h"), t("Priv", "priv.c")
        ctx.ctype_refs.add(("Class", "log.h"))
        ctx.cast_to |= {"Class", "Priv"}
        cls.cast_from.add("Ctx")
        priv.cast_from.add("Ctx")
        types = {n.key: n for n in (ctx, cls, priv)}

        def f(name, cast):
            n = SymNode(name, "log.c")
            n.kind, n.defined_in = "function", "log.c"
            n.cast_sig_refs.add(cast)
            return n
        syms = {("vlog", "log.c"): f("vlog", "Class"), ("ivlog", "log.c"): f("ivlog", "Priv")}
        amap = {k[0]: k for k in types}
        scope = {"api": {"types": [{"name": "Ctx", "defined_in": "log.h"}],
                         "functions": [{"name": "vlog", "defined_in": "log.c"}]}}
        return types, syms, amap, scope

    def test_casts_off_the_api_closure_add_no_edge(self) -> None:
        types, syms, amap, scope = self._graph()
        deps_dag._build_api_edges(types, syms, amap, scope)
        cls, priv = ("Class", "log.h"), ("Priv", "priv.c")
        self.assertEqual(types[("Ctx", "log.h")].dep_types, {cls})
        self.assertEqual(syms[("vlog", "log.c")].dep_types, {cls})
        self.assertEqual(syms[("ivlog", "log.c")].dep_types, set())
        self.assertEqual(types[priv].dep_types, set())

    def test_the_closure_is_cast_free(self) -> None:
        types, syms, amap, scope = self._graph()
        deps_dag._build_edges(types, syms, amap, cast_scope=(set(), set()))
        closure_t, closure_s = deps_dag._api_closure(types, syms, scope)
        self.assertEqual(closure_t, {("Ctx", "log.h"), ("Class", "log.h")})
        self.assertEqual(closure_s, {("vlog", "log.c")})

    def test_without_a_cast_scope_every_cast_is_an_edge(self) -> None:
        types, syms, amap, _ = self._graph()
        deps_dag._build_edges(types, syms, amap)
        self.assertIn(("Priv", "priv.c"), types[("Ctx", "log.h")].dep_types)
        self.assertIn(("Priv", "priv.c"), syms[("ivlog", "log.c")].dep_types)


if __name__ == "__main__":
    unittest.main()
