"""Compose objective-neutral target inventory from ``wavefront-config.json``.

`wavefront-config.json` names TWO file sets, always, whatever the campaign:

  `impl_files`   the sources (and private headers) that IMPLEMENT the library
  `api_headers`  the headers that PUBLISH its API

The `closure` section holds every entity defined in `impl_files` ∪
`api_headers`, `external` is its derived external closure, and the `api` view
is what `api_headers` declares.

Rules:

  1. A file is a *candidate* if the `included` list of `impl_files` or
     `api_headers` names it — directly, or through a trailing-slash
     directory entry that expands to every C/C++ source or header (`.c`,
     `.cc`, `.cpp`, `.h`, `.hpp`) beneath it.
  2. A candidate survives iff its repo-root-relative path does not match
     any entry of the same key's `excluded` list (entries ending with `/`
     match recursively; otherwise exact-file match).
  3. Everything an entity of the closure REACHES but that neither key names
     is external, derived by `import_closure.py` into the sibling `external`
     section — the campaign's EXTERNAL dependencies.

Alongside them, the `api` view: what `api_headers` PUBLISHES, selected on
DECLARATION sites. Not a section — it overlaps both, because publication and
location are independent questions.

Inventory shape:

    {
      "_comment": "...",
      "api":      {"files": [...], "functions": [...], ...},
      "closure":  {"files": [...], "functions": [...], ...},
      "external": {"files": [...], "functions": [...], ...}
    }
"""
from __future__ import annotations

import json
from pathlib import Path

try:  # package import (compose.scope_manifest) — the normal path
    from . import scope as _scope
except ImportError:  # script invocation fallback (python scope_manifest.py)
    import scope as _scope  # type: ignore

_SOURCE_EXTS = {".c", ".cc", ".cpp"}
_HEADER_EXTS = {".h", ".hpp"}
_ALL_EXTS = _SOURCE_EXTS | _HEADER_EXTS

_COMMENT = (
    "The CLOSURE section: every entity whose home file `wavefront-config.json` "
    "names. The candidate file universe is the `included` lists of "
    "`impl_files` + `api_headers` expanded (trailing-slash entries walked) "
    "minus their `excluded` lists; the ENTITY sets (functions/globals/macros/types) and the derived "
    "`files` list are then anchored on the CodeQL T1 tables, so they reflect "
    "the #ifdef-resolved (post-preprocessor) view of what the build actually "
    "compiled — a file whose body is elided by a disabled feature contributes "
    "no entities and therefore does not appear in `files`. Entities are keyed "
    "by (name, defined_in) because bare names collide (file-local statics). "
    "Classification (`classify`/`classify_type`, by location alone) runs "
    "ONCE here; downstream composers read these sets via "
    "`scope.load_entities` instead of re-deriving scope from the CSVs, and "
    "`scope.owned_entities` for the target's own (a header macro is in this "
    "section but not owned). Build-config-dependent by construction. "
    "Everything an entity here reaches that the config does not "
    "name is EXTERNAL, in the sibling section. Paths are repo-root-relative."
)


_API_COMMENT = (
    "The API view: every entity the `api_headers` set PUBLISHES, selected on "
    "DECLARATION-site membership (or definition, for something a header "
    "defines outright -- an inline function, a macro, a value struct). NOT a "
    "section: it cuts the PUBLICATION axis, orthogonal to the "
    "closure/external LOCATION split, so an entity appears here AND in "
    "whichever of those two holds it. A re-exported symbol declared here but "
    "defined outside the closure is `api` and `external` at once, which is "
    "exactly what a re-export is. Entries carry the same identity shape as "
    "every other set, so they collide with the dag nodes on (name, "
    "defined_in). This is what a `wrap` campaign schedules on, and what its "
    "dag seeds from."
)


def _is_excluded(rel_path: str, excluded: list[str]) -> bool:
    for pattern in excluded:
        if pattern.endswith("/"):
            if rel_path.startswith(pattern):
                return True
        elif rel_path == pattern:
            return True
    return False


