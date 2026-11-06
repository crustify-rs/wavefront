"""Command line interface for semantic queries, findings, and scheduling.

    wavefront <repo_root> --config PATH extract-ql
    wavefront <repo_root> --config PATH query types   --name X [...]
    wavefront <repo_root> --config PATH query symbols --name X [...]
    wavefront <repo_root> --config PATH query dag     [...]
    wavefront <repo_root> --config PATH query files   [...]

Inventory and records are composed in memory. Dependency graphs use a private
fingerprinted cache. `extract-ql`, `query --update`, and `schedule --output`
are the only writes.

"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path



def _pin_hash_seed() -> None:
    """Run every CLI command with the hash seed used by parity fixtures."""
    if os.environ.get("PYTHONHASHSEED") == "0":
        return
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    os.execve(
        sys.executable,
        [sys.executable, "-m", "wavefront.cli", *sys.argv[1:]],
        env,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wavefront",
        description="Semantic analysis, ownership findings, and deterministic scheduling for C.",
    )
    p.add_argument(
        "repo_root",
        help="Full path to the repository root. Explicit — Wavefront never "
             "walks the filesystem to find it.",
    )
    p.add_argument(
        "--config", type=Path, metavar="PATH",
        help="Explicit wavefront-config.json for extraction, query, or schedule. "
             "Relative paths are resolved from REPO_ROOT.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "extract-ql",
        help="Run the T1 (entities) + T2 (edges) .ql batches against the "
             "CodeQL database below the config's state_dir and write one CSV per "
             "query under its codeql/{t1,t2}/. The database is NOT "
             "created here — build the project under `codeql database create` "
             "yourself first. Everything else derives from these tables on "
             "demand. Takes minutes — run it only "
             "when the extraction is genuinely stale.",
    )
    schedule = sub.add_parser(
        "schedule",
        help="Order every unit of the config's closure and schedule its "
             "`schedule_seeds` with what they depend on, one wave per layer.",
    )
    schedule.add_argument(
        "--output", type=Path, required=True, metavar="PATH",
        help="Write the schedule to this exact free-form path. Its parent "
             "directory must already exist.",
    )
    schedule.add_argument(
        "--api-headers-only", action="store_true",
        help="Seed from published declarations and stop symbol traversal at signatures.",
    )
    schedule.add_argument(
        "--with-enums", action="store_true",
        help="Schedule enums, which are skipped by default.")
    schedule.add_argument(
        "--with-macros", action="store_true",
        help="Schedule every macro the closure's files define; by default only "
             "type generators are.")
    schedule.add_argument(
        "--max-syms", type=int, default=None,
        help="Maximum symbols per batch (default: no cap).")
    schedule.add_argument(
        "--max-loc", type=int, default=None,
        help="Maximum summed symbol body LoC per batch (default: no cap).")
    schedule.add_argument(
        "--max-types", type=int, default=None,
        help="Maximum types per type batch (default: no cap).")
    schedule.add_argument(
        "--min-fields", type=int, default=None,
        help="Close a type batch at this declared-field floor (default: no cap).")
    _add_query_command(sub)
    return p


def _add_query_flags(p: argparse.ArgumentParser, *, facets: bool) -> None:
    """Flags for `query types`/`query syms` — the read-only oracle, resolved
    from composed records (dag-free). With no `--name` they enumerate (filtered by
    scope / `--file`) as a name list; with `--name T` they
    introspect one entry — always the WHOLE record (several names → several
    records). On a type, `--fields`/`--lifecycle-ops` print its windowable lists
    (`facets`)."""
    sc = p.add_mutually_exclusive_group()
    sc.add_argument("--external-only", action="store_true", dest="external_only",
                    help="Narrow to the EXTERNAL section — this campaign's "
                         "EXTERNAL dependencies: everything the closure "
                         "reaches that is defined outside it. Always derived, "
                         "in the objective-neutral inventory. Enumeration → "
                         "external entries; --lifecycle-ops/--users → external "
                         "functions. (Facets are complete by default.)")
    sc.add_argument("--closure-only", action="store_true", dest="closure_only",
                    help="Narrow to the CLOSURE section — every entity "
                         "defined in the files `wavefront-config.json`'s "
                         "`impl_files` + `api_headers` name, DEFINITION-anchored "
                         "(a closure header's macros included). "
                         "Objective-neutral. Enumeration → closure "
                         "entries; --lifecycle-ops/--users → closure functions; "
                         "--fields/--field-touchers → fields touched by the "
                         "closure's own code. (Facets are complete by default.) Says what the "
                         "campaign COVERS, not what one wave does with it — that "
                         "is `translate --objective`.")
    # NOT in the `sc` exclusive group: `api` is an AXIS, not a section. It cuts
    # PUBLICATION (does a named header declare it) where closure/external cut
    # LOCATION (where is it defined), so the two compose. `--api-only
    # --external-only` is the re-export query — published by this library,
    # defined by another — and refusing it would lose the one fact that
    # distinguishes a re-export from an ordinary import.
    p.add_argument("--api-only", action="store_true", dest="api_only",
                   help="Narrow to the API view — what `wavefront-config.json`'s "
                        "`api_headers` PUBLISHES, selected on DECLARATION "
                        "sites (a public header publishes what it declares; "
                        "the bodies live in the .c files behind it). This is "
                        "the set a `wrap` campaign translates. INTERSECTS with "
                        "--closure-only / --external-only rather than "
                        "excluding them: `--api-only --closure-only` is the "
                        "public surface this campaign also defines, and "
                        "`--api-only --external-only` is the re-export set.")
    og = p.add_mutually_exclusive_group()
    og.add_argument("--out-of-tree", action="store_true", dest="out_of_tree",
                    help="Enumeration only. Keep entries whose home is OUTSIDE the "
                         "repository (system / toolchain headers). Combines with the "
                         "scope flags: `--external-only --out-of-tree` is the permanent FFI "
                         "floor — code that can never move into the closure.")
    og.add_argument("--in-tree", action="store_true", dest="in_tree",
                    help="Enumeration only. Keep entries whose home is INSIDE the "
                         "repository. `--external-only --in-tree` is first-party code "
                         "wrapped only because this target does not port it — the "
                         "remaining port backlog.")
    p.add_argument("--name", nargs="+", action="extend", default=None, metavar="NAME",
                   help="No --name → enumerate; one → introspect; several → batch records.")
    p.add_argument("--file", nargs="+", default=None, metavar="FILE",
                   dest="files",
                   help="Restrict/disambiguate by defining file.")
    facet = p.add_mutually_exclusive_group()
    facet.add_argument("--update", default=None, metavar="FINDINGS",
                       help="Submit findings for the named entry (a path, or '-' "
                            "for stdin), in the shape of its record's `findings`: "
                            "validated as a whole, then merged into the ownership "
                            "store under a lock. See docs/artifacts/findings.md.")
    if facets:
        facet.add_argument("--fields", action="store_true",
                           help="Introspect a type: all declared fields, split into "
                                "their composed records and their findings; "
                                "--closure-only narrows to the fields the config's "
                                "own code reaches (--external-only does not apply).")
        facet.add_argument("--lifecycle-ops", action="store_true",
                           dest="lifecycle_ops",
                           help="Introspect a type: its LIFECYCLE surface only — "
                                "the droppers, field-disposers and cloners, "
                                "reverse-derived from the symbols whose `lifetime` "
                                "block acts on an arg of this type, ordered "
                                "lifecycle-first then alphabetically. This is the "
                                "canonical windowable list the translate scheduler "
                                "co-emits with the type. A strict subset of --users.")
        facet.add_argument("--users", action="store_true",
                           help="Introspect a type: its COMPLETE footprint — the "
                                "opaque_in ∪ non_opaque_in functions (every function "
                                "tree-wide that USES the type, as a handle or through "
                                "a field, incl. out-of-scope); "
                                "--closure-only/--external-only intersect with that section's "
                                "functions; '[]' if none. Wider than --lifecycle-ops, "
                                "and unordered.")
        facet.add_argument("--field-touchers", action="store_true",
                           dest="field_touchers",
                           help="Introspect a type: {field: [touchers]} — ALL "
                                "declared fields by default; --closure-only "
                                "narrows the FIELDS to the subset this target's "
                                "code reaches; --external-only does not apply. "
                                "each field's toucher set is the COMPLETE, unfiltered "
                                "set of functions that access it.")
    else:
        # Symbols-only REVERSE lifecycle lookup, parameterized by a TYPE (no
        # --name): which symbols drop / dispose / clone / construct TYPE, read
        # off each symbol's entry-level lifetime block.
        facet.add_argument(
            "--lifetime-for", default=None, metavar="SPEC", dest="lifetime_for",
            help="Reverse lifecycle lookup (READ: roles that already exist): "
                 "every symbol whose `lifetime` block (is_dropper/is_disposer/"
                 "is_cloner/is_constructor) acts on a subject matching SPEC, "
                 "grouped into the type's dropped_by / fields_disposed_by / "
                 "cloned_by / constructed_by. SPEC is "
                 "a struct tag / typedef, or the keyword `void` (raw byte-level, "
                 "untyped) or `string` (NUL-terminated; the char family or the "
                 "wrapper's own ptr.string verdict). The subject is the arg "
                 "named by `lifetime.for`, or the return for an alloc "
                 "constructor that returns its object (`for: \"return\"`), "
                 "so a symbol that merely "
                 "TAKES a SPEC arg without acting on it is not listed. No --name "
                 "needed.")
        facet.add_argument(
            "--taking", default=None, metavar="SPEC", dest="taking",
            help="CANDIDATE discovery (the inverse of --lifetime-for, which reads "
                 "flags that already exist): every symbol with an ARG matching "
                 "SPEC (tag / typedef / `void` / `string`). Pair with --calling "
                 "to keep only those that reach a lifecycle primitive. No --name "
                 "needed.")
        facet.add_argument(
            "--returning", default=None, metavar="SPEC", dest="returning",
            help="CANDIDATE discovery by RETURN: every symbol whose pointer "
                 "return matches SPEC (tag / typedef / `void` / `string`) -- "
                 "where allocators and `alloc` constructors hand their object "
                 "back, which --taking cannot see (`malloc(size_t)` takes no "
                 "`void *`). Pair with --calling to keep those that reach an "
                 "allocation primitive. No --name needed.")
        # The raw use-graph closure around a symbol. Distinct from `query dag
        # --name F --depth N`, which walks the ORDERING graph: scope-narrowed
        # (an external symbol contributes no callees at all) and carrying the
        # layering. These two walk the graph the C actually wrote.
        facet.add_argument(
            "--callees", action="store_true", dest="callees",
            help="Introspect a symbol: what it reaches, out to --depth hops "
                 "(default 1 = direct). The raw use graph from the composer's "
                 "depends_on.syms — codebase-wide, NOT narrowed by scope, so it "
                 "answers on a `wrap` campaign where `query dag` deliberately "
                 "shows nothing. Nodes come back as {name, defined_in}: the walk "
                 "is keyed on that pair, so same-named file-local statics never "
                 "merge. Needs --name; --file picks one of several.")
        facet.add_argument(
            "--callers", action="store_true", dest="callers",
            help="Introspect a symbol: what reaches IT, out to --depth hops — "
                 "the inverse of --callees over the same index, same output "
                 "shape. Needs --name.")
        p.add_argument(
            "--calling", default=None, metavar="FN[,FN...]", dest="calling",
            help="Narrow --taking / --returning to symbols that reach one of "
                 "these routines "
                 "within --depth hops (via the composer's depends_on.syms). "
                 "A dropper/cloner must ultimately reach a raw primitive -- but "
                 "the top-level one often does so through a helper, so >1 hop is "
                 "the norm (e.g. ASN1_STRING_free -> "
                 "ossl_asn1_string_free_internal -> CRYPTO_free is 2 hops). "
                 "Matches on NAME (a caller cannot know which file a helper was "
                 "defined in); each hit is reported with the file it resolved to.")
        p.add_argument(
            "--depth", type=int, default=1, metavar="N", dest="depth",
            help="Hop depth for --callees / --callers / --calling (default 1 = "
                 "direct edges only). Cycles are safe -- the walk is an "
                 "iterative BFS over a visited set, so a recursive cluster "
                 "terminates like anything else. NOT capped: every function "
                 "transitively reaches malloc, so depth is a precision/recall "
                 "trade the caller owns, and what a large one costs is output.")
        p.add_argument(
            "--array", action="store_true", dest="array",
            help="With --lifetime-for/--taking/--returning: keep only matches "
                 "whose ptr carries "
                 "an `array` shape (a buffer, not a lone pointee). Only "
                 "meaningful on an analyzed record.")


def _add_query_command(sub) -> None:
    """Attach the `query` verb and its subjects."""
    query_p = sub.add_parser(
        "query",
        help=(
            "Read-only oracle. `types`/`symbols` enumerate (filtered, as a name "
            "list) or introspect one (--name) as the whole record. "
            "`files` lists the closure / external section file sets. "
            "`dag` does the graph walks (closure / layer / scc)."
        ),
    )
    query_sub = query_p.add_subparsers(dest="subject", required=True)
    # The semantics below are NOT derivable from the flag list, and each one is
    # a mistake an agent otherwise makes: reading `lifetime: null` as "no role",
    # guessing at an ambiguous tag, and assuming scope narrows a lookup or an
    # emitted record's edges. Stated here so `--help` is the single authority.
    _SEMANTICS = (
        " SEMANTICS. `_analysis` on every record: `submitted` says whether the "
        "ownership store holds anything for this entity — `lifetime: null` "
        "alone cannot distinguish 'nobody looked' from 'an agent found no "
        "lifecycle role'; `pending` lists the pointer slots with no ownership "
        "block, counted per section under --closure-only/--external-only. "
        "A type carries no lifecycle of its own: dropped_by / "
        "fields_disposed_by / cloned_by are reverse-derived from the acting "
        "symbols' `lifetime` blocks. "
        "--file disambiguates and is REQUIRED when a name is ambiguous — a tag "
        "naming two unrelated structs both in this target's scope is refused, "
        "with the --file for each candidate printed; a name shared with a type "
        "OUTSIDE the scope is not ambiguous and resolves without it. "
        "Scope gates enumeration, not lookup: a listing is this target's "
        "inventory, but --name reaches every entity the extraction saw, so a "
        "type's destructor in another scope is readable, submittable through "
        "--update, and comes back from --lifetime-for. Scope gates emission, "
        "not content: an emitted record's depends_on / used_by are "
        "codebase-wide whatever its scope, so an external node's "
        "depends_on.syms is populated and safe to walk. "
        "Every graph walk here (--callees / --callers / --calling) is keyed on "
        "(name, defined_in), never on the bare name, and reports both halves: "
        "same-named file-local statics are distinct nodes, and merging them "
        "would step between unrelated functions at every hop. Submit through "
        "--update, never by editing a file."
    )
    _add_query_flags(
        query_sub.add_parser(
            "types", help="Types: enumerate, or introspect one (--name).",
            description=_add_query_flags.__doc__ + _SEMANTICS),
        facets=True)
    _add_query_flags(
        query_sub.add_parser(
            "symbols",
            help="Symbols: enumerate, or introspect one (--name).",
            description=_add_query_flags.__doc__ + _SEMANTICS),
        facets=False)

    files_q = query_sub.add_parser(
        "files",
        help="Scope files: --closure-only (the files the campaign names) or "
             "--external-only (its derived external dependency frontier).",
    )
    files_sel = files_q.add_mutually_exclusive_group()
    files_sel.add_argument(
        "--closure-only", action="store_true", dest="closure_only",
        help="Print the closure's files (in-memory inventory.closure.files). "
             "Computed identically for `port` and `wrap` campaigns.",
    )
    files_q.add_argument(
        "--api-only", action="store_true", dest="api_only",
        help="Print the API header set (in-memory inventory.api.files) — the headers "
             "that publish the library, T1-anchored.",
    )
    files_sel.add_argument(
        "--external-only", action="store_true", dest="external_only",
        help="Print the external section's files — entities reached by the "
             "closure but defined outside it, with files narrowed to the headers "
             "actually used (in-memory inventory.external.files). Objective-independent; "
             "a `wrap` campaign schedules the separate API view.",
    )

    dag_q = query_sub.add_parser(
        "dag",
        help="Structural dag views: transitive deps of --name T/S (closure), "
             "all nodes at --layer N (slice), or --name X --scc hi-deps/lo-deps "
             "(flattened-cycle twins X may use naked / that used X naked).",
        description=(
            "Structural dag views: transitive deps of --name T/S (closure), all "
            "nodes at --layer N (slice), or --name X --scc hi-deps/lo-deps "
            "(flattened-cycle twins X may use naked / that used X naked). "
            "OUTPUT: JSON grouped by kind — types / callbacks / functions / "
            "globals / macros, each {id, layer, defined_in} plus depth in "
            "closure mode; empty groups are omitted. The groups route the work: "
            "types to the type wrapper, callbacks and functions to the symbol "
            "wrapper, macros to no standalone unit (their consumers extend "
            "the owning -sys crate lazily). `layer` "
            "and `depth` exist only here — no other subject reports them."
        ),
    )
    dag_q.add_argument(
        "--name", nargs="+", action="extend", default=None, metavar="NAME",
        help="Entity (type tag / symbol) to query (closure or --scc mode).",
    )
    dag_q.add_argument(
        "--layer", type=int, default=None, metavar="N",
        help="Slice mode: return every node (type + symbol) at layer N "
             "(mutually exclusive with --name).",
    )
    dag_q.add_argument(
        "--scc", choices=("hi-deps", "lo-deps"), default=None,
        help="With --name X: hi-deps = X's fallback (higher-layer cycle twins "
             "X may use naked); lo-deps = X's back_fill (lower-layer twins that "
             "used X naked).",
    )
    dag_q.add_argument(
        "--file", nargs="+", default=None, metavar="FILE", dest="files",
        help="Narrow a --name to the nodes defined in these files.",
    )
    dag_q.add_argument(
        "--kind", choices=("type", "symbol"), default=None,
        help="Narrow a --name to its type or its symbol nodes. A name that "
             "still names several nodes resolves to all of them, listed under "
             "`matches` with their kinds and files.",
    )
    dag_q.add_argument(
        "--depth", type=int, default=None, metavar="N",
        help="Closure mode: limit to N hops (1 = direct deps, 2 = deps of "
             "deps, …; default: full transitive closure).",
    )
    dag_q.add_argument(
        "--loc", action="store_true", dest="loc",
        help="LoC view (with --name or --layer): a type seed → its struct "
             "field count + op count; a function seed → its body LoC; "
             "--layer N → the layer's total translated LoC (types valued as "
             "fields+ops; the bodies of folded type-ops are excluded — they "
             "ride their type at 1 each, not ported standalone).",
    )
    dag_q.add_argument(
        "--api-headers-only", action="store_true", dest="api_headers_only",
        help="Use the public-signature graph: no function bodies, public "
             "definitions keep fields, and forward declarations stay opaque.",
    )
    dag_q.add_argument(
        "--api-only", action="store_true", dest="api_only",
        help="Restrict the node set (slice / --loc) to the API view — what "
             "`api_headers` publishes. This is the schedulable set on a "
             "`wrap` campaign. Composes with the section flags.",
    )
    dag_scope = dag_q.add_mutually_exclusive_group()
    dag_scope.add_argument(
        "--external-only", action="store_true", dest="external_only",
        help="Restrict the node set (slice / --loc) to EXTERNAL entities "
             "(in-memory inventory's derived external section).",
    )
    dag_scope.add_argument(
        "--closure-only", action="store_true", dest="closure_only",
        help="Restrict the node set (slice / --loc) to CLOSURE entities "
             "(defined in the inventory's own file set — the library "
             "itself). Pair with --api-only for the public surface "
             "it defines.",
    )


def _dispatch_query(args: argparse.Namespace, target: Path) -> None:
    if args.subject == "files":
        from wavefront.query import query_files
        query_files(
            target,
            closure_only=bool(getattr(args, "closure_only", False)),
            external_only=bool(getattr(args, "external_only", False)),
            api_only=bool(getattr(args, "api_only", False)),
        )
        return
    if args.subject == "dag":
        from wavefront.query import query_dag
        query_dag(
            target,
            names=getattr(args, "name", None),
            files=getattr(args, "files", None),
            depth=getattr(args, "depth", None),
            scc=getattr(args, "scc", None),
            layer=getattr(args, "layer", None),
            loc=bool(getattr(args, "loc", False)),
            external_only=bool(getattr(args, "external_only", False)),
            closure_only=bool(getattr(args, "closure_only", False)),
            api_only=bool(getattr(args, "api_only", False)),
            api_headers_only=bool(getattr(args, "api_headers_only", False)),
            kind=getattr(args, "kind", None),
        )
        return
    from wavefront.query import query
    query(
        target,
        subject=args.subject,
        names=getattr(args, "name", None),
        files=getattr(args, "files", None),
        external_only=bool(getattr(args, "external_only", False)),
        closure_only=bool(getattr(args, "closure_only", False)),
        out_of_tree=bool(getattr(args, "out_of_tree", False)),
        in_tree=bool(getattr(args, "in_tree", False)),
        fields=bool(getattr(args, "fields", False)),
        api_only=bool(getattr(args, "api_only", False)),
        lifecycle_ops=bool(getattr(args, "lifecycle_ops", False)),
        users=bool(getattr(args, "users", False)),
        field_touchers=bool(getattr(args, "field_touchers", False)),
        update=getattr(args, "update", None),
        lifetime_for=getattr(args, "lifetime_for", None),
        taking=getattr(args, "taking", None),
        returning=getattr(args, "returning", None),
        calling=getattr(args, "calling", None),
        callees=bool(getattr(args, "callees", False)),
        callers=bool(getattr(args, "callers", False)),
        depth=int(getattr(args, "depth", 1) or 1),
        array=bool(getattr(args, "array", False)),
    )


def _main() -> None:
    _pin_hash_seed()
    from wavefront import extract as extract_mod
    from wavefront.layout import set_config_path, set_repo_root

    args = build_parser().parse_args()

    repo_root = Path(args.repo_root).resolve()
    set_repo_root(repo_root)

    for cond, msg in (
        (not repo_root.exists(), f"repo_root does not exist: {repo_root}"),
    ):
        if cond:
            print(f"error: {msg}", file=sys.stderr)
            sys.exit(1)

    if args.config is None:
        raise SystemExit(f"{args.command}: --config is required")
    config_path = args.config
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    config_path = config_path.resolve()
    if not config_path.is_file():
        raise SystemExit(f"{args.command}: config does not exist: {config_path}")
    set_config_path(config_path)
    args._config_path = str(config_path)
    scope = config_path

    if args.command == "extract-ql":
        extract_mod.extract_ql(repo_root)
        return

    if args.command == "schedule":
        from wavefront.layout import Layout
        from wavefront.schedule import build_schedule, write_wave
        layout = Layout.discover(scope)
        schedule = build_schedule(
            layout, scope, api_headers_only=args.api_headers_only,
            with_enums=args.with_enums, with_macros=args.with_macros,
            caps={"max_syms": args.max_syms, "max_loc": args.max_loc,
                  "max_types": args.max_types, "min_fields": args.min_fields})
        write_wave(args.output, schedule)
        s = schedule["summary"]
        print(f"[wavefront schedule] {s['unit_count']} unit(s), "
              f"{s['wave_count']} wave(s), {s['batch_count']} batch(es), "
              f"{s['cut_count']} cut(s) -> {args.output}")
        return
    if args.command == "query":
        _dispatch_query(args, scope)
        return
    raise SystemExit(f"wavefront: unknown command {args.command!r}")


def main() -> None:
    """Run the CLI, treating a closed stdout pipe as a successful consumer exit."""
    try:
        _main()
    except BrokenPipeError:
        # A downstream consumer such as `head` has all the records it needs.
        # Replace stdout so interpreter shutdown does not retry flushing the
        # already-closed pipe and turn this normal pipeline exit into status 120.
        sys.stdout = open(os.devnull, "w")


if __name__ == "__main__":
    main()
