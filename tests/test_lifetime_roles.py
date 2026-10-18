"""The symbol-level `lifetime` roles: the validator's rules for each role, the
constructor role's `for: "return"` subject, and the reverse-derived lifecycle
index that `--lifetime-for` and the type views read."""
from __future__ import annotations

import unittest

from compose.scope import build_lifecycle_index, type_constructed_by, type_method_syms
from wavefront.query import _lifetime_errors

OWNED = {"owned": True, "borrowed": None}
BORROWED = {"owned": False, "borrowed": {"lifetime": "caller"}}


def ctor(alloc: bool, init: bool, subject: str) -> dict:
    return {"for": subject, "is_constructor": {"alloc": alloc, "init": init}}


class ConstructorRoleTests(unittest.TestCase):
    def test_alloc_names_the_return_and_requires_it_owned(self):
        self.assertEqual(_lifetime_errors("lt", ctor(True, False, "return"), {},
                                          ret_ptr=OWNED, has_ret=True), [])
        errs = _lifetime_errors("lt", ctor(True, False, "return"), {},
                                ret_ptr=BORROWED, has_ret=True)
        self.assertTrue(any("return to be owned" in e for e in errs), errs)

    def test_alloc_needs_a_pointer_return(self):
        errs = _lifetime_errors("lt", ctor(True, False, "return"), {},
                                ret_ptr=None, has_ret=False)
        self.assertTrue(any("no pointer return" in e for e in errs), errs)

    def test_only_alloc_may_name_the_return(self):
        errs = _lifetime_errors("lt", {"for": "return", "is_dropper": True},
                                {"obj": OWNED}, has_ret=True)
        self.assertTrue(any("only an alloc constructor" in e for e in errs), errs)

    def test_alloc_through_an_out_parameter(self):
        # `int foo_new(foo **out)`: the new object comes back through `out`.
        self.assertEqual(_lifetime_errors(
            "lt", ctor(True, False, "out"), {"out": {"mutable": True}},
            arg_depth_by_name={"out": 2}), [])
        errs = _lifetime_errors("lt", ctor(True, False, "out"), {"out": None},
                                arg_depth_by_name={"out": 1})
        self.assertTrue(any("out-parameter" in e for e in errs), errs)
        errs = _lifetime_errors("lt", ctor(True, False, "out"),
                                {"out": {"mutable": False}},
                                arg_depth_by_name={"out": 2})
        self.assertTrue(any("writable" in e for e in errs), errs)

    def test_init_acts_on_writable_single_pointer_storage(self):
        self.assertEqual(_lifetime_errors("lt", ctor(False, True, "obj"),
                                          {"obj": {"mutable": True}},
                                          arg_depth_by_name={"obj": 1}), [])
        errs = _lifetime_errors("lt", ctor(False, True, "obj"),
                                {"obj": {"mutable": False}})
        self.assertTrue(any("writable" in e for e in errs), errs)
        errs = _lifetime_errors("lt", ctor(False, True, "obj"), {"obj": None},
                                arg_depth_by_name={"obj": 2})
        self.assertTrue(any("it is `alloc`" in e for e in errs), errs)

    def test_modes_are_explicit_and_exclusive(self):
        errs = _lifetime_errors("lt", ctor(True, True, "return"), {}, has_ret=True)
        self.assertTrue(any("mutually exclusive" in e for e in errs), errs)
        errs = _lifetime_errors("lt", {"for": "obj",
                                       "is_constructor": {"init": True}},
                                {"obj": None})
        self.assertTrue(any("alloc: must be an explicit boolean" in e
                            for e in errs), errs)

    def test_a_constructor_plays_no_other_role(self):
        lf = {**ctor(False, True, "obj"), "is_disposer": True}
        errs = _lifetime_errors("lt", lf, {"obj": None})
        self.assertTrue(any("plays no other role" in e for e in errs), errs)

    def test_an_empty_constructor_block_asserts_no_role(self):
        errs = _lifetime_errors("lt", ctor(False, False, "obj"), {"obj": None})
        self.assertTrue(any("asserts no role" in e for e in errs), errs)