def _walk_dir(rel_dir: str, repo_root: Path, excluded: list[str]) -> list[str]:
    """Every source/header file under ``rel_dir``, repo-root-relative."""
    base = repo_root if rel_dir in (".", "", "/") else (repo_root / rel_dir)
    base = base.resolve()

    files: list[str] = []
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix not in _ALL_EXTS:
            continue
        try:
            rel = str(p.resolve().relative_to(repo_root.resolve()))
        except ValueError:
            continue  # symlinks pointing outside repo_root; skip
        if _is_excluded(rel, excluded):
            continue
        files.append(rel)
    return files


#: The section of `wavefront-config.json` that names the program Wavefront
#: analyzes: the files of its graph, queries and usage counts. The inventory's
#: section of the entities those files define bears the same name, the same
#: constant: it is what this config section holds.
CLOSURE = _scope.CLOSURE
#: The section that seeds what `wavefront schedule` holds.
SCHEDULE = "schedule_seeds"
#: The two file-set keys of :data:`CLOSURE`.
IMPL_FILES = "impl_files"
API_HEADERS = "api_headers"
#: The two lists of each file-set key, and of a schedule entry's ``items``.
INCLUDED, EXCLUDED = "included", "excluded"
#: An item's kind: a type (struct, union or enum tag, or typedef) or a symbol
#: (function, global, macro or callback typedef), the two kinds of dag node. C
#: keeps tags apart from ordinary identifiers, so a tag and a function or
#: global may share a name in one file; nothing else can.
ITEM_KINDS = ("type", "symbol")

#: The section that groups the units a schedule orders.
MODULES = "modules"

_TOP_LEVEL = {"_comment", "state_dir", "t3_dir", CLOSURE, MODULES, SCHEDULE}
_SCHEMA_HINT = (
    '`closure` holds `impl_files` and `api_headers`, each '
    '{"included": [...], "excluded": [...]}, `excluded` optional; the optional '
    '`modules` groups the units a schedule orders, and the optional '
    '`schedule_seeds` names the units a schedule starts from. The top-level '
    '`impl_files`, `api_headers`, `items` and `out_of_scope` are gone.')


def closure(config: dict) -> dict:
    """The config's :data:`CLOSURE` section, its top level validated."""
    unknown = sorted(set(config) - _TOP_LEVEL)
    if unknown:
        raise SystemExit(
            f"wavefront-config.json: unknown top-level keys {unknown}. "
            f"{_SCHEMA_HINT}")
    value = config.get(CLOSURE)
    if not isinstance(value, dict) or not set(value) <= {IMPL_FILES, API_HEADERS}:
        raise SystemExit(
            f"wavefront-config.json: `{CLOSURE}` must be an object of "
            f"`{IMPL_FILES}` and `{API_HEADERS}`. {_SCHEMA_HINT}")
    return value


def _lists(holder: dict, key: str) -> tuple[list, list]:
    """``(included, excluded)`` of one file-set key of ``holder``, validated;
    both empty when the key is absent."""
    value = holder.get(key)
    if value is None:
        return [], []
    if not isinstance(value, dict) or not set(value) <= {INCLUDED, EXCLUDED}:
        raise SystemExit(
            f"wavefront-config.json: `{key}` must be an object of "
            f"`{INCLUDED}` and `{EXCLUDED}` lists. {_SCHEMA_HINT}")
    out = []
    for part in (INCLUDED, EXCLUDED):
        entries = value.get(part) or []
        if not isinstance(entries, list):
            raise SystemExit(f"wavefront-config.json: `{key}.{part}` must be a list")
        out.append(entries)
    return out[0], out[1]


