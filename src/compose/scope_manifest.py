"""Compose objective-neutral target inventory from ``wavefront-config.json``.

`wavefront-config.json` names TWO file sets, always, whatever the campaign:

  `impl_files`   the sources (and private headers) that IMPLEMENT the library
  `api_headers`  the headers that PUBLISH its API

`targeted` is `impl_files` ∪ `api_headers`, `imported` is its derived external
closure, and the `api` view is what `api_headers` declares.

Rules:

  1. A file is a *candidate* if the `included` list of `impl_files` or
     `api_headers` names it — directly, or through a trailing-slash
     directory entry that expands to every C/C++ source or header (`.c`,
     `.cc`, `.cpp`, `.h`, `.hpp`) beneath it.
  2. A candidate survives iff its repo-root-relative path does not match
     any entry of the same key's `excluded` list (entries ending with `/`
     match recursively; otherwise exact-file match).
  3. Everything an in-scope entity REACHES but that neither key names is
     imported, derived by `import_closure.py` into the sibling `imported`
     section — the campaign's EXTERNAL dependencies.

Alongside them, the `api` view: what `api_headers` PUBLISHES, selected on
DECLARATION sites. Not a section — it overlaps both, because publication and
ownership are independent questions.

Inventory shape:

    {
      "_comment": "...",
      "api":      {"files": [...], "functions": [...], ...},
      "targeted": {"files": [...], "functions": [...], ...},
      "imported": {"files": [...], "functions": [...], ...}
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
    "The TARGETED section: every entity whose home file `wavefront-config.json` "
    "names. The candidate file universe is the `included` lists of "
    "`impl_files` + `api_headers` expanded (trailing-slash entries walked) "
    "minus their `excluded` lists; the ENTITY sets (functions/globals/macros/types) and the derived "
    "`files` list are then anchored on the CodeQL T1 tables, so they reflect "
    "the #ifdef-resolved (post-preprocessor) view of what the build actually "
    "compiled — a file whose body is elided by a disabled feature contributes "
    "no entities and therefore does not appear in `files`. Entities are keyed "
    "by (name, defined_in) because bare names collide (file-local statics). "
    "Classification (`classify`/`entry_scope`/`classify_type`, including the "
    "header-macro carve-out) runs ONCE here; downstream composers read these "
    "sets via `scope.load_entities` instead of re-deriving scope from the "
    "CSVs. Build-config-dependent by construction. Everything an entity here "
    "reaches that the config does not "
    "name is IMPORTED, in the sibling section. Paths are repo-root-relative."
)


_API_COMMENT = (
    "The API view: every entity the `api_headers` set PUBLISHES, selected on "
    "DECLARATION-site membership (or definition, for something a header "
    "defines outright -- an inline function, a macro, a value struct). NOT a "
    "section: it cuts the PUBLICATION axis, orthogonal to the "
    "targeted/imported OWNERSHIP split, so an entity appears here AND in "
    "whichever of those two owns it. A re-exported symbol declared here but "
    "defined outside `impl_files` is `api` and `imported` at once, which is "
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


#: The two top-level file-set keys of `wavefront-config.json`.
IMPL_FILES = "impl_files"
API_HEADERS = "api_headers"
#: The entity lists that narrow a config's ownership: ``items.included`` and
#: ``items.excluded``.
ITEMS = "items"
#: The two lists of each of :data:`IMPL_FILES`, :data:`API_HEADERS` and
#: :data:`ITEMS`.
INCLUDED, EXCLUDED = "included", "excluded"
#: An item's kind: a type (struct, union or enum tag, or typedef) or a symbol
#: (function, global, macro or callback typedef), the two kinds of dag node. C
#: keeps tags apart from ordinary identifiers, so a tag and a function or
#: global may share a name in one file; nothing else can.
ITEM_KINDS = ("type", "symbol")

_SCHEMA_HINT = (
    'Each of `impl_files`, `api_headers` and `items` is '
    '{"included": [...], "excluded": [...]}, `excluded` optional; an item is '
    '{"name": ..., "defined_in": ..., "kind": "type"|"symbol"}. '
    '`out_of_scope` is gone: its `paths` go to the `excluded` lists of the '
    'file keys whose directories expand to them, its `items` to '
    '`items.excluded`.')


def _lists(config: dict, key: str) -> tuple[list, list]:
    """``(included, excluded)`` of one key, validated; both empty when the key
    is absent."""
    if "out_of_scope" in config:
        raise SystemExit(
            f"wavefront-config.json: `out_of_scope` is no longer read. {_SCHEMA_HINT}")
    value = config.get(key)
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
#: Where the composed manifest keeps the targeted entities a config's items
#: narrowed out, until `wavefront.scope.build` files them as imported.
NARROWED = "narrowed"

def enumerate_files(config: dict, repo_root: Path, key: str) -> list[str]:
    """Return the repo-root-relative candidate file paths ``config[key]`` names
    (:data:`IMPL_FILES` | :data:`API_HEADERS`): its ``included`` entries,
    less what its ``excluded`` entries match.

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
    entries, excluded = _lists(config, key)

    files: list[str] = []
    for entry in entries:
        if entry.endswith("/"):
            files.extend(_walk_dir(entry, repo_root, excluded))
        elif not _is_excluded(entry, excluded):
            files.append(entry)
    return sorted(set(files))


