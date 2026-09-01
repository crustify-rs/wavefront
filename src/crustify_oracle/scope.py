"""scope.py — the per-target scope manifest, composed in memory.

`in-memory inventory` is a pure function of `oracle-config.json` (hand-authored) and the
CodeQL T1/T2 tables. Every stage read it off disk, which made it the one
artifact whose staleness a human could cause directly: edit `oracle-config.json`,
forget `analyze scope`, and wrap/query/dag all run against the previous port
set without a word. That is exactly the failure `dag.build` removed for the
graph, and the same fix applies — compose it, don't cache it.

Two halves, both composer-only:

  ``targeted``  from `oracle-config.json` + T1, ~0.12s
  ``imported``  the closure of ``targeted`` over T1/T2, ~1.4s (dominated by
                parsing `macro_expansions.csv` and friends)

Plus a cross-cutting ``api`` view: what ``api_headers`` PUBLISHES, selected on
declaration sites. Not a section — it overlaps both.

The inventory is objective-neutral. Graph depth is an explicit scheduling or
query option.

:func:`build` memoizes per `(repo_root, target)` for the life of the process,
which is what makes the multi-read commands cheap: `deps_dag.compose` alone
wants it twice, and `query` up to six times.

Nothing writes this inventory to disk.
"""
from __future__ import annotations

import sys
from pathlib import Path

from crustify_oracle.layout import Layout


#: (repo_root, target) -> composed manifest. Process-lifetime only: a stage is
#: one process, and the CSVs cannot change under it mid-run.
_CACHE: dict[tuple[str, str], dict] = {}


def build(layout: Layout, target: Path, *, stage: str) -> dict:
    """Compose this target's scope manifest — both sections plus the ``api``
    view — and return it.

    Raises ``SystemExit`` with a stage-tagged message when an input is missing,
    so a caller never has to pre-check.
    """
    ck = (str(layout.repo_root), str(target))
    hit = _CACHE.get(ck)
    if hit is not None:
        return hit

    from compose import scope_manifest as _sm
    from compose import scope as _scope
    from compose.import_closure import compose_import

    t1, t2 = layout.t1, layout.t2
    if not (t1 / "functions.csv").is_file():
        raise SystemExit(
            f"{stage}: no CodeQL T1 tables at {t1}. "
            f"Run `wavefront {target} extract-ql` first.")
    config_path = layout.config(target)
    if not config_path.is_file():
        raise SystemExit(
            f"{stage}: no oracle-config.json at {config_path}. It is authored by "
            f"hand — it names the implementation and API file sets — and "
            f"there is nothing to derive scope from without it.")
    includes_csv = t1 / "includes.csv"
    if not includes_csv.is_file():
        raise SystemExit(
            f"{stage}: no includes.csv at {includes_csv}. "
            f"Run `wavefront {target} extract-ql` first.")

    import json
    config = json.loads(config_path.read_text())
    manifest = _sm.compose(config_path, t1, layout.repo_root)
    target_paths = _scope.load_targeted_paths(manifest)
    # An empty file set means the campaign covers nothing. There is no implicit
    # walk to fall back on, so this is always a config error — a mistyped path,
    # or a list that never got filled in — and it would otherwise compose a
    # well-formed, entirely empty scope that every later stage reports as
    # "nothing to do".
    if not target_paths:
        raise SystemExit(
            f"{stage}: {config_path} selects no files. `{_sm.IMPL_FILES}` and "
            f"`{_sm.API_HEADERS}` are both empty, or name paths that nothing "
            f"under {layout.repo_root} matches, or name only files this build "
            f"never compiled (the sets are anchored on the T1 tables).")
    # The imported half needs the targeted half, and only that — it reads
    # no composed type or symbol records, so scope stands alone ahead of them.
    manifest[_scope.IMPORTED] = compose_import(
        t1, t2, manifest,
        _scope.load_csv(includes_csv),
        target_paths,
        _scope.load_csv(t1 / "types.csv"),
        _scope.load_csv(t2 / "field_type_uses.csv"),
    )
    _CACHE[ck] = manifest
    return manifest


def try_build(layout: Layout, target: Path) -> dict | None:
    """`build`, returning ``None`` instead of exiting when scope cannot be
    composed — for the callers that treat a scope-less target (``.``) as "no
    classification available" rather than an error.

    Call it only on the branch that needs scope. Composing costs ~1.5s, and the
    common oracle query (`query syms --name X` with no scope filter) has no
    business paying it.
    """
    try:
        return build(layout, target, stage="scope")
    except SystemExit:
        return None