def enumerate_files(holder: dict, repo_root: Path, key: str) -> list[str]:
    """Return the repo-root-relative candidate file paths ``holder[key]``
    names (the closure's :data:`IMPL_FILES` | :data:`API_HEADERS`, or any
    file set of that shape): its ``included`` entries, less what its
    ``excluded`` entries match.

    Always an explicit list — there is no implicit directory walk, so the key
    must name everything it covers. Entries are repo-root-relative
    and may be either:

      * a **file** — ``include/internal/statem.h``
      * a **directory**, written with a trailing slash — ``ssl/`` — which
        expands to every source/header file beneath it

    ``excluded`` entries follow the same trailing-slash convention, so the two
    lists read the same way, and ``excluded`` applies to whatever a directory
    entry of ``included`` expands to. Directory entries are what make
    "this whole subtree **plus** these specific headers" expressible: a
    port cluster often spans a tree it does not own, because the structs
    its code implements are declared in headers that live elsewhere.

    The result is only the *candidate* set; the T1 tables decide which of
    these actually compiled under the build configuration — so naming a
    file that the build never compiled is harmless, not an error.
    """
    entries, excluded = _lists(holder, key)

    files: list[str] = []
    for entry in entries:
        if entry.endswith("/"):
            files.extend(_walk_dir(entry, repo_root, excluded))
        elif not _is_excluded(entry, excluded):
            files.append(entry)
    return sorted(set(files))


def closure_candidates(config: dict, repo_root: Path) -> list[str]:
    """The candidate file set the ``closure`` section is composed against:
    ``impl_files`` ∪ ``api_headers``.

    Objective-neutral: coverage is a property of the files it names.
    """
    files = closure(config)
    return sorted(set(enumerate_files(files, repo_root, IMPL_FILES))
                  | set(enumerate_files(files, repo_root, API_HEADERS)))


def api_candidates(config: dict, repo_root: Path) -> list[str]:
    """The candidate file set the ``api`` view is composed against:
    ``api_headers`` alone."""
    return enumerate_files(closure(config), repo_root, API_HEADERS)


def _target_entities(t1_dir: Path, candidate_files: set[str]) -> dict[str, list[dict]]:
    """Classify every T1 entity against the candidate (config-named) file set
    and return the CLOSURE subset per kind.

    Reuses the single load-bearing classifier in `scope.py` — this is
    the ONE place section classification runs; downstream composers
    consume the result rather than re-deriving it from the CSVs. The
    rules mirror the per-row call sites exactly:

      - functions / globals → `classify` (definition-anchored, decl
        fallback).
      - macros → `classify` on their defining file, a header's included:
        the section is location alone. Which of them are the target's own (a
        `.c` TU's, not a header's) is `scope.owned_macro`, applied by the
        consumers that need it.
      - types → `classify_type` (typedef alias-chain resolution).

    Entities are keyed by (name, defined_in); `defined_in` may be empty for
    declaration-only entities.
    """
    funcs = _scope.load_csv(t1_dir / "functions.csv")
    globs = _scope.load_csv(t1_dir / "globals.csv")
    macros = _scope.load_csv(t1_dir / "macros.csv")
    types_rows = _scope.load_csv(t1_dir / "types.csv")
    by_name = _scope.build_types_index(types_rows)

    def _cls(r: dict) -> bool:
        return _scope.classify(
            r["def_file"], _scope.parse_decl_files(r["decl_files"]), candidate_files
        ) == _scope.CLOSURE

    # Every entry carries BOTH `defined_in` and `declared_in` (the latter the
    # def_file-empty complement: a null-def callback/extern/typedef is keyed by
    # its declaring header). `linkage` is dropped — never read off in-memory inventory.
    def _ent(r: dict, **extra) -> dict:
        return {"name": r["name"], "defined_in": r["def_file"],
                "declared_in": _scope.parse_decl_files(r.get("decl_files", "")),
                **extra}

    tgt_funcs = [_ent(r) for r in funcs if _cls(r)]
    tgt_globs = [_ent(r) for r in globs if _cls(r)]
    tgt_macros = []
    for r in macros:
        df = r["def_file"] or ""
        if _scope.classify(df, [df] if df else [], candidate_files) == _scope.CLOSURE:
            tgt_macros.append(_ent(r))
    # Types split: a callback is a function-pointer typedef — symbol-shaped, not
    # a layout type — so it is bucketed with `functions` (untagged), matching how
    # import_closure emits external callbacks, and so is a typedef of its own
    # (`scope.own_typedef`). An alias of a callback folds into it, and is no
    # entity. Everything else is a real type.
    tgt_types = []
    for r in types_rows:
        if _scope.classify_type(r, by_name, candidate_files) != _scope.CLOSURE:
            continue
        # An ANONYMOUS tag (`(unnamed enum)`, `(unnamed class/struct/union)`) is
        # a synthetic placeholder CodeQL reuses for every anonymous definition in
        # the DB, so it is not a name anything can reference or place: dozens of
        # distinct types collide on the one string. The analysis tree already
        # drops them (types.json carries none); this keeps in-memory inventory in
        # agreement. Their FIELDS are not lost — `entities/fields.ql` flattens an
        # anonymous member into its named parent under a qualified name.
        if str(r.get("name") or "").startswith("("):
            continue
        bucket = _typedef_bucket(r, by_name)
        if bucket == "functions":
            tgt_funcs.append(_ent(r))
        elif bucket == "types":
            tgt_types.append(_ent(r, kind=r["kind"]))
    # A function pointer written inline is homed in the file it is written in.
    for fp in inline_function_pointers(t1_dir):
        if _scope.classify(fp["defined_in"], fp["declared_in"],
                           candidate_files) == _scope.CLOSURE:
            tgt_funcs.append(fp)
    keyf = lambda e: (e["defined_in"], e["name"])
    return {
        "functions": sorted(tgt_funcs, key=keyf),
        "globals": sorted(tgt_globs, key=keyf),
        "macros": sorted(tgt_macros, key=keyf),
        "types": sorted(tgt_types, key=keyf),
    }


