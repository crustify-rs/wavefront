"""A tag a closure header only forward-declares, and a system header defines,
is no closure entity: its declaration-only row folds into the external
definition, so the tag stays an external leaf rather than a unit of the
schedule. The declaration fallback is for a tag defined nowhere."""
from __future__ import annotations

import unittest

from compose import scope


def _row(name: str, kind: str, def_file: str, decl_files: str) -> dict:
    return {"name": name, "kind": kind, "def_file": def_file,
            "decl_files": decl_files, "aliases": "", "unaliased_kind": ""}


TARGET = {"libfoo/print.h", "libfoo/print.c"}

ROWS = [
    # `struct tm;` in the target's header: a declaration-only row.
    _row("tm", "struct", "", "libfoo/print.h"),
    # glibc's definition, which the forward declaration folds into.
    _row("tm", "struct", "/usr/include/bits/types/struct_tm.h",
         "/usr/include/bits/types/struct_tm.h|libfoo/print.h"),
    # An opaque handle the target declares and nothing defines.
    _row("FooContext", "struct", "", "libfoo/print.h"),
]


class ExternalTagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.by_name = scope.build_types_index(ROWS)

    def test_forward_declaration_of_an_external_tag_is_external(self) -> None:
        self.assertEqual(
            scope.classify_type(ROWS[0], self.by_name, TARGET), scope.EXTERNAL)
        self.assertEqual(
            scope.classify_type(ROWS[1], self.by_name, TARGET), scope.EXTERNAL)

    def test_tag_defined_nowhere_is_in_the_closure_by_its_declarations(self) -> None:
        self.assertEqual(
            scope.classify_type(ROWS[2], self.by_name, TARGET), scope.CLOSURE)


if __name__ == "__main__":
    unittest.main()
