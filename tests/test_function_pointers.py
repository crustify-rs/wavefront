"""Function pointers and typedefs: every function pointer is an entity, the
typedef declaring one identifying it and an inline one identified by its
signature and home file; a typedef folds into the struct, union, enum or
function pointer it names, and is an entity of its own only when it names
none (`edges/function_pointer_uses.ql`,
`edges/function_pointer_signature_types.ql`, `compose.scope.typedef_class`)."""
from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from compose import scope
from wavefront.resources import data_root

FIXTURE = Path(__file__).parent / "fixtures" / "function_pointers"
QUERIES = ("edges/function_pointer_uses", "edges/function_pointer_signature_types")


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _key(r: dict) -> tuple:
    return tuple(r[k] for k in sorted(r))


class FunctionPointerQueryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("codeql"), "codeql not on PATH")
    def test_fixture_tables_match_golden(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db"
            subprocess.run(
                ["codeql", "database", "create", str(db), "--language=cpp",
                 "--source-root", str(FIXTURE),
                 "--command=gcc -std=c11 -c fp.c -o /dev/null"],
                check=True, capture_output=True)
            for query in QUERIES:
                name = query.split("/")[1]
                bqrs, out = Path(td) / f"{name}.bqrs", Path(td) / f"{name}.csv"
                subprocess.run(
                    ["codeql", "query", "run", f"--database={db}", f"--output={bqrs}",
                     str(data_root() / f"{query}.ql")], check=True, capture_output=True)
                subprocess.run(["codeql", "bqrs", "decode", "--format=csv",
                                f"--output={out}", str(bqrs)],
                               check=True, capture_output=True)
                got = [r for r in _rows(out)
                       if not any(str(v).startswith("/") for v in r.values())]
                with self.subTest(query):
                    self.assertEqual(sorted(map(_key, got)),
                                     sorted(map(_key, _rows(FIXTURE / f"{name}.csv"))))


class FunctionPointerGoldenTests(unittest.TestCase):
    uses = _rows(FIXTURE / "function_pointer_uses.csv")

    def test_every_inline_use_is_recorded(self) -> None:
        self.assertEqual(
            {(r["user_name"], r["use_kind"], r["signature"]) for r in self.uses},
            {("ops", "field", "int (*)(ctx *, const char *)"),
             ("ops", "field", "void (*)(ctx *)"),
             ("each", "param", "int (*)(ctx *, void *)"),
             ("pick", "return", "void (*)(ctx *)"),
             ("on_exit_hook", "global", "void (*)(void)"),
             ("run", "local", "int (*)(ctx *, void *)"),
             ("run", "cast", "int (*)(ctx *, void *)")})

    def test_a_typedef_declared_function_pointer_has_no_row(self) -> None:
        # `ops.visit` and `tell`'s `cb` are `visit_cb`'s, a typedef's.
        self.assertFalse({r["user_name"] for r in self.uses} & {"tell"})
        self.assertNotIn(("ops", "visit"), {(r["user_name"], r["use_line"])
                                            for r in self.uses})

    def test_an_inline_function_pointer_is_homed_where_its_user_is(self) -> None:
        self.assertEqual({r["def_file"] for r in self.uses}, {"fp.c"})


def _types(*rows) -> list[dict]:
    keys = ("name", "kind", "def_file", "decl_files", "aliases", "unaliased_kind")
    return [dict(zip(keys, r)) for r in rows]


TYPES = _types(
    ("ctx", "struct", "fp.c", "fp.c", "", ""),
    ("ctx", "typedef", "", "fp.c", "ctx", ""),
    ("ctx_t", "typedef", "", "fp.c", "ctx", ""),
    ("ctx_alias_t", "typedef", "", "fp.c", "ctx_t", ""),
    ("anon_t", "typedef", "fp.c", "fp.c", "", "struct_anonymous"),
    ("anon_alias_t", "typedef", "", "fp.c", "anon_t", ""),
    ("visit_cb", "typedef", "", "fp.c", "", "callback"),
    ("visit_alias_cb", "typedef", "", "fp.c", "visit_cb", ""),
    ("int64_t", "typedef", "", "/usr/include/stdint.h", "__int64_t", ""),
    ("__int64_t", "typedef", "", "/usr/include/types.h", "", "primitive"),
    ("fp_off_t", "typedef", "", "fp.c", "int64_t", ""),
    ("fp_pos_t", "typedef", "", "fp.c", "fp_off_t", ""),
    ("fp_handle", "typedef", "", "fp.c", "", "primitive"),
    ("iter", "typedef", "", "fp.c", "iter", ""),
    ("iter", "struct", "", "fp.c", "", ""),
)


class TypedefClassTests(unittest.TestCase):
    by_name = scope.build_types_index(TYPES)

    def cls(self, name: str) -> tuple[str, str]:
        row = next(r for r in TYPES if r["name"] == name and r["kind"] == "typedef")
        c, end = scope.typedef_class(row, self.by_name)
        return c, end["name"]

    def test_a_typedef_folds_into_what_it_names(self) -> None:
        self.assertEqual(
            {n: self.cls(n) for n in ("iter", "ctx", "ctx_t", "ctx_alias_t", "anon_t",
                                      "anon_alias_t", "visit_cb", "visit_alias_cb")},
            {"iter": ("aggregate", "iter"),
             "ctx": ("aggregate", "ctx"), "ctx_t": ("aggregate", "ctx"),
             "ctx_alias_t": ("aggregate", "ctx"), "anon_t": ("aggregate", "anon_t"),
             "anon_alias_t": ("aggregate", "anon_t"),
             "visit_cb": ("callback", "visit_cb"),
             "visit_alias_cb": ("callback", "visit_cb")})

    def test_a_typedef_that_names_none_is_its_own(self) -> None:
        own = {r["name"] for r in TYPES if scope.own_typedef(r, self.by_name)}
        # A system header's is a primitive to Rust, no entity.
        self.assertEqual(own, {"fp_off_t", "fp_pos_t", "fp_handle"})

    def test_a_typedef_of_its_own_classifies_by_its_own_declaration(self) -> None:
        row = next(r for r in TYPES if r["name"] == "fp_off_t")
        self.assertEqual(scope.classify_type(row, self.by_name, {"fp.c"}), scope.CLOSURE)


if __name__ == "__main__":
    unittest.main()