def _typedef_bucket(row: dict, by_name: dict[str, dict]) -> str | None:
    """The inventory bucket of a type row: ``functions`` for a function-pointer
    typedef that declares one and for a typedef of its own, ``None`` for an
    alias of a function-pointer typedef, which folds into it, and ``types``
    for every other."""
    cls = _scope.typedef_class(row, by_name)
    if cls is not None and cls[0] == _scope.FOLDS_CALLBACK:
        return "functions" if cls[1] is row else None
    if _scope.own_typedef(row, by_name):
        return "functions"
    return "types"


def inline_function_pointers(t1_dir: Path) -> list[dict]:
    """Every function pointer written inline (``t2/function_pointer_uses.csv``),
    one entity per signature and home file, as inventory entries: the
    signature is its name."""
    path = Path(t1_dir).parent / "t2" / "function_pointer_uses.csv"
    if not path.is_file():
        return []
    seen = {(r["signature"], r["def_file"]) for r in _scope.load_csv(path)
            if r.get("signature") and r.get("def_file")}
    return [{"name": sig, "defined_in": home, "declared_in": [home]}
            for sig, home in sorted(seen)]


def _api_entities(t1_dir: Path, api_files: set[str]) -> dict[str, list[dict]]:
    """Every T1 entity the ``api_headers`` set PUBLISHES, per kind.

    DECLARATION-anchored, and that is the whole point of the view. `closure`
    asks "where is this defined" and answers with the defining file; the API asks
    "what does this library publish", and a public header publishes exactly
    what it DECLARES — the bodies live in the `.c` files behind it. Anchoring
    this set on definitions instead would admit only what the headers happen to
    define (inline functions, macros, value structs) and drop every function
    they merely declare, which is most of an API.

    An entity qualifies if a named header is among its declaration sites, or is
    its definition site (an inline function or a struct defined in the header
    publishes itself). Entries carry the same ``{name, defined_in,
    declared_in}`` shape every other section uses, so ``origin_key`` still
    collides with the dag nodes and with the location sections: selection is by
    DECLARATION, identity stays by DEFINITION, and conflating the two is the
    bug this split exists to remove.
    """
    def _ent(r: dict, **extra) -> dict:
        return {"name": r["name"], "defined_in": r["def_file"],
                "declared_in": _scope.parse_decl_files(r.get("decl_files", "")),
                **extra}

    def _published(r: dict) -> bool:
        if (r.get("def_file") or "") in api_files:
            return True
        return any(d in api_files
                   for d in _scope.parse_decl_files(r.get("decl_files", "")))

    out: dict[str, list[dict]] = {"functions": [], "globals": [],
                                  "macros": [], "types": []}
    for csv_name, bucket in (("functions.csv", "functions"),
                             ("globals.csv", "globals"),
                             ("macros.csv", "macros")):
        for r in _scope.load_csv(t1_dir / csv_name):
            # A header's include guard is defined there, yet publishes nothing.
            if _published(r) and r.get("include_guard") != "1":
                out[bucket].append(_ent(r))
    type_rows = _scope.load_csv(t1_dir / "types.csv")
    by_name = _scope.build_types_index(type_rows)
    for r in type_rows:
        if not _published(r) or str(r.get("name") or "").startswith("("):
            continue
        # Same carve-out the closure section applies: a function-pointer
        # typedef, and a typedef of its own, are symbol-shaped, so they bucket
        # with `functions` rather than `types`.
        bucket = _typedef_bucket(r, by_name)
        if bucket == "functions":
            out["functions"].append(_ent(r))
        elif bucket == "types":
            out["types"].append(_ent(r, kind=r["kind"]))
    for fp in inline_function_pointers(t1_dir):
        if fp["defined_in"] in api_files:
            out["functions"].append(fp)
    keyf = lambda e: (e["defined_in"], e["name"])
    return {k: sorted(v, key=keyf) for k, v in out.items()}