def targeted_candidates(config: dict, repo_root: Path) -> list[str]:
    """The candidate file set the ``targeted`` section is composed against:
    ``impl_files`` ∪ ``api_headers``.

    Objective-neutral: coverage is a property of the files it names.
    """
    return sorted(set(enumerate_files(config, repo_root, IMPL_FILES))
                  | set(enumerate_files(config, repo_root, API_HEADERS)))


def api_candidates(config: dict, repo_root: Path) -> list[str]:
    """The candidate file set the ``api`` view is composed against:
    ``api_headers`` alone."""
    return enumerate_files(config, repo_root, API_HEADERS)


def _target_entities(t1_dir: Path, candidate_files: set[str]) -> dict[str, list[dict]]:
    """Classify every T1 entity against the candidate (config-named) file set
    and return the TARGET subset per kind.

    Reuses the single load-bearing classifier in `scope.py` — this is
    the ONE place section classification runs; downstream composers
    consume the result rather than re-deriving it from the CSVs. The
    rules mirror the per-row call sites exactly:

      - functions / globals → `classify` (definition-anchored, decl
        fallback).
      - macros → `entry_scope` with the header-macro carve-out: a
        `#define` belongs to the target only when its home is a target
        `.c` TU.
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
        ) == _scope.TARGETED

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
        if _scope.entry_scope("macro", df, [df] if df else [], candidate_files) == _scope.TARGETED:
            tgt_macros.append(_ent(r))
    # Types split: a callback is a function-pointer typedef — symbol-shaped, not
    # a layout type — so it is bucketed with `functions` (untagged), matching how
    # import_closure emits import-side callbacks. Everything else is a real type.
    tgt_types = []
    for r in types_rows:
        if _scope.classify_type(r, by_name, candidate_files) != _scope.TARGETED:
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
        if r.get("unaliased_kind") == "callback":
            tgt_funcs.append(_ent(r))
        else:
            tgt_types.append(_ent(r, kind=r["kind"]))
    keyf = lambda e: (e["defined_in"], e["name"])
    return {
        "functions": sorted(tgt_funcs, key=keyf),
        "globals": sorted(tgt_globs, key=keyf),
        "macros": sorted(tgt_macros, key=keyf),
        "types": sorted(tgt_types, key=keyf),
    }


def _api_entities(t1_dir: Path, api_files: set[str]) -> dict[str, list[dict]]:
    """Every T1 entity the ``api_headers`` set PUBLISHES, per kind.

    DECLARATION-anchored, and that is the whole point of the view. `targeted`
    asks "whose body is this" and answers with the defining file; the API asks
    "what does this library publish", and a public header publishes exactly
    what it DECLARES — the bodies live in the `.c` files behind it. Anchoring
    this set on definitions instead would admit only what the headers happen to
    define (inline functions, macros, value structs) and drop every function
    they merely declare, which is most of an API.

    An entity qualifies if a named header is among its declaration sites, or is
    its definition site (an inline function or a struct defined in the header
    publishes itself). Entries carry the same ``{name, defined_in,
    declared_in}`` shape every other section uses, so ``origin_key`` still
    collides with the dag nodes and with the ownership sections: selection is by
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
            if _published(r):
                out[bucket].append(_ent(r))
    for r in _scope.load_csv(t1_dir / "types.csv"):
        if not _published(r) or str(r.get("name") or "").startswith("("):
            continue
        # Same callback carve-out the targeted section applies: a
        # function-pointer typedef is signature-shaped, so it buckets with
        # `functions` rather than `types`.
        if r.get("unaliased_kind") == "callback":
            out["functions"].append(_ent(r))
        else:
            out["types"].append(_ent(r, kind=r["kind"]))
    keyf = lambda e: (e["defined_in"], e["name"])
    return {k: sorted(v, key=keyf) for k, v in out.items()}


def _item_entries(where: str, entries: list) -> list[tuple[str, str, str]]:
    """The ``(name, defined_in, kind)`` triples of one entity list, validated."""
    out = []
    for i, e in enumerate(entries):
        if (not isinstance(e, dict) or set(e) != {"name", "defined_in", "kind"}
                or not all(isinstance(e[k], str) and e[k] for k in e)
                or e["kind"] not in ITEM_KINDS):
            raise SystemExit(
                f"wavefront-config.json: `{where}[{i}]` must be "
                f'{{"name": ..., "defined_in": ..., "kind": "type"|"symbol"}} '
                f"with non-empty strings")
        out.append((e["name"], e["defined_in"], e["kind"]))
    if len(set(out)) != len(out):
        raise SystemExit(f"wavefront-config.json: `{where}` repeats an entity")
    return out


