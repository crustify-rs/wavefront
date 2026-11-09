"""A macro is a unit wherever the closure defines it, a header included, as
libgit2's type generator `GIT_HASHMAP_STRUCT` in `src/util/hashmap.h` is; an
enum the closure owns is one too, and nothing the closure does not define is
one (docs/batching.md#units)."""
from __future__ import annotations

import unittest

from wavefront.dag import Node
from wavefront.schedule import is_unit

CLOSURE = {"src/util/hashmap.h", "src/libgit2/cache.c", "include/git2/oid.h"}
OWNED = {("git_cache_new", "src/libgit2/cache.c"), ("CACHE_LOCAL", "src/libgit2/cache.c")}


def _node(name, kind, subkind, defined_in, generates=()):
    n = Node(id=name, node_kind=kind, subkind=subkind, defined_in=defined_in,
             layer=0, dep_types=[], dep_syms=[])
    n.type_generator_for = list(generates)
    return n


class GeneratorUnitTests(unittest.TestCase):
    def unit(self, node, **kw):
        return is_unit(node, owned=OWNED, closure_files=CLOSURE, **kw)

    def test_a_header_generator_is_a_unit(self) -> None:
        gen = _node("GIT_HASHMAP_STRUCT", "symbol", "macro_function", "src/util/hashmap.h",
                    [("git_cache_oidmap", "src/libgit2/cache.h", "type")])
        self.assertTrue(self.unit(gen))

    def test_a_generator_outside_the_closure_is_not(self) -> None:
        gen = _node("SYS_LIST", "symbol", "macro_function", "/usr/include/sys/queue.h",
                    [("entries", "src/libgit2/cache.c", "type")])
        self.assertFalse(self.unit(gen))

    def test_every_closure_macro_is_a_unit(self) -> None:
        mac = _node("GIT_OID_MAX_SIZE", "symbol", "macro_object", "include/git2/oid.h")
        self.assertTrue(self.unit(mac))
        local = _node("CACHE_LOCAL", "symbol", "macro_object", "src/libgit2/cache.c")
        self.assertTrue(self.unit(local))

    def test_a_macro_outside_the_closure_is_not(self) -> None:
        mac = _node("INT_MAX", "symbol", "macro_object", "/usr/include/limits.h")
        self.assertFalse(self.unit(mac))

    def test_an_owned_enum_is_a_unit(self) -> None:
        enum = _node("git_oid_t", "type", "enum", "include/git2/oid.h")
        self.assertFalse(self.unit(enum))
        owned = is_unit(enum, owned=OWNED | {("git_oid_t", "include/git2/oid.h")},
                        closure_files=CLOSURE)
        self.assertTrue(owned)

if __name__ == "__main__":
    unittest.main()