def _contributing_files(
    t1_dir: Path, entities: dict[str, list[dict]], candidate_files: set[str]
) -> list[str]:
    """Derive the section's `files` list: every candidate file that is the
    definition site OR a declaration site of at least one of its entities.

    Drops `#ifdef`-elided files (zero entities → never a def/decl site)
    while keeping declaration-only headers. decl sites are pulled
    from the raw CSVs since the slim entity records omit decl_files.
    """
    files: set[str] = set()
    for kind in ("functions", "globals", "types", "macros"):
        for e in entities[kind]:
            if e["defined_in"] in candidate_files:
                files.add(e["defined_in"])
    keyset = {
        kind: {(e["defined_in"], e["name"]) for e in entities[kind]}
        for kind in ("functions", "globals", "types")
    }
    for csv_name, kind in (("functions.csv", "functions"),
                           ("globals.csv", "globals"),
                           ("types.csv", "types")):
        for r in _scope.load_csv(t1_dir / csv_name):
            if (r["def_file"], r["name"]) not in keyset[kind]:
                continue
            for d in _scope.parse_decl_files(r.get("decl_files", "")):
                if d in candidate_files:
                    files.add(d)
    return sorted(files)


def compose(config_path: Path, t1_dir: Path, repo_root: Path | None = None) -> dict:
    """Emit the manifest's `closure` section and its `api` view.

    `t1_dir` is `<state_dir>/codeql/t1` — the entity tables
    produced by `analyze extract-ql`. Expanding `files` gives the
    candidate universe; the T1 tables decide which files and entities
    actually compiled under this build configuration.

    `repo_root` is the CLI's first positional (per the Layout contract); it is
    **not** read from `wavefront-config.json`, so the same in-repo config stays
    portable across git worktrees. When omitted, it
    is derived from the configured `<state_dir>/codeql/t1` location of
    `t1_dir`.
    """
    config = json.loads(config_path.read_text())
    if repo_root is None:
        repo_root = t1_dir.resolve().parents[3]
    else:
        repo_root = Path(repo_root).resolve()
    candidate_files = set(closure_candidates(config, repo_root))
    entities = _target_entities(t1_dir, candidate_files)
    files = _contributing_files(t1_dir, entities, candidate_files)
    api_files = set(api_candidates(config, repo_root))
    api = _api_entities(t1_dir, api_files)
    api_contributing = _contributing_files(t1_dir, api, api_files)
    return {
        "_comment": _COMMENT,
        _scope.API: {
            "_comment": _API_COMMENT,
            "files": api_contributing,
            "functions": api["functions"],
            "globals": api["globals"],
            "macros": api["macros"],
            "types": api["types"],
        },
        _scope.CLOSURE: {
            "files": files,
            "functions": entities["functions"],
            "globals": entities["globals"],
            "macros": entities["macros"],
            "types": entities["types"],
        },
    }