def _narrow(entities: dict[str, list[dict]], config: dict,
            types_rows: list[dict]) -> tuple[dict, dict]:
    """Split the targeted ``entities`` into those the config owns and those
    its ``items.included`` / ``items.excluded`` narrow out.

    An entry matches an entity of its name and kind defined in its
    ``defined_in``, or, for an entity with no definition in the database,
    declared there. A typedef and the type it finally names are one group, so
    an entry selects both. A non-empty ``included`` keeps only what it names;
    ``excluded`` drops what it names. Only targeted entities can be named: an
    entry that matches none -- a header macro, which is never targeted, or an
    entity the config's files do not define -- is an error, as is an entity
    both lists name.
    """
    include_raw, exclude_raw = _lists(config, ITEMS)
    include = _item_entries(f"{ITEMS}.{INCLUDED}", include_raw)
    exclude = _item_entries(f"{ITEMS}.{EXCLUDED}", exclude_raw)
    if not include and not exclude:
        return entities, {k: [] for k in entities}
    both = sorted(set(include) & set(exclude))
    if both:
        raise SystemExit(
            f"wavefront-config.json: `{ITEMS}.{INCLUDED}` and "
            f"`{ITEMS}.{EXCLUDED}` both name "
            + ", ".join(f"{n} ({d}, {k})" for n, d, k in both))

    by_name = _scope.build_types_index(types_rows)

    def group(kind: str, e: dict) -> tuple[str, str, str]:
        if kind == "types" and e.get("kind") == "typedef":
            base = _scope.resolve_typedef(e["name"], by_name)
            if base is not None and base["kind"] != "typedef":
                return ("types", base["name"], base["def_file"])
        return (kind, e["name"], e["defined_in"])

    def matches(entry: tuple[str, str, str], bucket: str, e: dict) -> bool:
        name, file, kind = entry
        return (e["name"] == name
                and (bucket == "types") == (kind == "type")
                and (e["defined_in"] == file
                     or (not e["defined_in"] and file in e.get("declared_in", []))))

    def groups_of(entries: list[tuple[str, str, str]], where: str) -> set:
        out = set()
        for entry in entries:
            hit = {group(bucket, e) for bucket, es in entities.items()
                   for e in es if matches(entry, bucket, e)}
            if not hit:
                raise SystemExit(
                    f"wavefront-config.json: `{where}` names the {entry[2]} "
                    f"{entry[0]} ({entry[1]}), which the config's files do not "
                    f"define: only a targeted entity can be named, and a header "
                    f"macro never is")
            out |= hit
        return out

    selected = groups_of(include, f"{ITEMS}.{INCLUDED}") if include else None
    excluded = groups_of(exclude, f"{ITEMS}.{EXCLUDED}")
    owned, narrowed = {}, {}
    for kind, es in entities.items():
        owned[kind], narrowed[kind] = [], []
        for e in es:
            g = group(kind, e)
            keep = (selected is None or g in selected) and g not in excluded
            (owned if keep else narrowed)[kind].append(e)
    return owned, narrowed


def file_narrowed(manifest: dict) -> None:
    """File what the config's items narrowed out under ``imported``, once the
    imported section is composed.

    Narrowed-out entities are another config's work: imports here, nodes and
    dependencies of what reaches them, never units of this config.
    """
    imported = manifest[_scope.IMPORTED]
    for kind, entries in manifest.pop(NARROWED, {}).items():
        have = {(e["name"], e["defined_in"]) for e in imported.get(kind, [])}
        imported.setdefault(kind, []).extend(
            e for e in entries if (e["name"], e["defined_in"]) not in have)
        imported[kind].sort(key=lambda r: (r["name"], r["defined_in"]))


def _contributing_files(
    t1_dir: Path, entities: dict[str, list[dict]], candidate_files: set[str]
) -> list[str]:
    """Derive the port `files` list: every candidate file that is the
    definition site OR a declaration site of at least one port entity.

    Drops `#ifdef`-elided files (zero entities → never a def/decl site)
    while keeping declaration-only port headers. decl sites are pulled
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
    """Emit the manifest's `targeted` section and its `api` view.

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
    candidate_files = set(targeted_candidates(config, repo_root))
    entities, narrowed = _narrow(_target_entities(t1_dir, candidate_files), config,
                                 _scope.load_csv(t1_dir / "types.csv"))
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
        _scope.TARGETED: {
            "files": files,
            "functions": entities["functions"],
            "globals": entities["globals"],
            "macros": entities["macros"],
            "types": entities["types"],
        },
        NARROWED: narrowed,
    }