class ExistingRoleTests(unittest.TestCase):
    """The earlier roles keep their rules."""

    def test_dropper_and_cloner_ownership(self):
        self.assertEqual(_lifetime_errors("lt", {"for": "o", "is_dropper": True},
                                          {"o": OWNED}), [])
        errs = _lifetime_errors("lt", {"for": "o", "is_dropper": True},
                                {"o": BORROWED})
        self.assertTrue(any("to be owned" in e for e in errs), errs)
        lf = {"for": "o", "is_cloner": {"deep": True, "upref": False}}
        self.assertEqual(_lifetime_errors("lt", lf, {"o": BORROWED}), [])


class LifecycleIndexTests(unittest.TestCase):
    def test_constructors_land_on_their_type_through_typedefs(self):
        types = [{"name": "foo_st", "typedef": "Foo"}]
        syms = [
            {"name": "foo_new", "ptr_args": [], "ptr_ret": {"type": "Foo"},
             "lifetime": ctor(True, False, "return")},
            {"name": "foo_init", "ptr_args": [{"name": "f", "type": "foo_st"}],
             "lifetime": ctor(False, True, "f")},
            {"name": "foo_parse", "ptr_args": [{"name": "out", "type": "Foo",
                                                "depth": 2}],
             "lifetime": ctor(True, False, "out")},
            {"name": "foo_free", "ptr_args": [{"name": "f", "type": "Foo"}],
             "lifetime": {"for": "f", "is_dropper": True}},
            {"name": "unrelated", "ptr_args": [{"name": "f", "type": "Foo"}],
             "lifetime": None},
        ]
        index = build_lifecycle_index((types, syms))
        entry = types[0]
        self.assertEqual(type_constructed_by(entry, index),
                         {"alloc": ["foo_new", "foo_parse"], "init": ["foo_init"]})
        self.assertEqual(type_method_syms(entry, index),
                         ["foo_free", "foo_new", "foo_parse", "foo_init"])


class ReturningDiscoveryTests(unittest.TestCase):
    """`--returning` finds allocators by their return, which `--taking` cannot:
    `malloc(size_t)` takes no `void *`."""

    SYMS = [
        {"name": "my_malloc", "defined_in": "mem.c", "ptr_args": [],
         "ptr_ret": {"type": "void", "depth": 1, "ptr": None}},
        {"name": "my_free", "defined_in": "mem.c",
         "ptr_args": [{"position": 0, "name": "p", "type": "void", "depth": 1}],
         "ptr_ret": None},
        {"name": "my_strdup", "defined_in": "str.c",
         "ptr_args": [{"position": 0, "name": "s", "type": "char", "depth": 1}],
         "ptr_ret": {"type": "char", "depth": 1, "ptr": None}},
    ]

    def run_query(self, **kw) -> dict:
        import io
        import json
        from contextlib import redirect_stdout
        from pathlib import Path
        from unittest.mock import patch

        from wavefront import query

        out = io.StringIO()
        with patch("wavefront.layout.Layout.discover", return_value=object()), \
                patch("wavefront.query._entries", return_value=self.SYMS), \
                redirect_stdout(out):
            query._taking(Path("."), calling=None, depth=1, array_only=False, **kw)
        return json.loads(out.getvalue())

    def test_returning_matches_the_return_only(self):
        d = self.run_query(spec="void", by_return=True)
        self.assertEqual(d["returning"], "void")
        self.assertEqual([r["symbol"] for r in d["candidates"]], ["my_malloc"])
        self.assertEqual(d["candidates"][0]["returns"][0]["name"], "return")

    def test_taking_still_matches_args_only(self):
        d = self.run_query(spec="void")
        self.assertEqual([r["symbol"] for r in d["candidates"]], ["my_free"])

    def test_returning_string_uses_the_char_family(self):
        d = self.run_query(spec="string", by_return=True)
        self.assertEqual([r["symbol"] for r in d["candidates"]], ["my_strdup"])


if __name__ == "__main__":
    unittest.main()
