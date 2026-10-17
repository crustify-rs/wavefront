"""macro_families.py — template-by-macro families.

A macro emitting a whole `typedef struct {…} name;` mints a family of
same-shaped types that C links in no way at all: no cast, no common tag, no
base. Downstream that means each instance is wrapped as an unrelated Rust
type, when the family wants ONE generic plus aliases.

WHICH macros are templates is not a fact of the source. `GIT_HASHMAP_STRUCT`
mints 24 same-shaped maps; `FF_PAD_STRUCTURE` mints `AVBPrint` and its
padding helper once, and is a definition. Counting instances in the
extracted build cannot tell them apart either -- `entry_short` mints its
SHA256 twin only behind `#ifdef GIT_EXPERIMENTAL_SHA256`. So the judgement
is the orchestrator's: it reads `t2/macro_generated_types.csv` (which
macro invocation minted which type, extracted) and writes the families it
accepts to the T3 table `type_generators.csv` (`compose/t3.py`). This module
reads that table only; with no T3, there are no generators.

The generator needs no node of its own: the MACRO is already an entity. So
the family hangs off it as `generates`, with `generated_by` on each
instance. A row may also name a macro the generator expands into a family
of its own (`derived_kind = macro`); that macro depends on its generator.

`generated_by` / `generates` is a DIRECTED relation, unlike `casted`: an
instance always depends on its generator, so the edge needs no inference.

**Scope** is the macro's own. `import_closure` admits a generator regardless
of call-site reachability (it expands at file scope, never from a function
body), and `wrap._is_macro` exempts it from "macros are bindgen's" — the
generic its instances alias is Rust this stage writes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from . import t3 as _t3
except ImportError:                       # script execution
    import t3 as _t3                      # type: ignore


def load(codeql_dir: Path, api_paths=None) -> dict[str, dict[str, Any]]:
    """``{macro: {"def_file", "members": [(tag, def_file)], "macros":
    [(macro, def_file)]}}`` for every generator in `type_generators.csv`.
    Empty when no T3 is configured. With `api_paths` (API mode), every
    generator must be defined in a public header."""
    fams: dict[str, dict[str, Any]] = {}
    for (macro, mdf), derived in _t3.load(Path(codeql_dir) / "t1",
                                          api_paths).generates.items():
        fams[macro] = {
            "def_file": mdf,
            "members": sorted((n, df) for k, n, df in derived if k == "type"),
            "macros": sorted((n, df) for k, n, df in derived if k == "macro"),
        }
    return fams


def generated_by(fams: dict[str, dict[str, Any]]) -> dict[tuple, tuple[str, str]]:
    """``{(tag, def_file): (macro, macro_def_file)}`` — the reverse index,
    for stamping instances. Keyed to the macro's own definition, so two
    same-named macros in different files stay apart."""
    out: dict[tuple, tuple[str, str]] = {}
    for m, f in fams.items():
        for tag, df in f["members"]:
            out[(tag, df)] = (m, f["def_file"])
    return out
