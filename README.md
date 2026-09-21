# Wavefront

Deterministic semantic analysis and scheduling for C-to-Rust work. It does not
run translation agents and does not know whether a campaign wraps or ports.

Python 3.13 or newer is required. Install with:

```sh
python -m pip install -e .
```

## Inputs

Every command starts with the explicit repository root. Queries and schedules
also take the exact authored inventory config:

```text
wavefront REPO_ROOT [--config PATH] COMMAND ...
```

| Argument | Meaning |
|---|---|
| `REPO_ROOT` | Explicit repository root. The oracle never searches parent directories for it. |
| `--config PATH` | Required by every command. The `wavefront-config.json` to compose; relative paths resolve from `REPO_ROOT`. |

An authored `wavefront-config.json` may live anywhere. Campaign-wide and
narrowed scheduling configs may use any repository layout:

```json
{
  "state_dir": ".wavefront",
  "impl_files": ["src/"],
  "api_headers": ["include/public.h"],
  "out_of_scope": {"paths": []}
}
```

`state_dir` is the explicit repository-relative or absolute home for CodeQL
tables, ownership findings, and disposable caches. Inventory paths are
repository-relative. A trailing slash selects a directory
recursively. `impl_files` names implementation sources and private headers;
`api_headers` names the headers that publish the target API. Both sets are
always inventory inputs.

## Commands

### `extract-ql`

```sh
wavefront REPO_ROOT --config PATH extract-ql
```

Runs the bundled T1 entity and T2 edge queries against
`<state_dir>/codeql/db/`, writing CSVs under `<state_dir>/codeql/{t1,t2}/`. It
does not create the CodeQL database: build the project under
`codeql database create` first. Run extraction again only when the database or
query pack changes.

### `query`

```sh
wavefront REPO_ROOT --config PATH query SUBJECT [FLAGS]
```

`SUBJECT` is `types`, `symbols`, `files`, or `dag`. Queries are read-only
except for `query types --update` and `query symbols --update`.

#### Type and symbol records

With no `--name`, `query types` and `query symbols` enumerate names. One name
returns its complete record; several names return several complete records.

Flags shared by `types` and `symbols`:

| Flag | Meaning |
|---|---|
| `--name NAME [NAME ...]` | Introspect one or more entities instead of enumerating. The option may be repeated. |
| `--file FILE [FILE ...]` | Restrict enumeration or disambiguate entities with the same name by defining file. |
| `--targeted-only` | Keep entities owned by the configured target. Mutually exclusive with `--imported-only`. |
| `--imported-only` | Keep external dependencies reached by the target. Mutually exclusive with `--targeted-only`. |
| `--api-only` | Keep declarations published by `api_headers`. This axis composes with targeted/imported selection. |
| `--in-tree` | Enumeration only: keep entities defined inside the repository. Mutually exclusive with `--out-of-tree`. |
| `--out-of-tree` | Enumeration only: keep entities defined outside the repository. Mutually exclusive with `--in-tree`. |
| `--schema` | Print the record field definitions and invariants. No name is required. |
| `--update-help` | Print the JSON shape accepted by `--update`. No name is required. |
| `--update FINDINGS` | Validate and merge findings for exactly one named entity. Use a path or `-` for stdin. |

Type-only views require exactly one `--name`:

| Flag | Meaning |
|---|---|
| `--fields` | Print declared fields and their structural and ownership records. With `--targeted-only`, keep fields reached by target code. |
| `--lifecycle-ops` | Print the functions known to drop, dispose fields of, or clone the type. |
| `--users` | Print the complete function footprint of the type. Targeted/imported flags intersect that footprint. |
| `--field-touchers` | Print each field and all functions that access it. With `--targeted-only`, keep fields reached by target code. |

Symbol-only views:

| Flag | Meaning |
|---|---|
| `--lifetime-for SPEC` | Find submitted droppers, disposers, and cloners acting on a type, `void`, or `string`. No `--name` is needed. |
| `--taking SPEC` | Find candidate symbols with an argument matching a type, `void`, or `string`. No `--name` is needed. |
| `--calling FN[,FN...]` | With `--taking`, keep candidates that reach one of the named functions. |
| `--callees` | Walk outward from `--name` through the raw call graph. |
| `--callers` | Walk backward from `--name` through the raw call graph. |
| `--depth N` | Hop limit for `--calling`, `--callees`, or `--callers`; default `1`. |
| `--array` | With `--taking` or `--lifetime-for`, keep arguments classified as arrays. |

Examples:

```sh
# Enumerate the target's published types.
wavefront /work/project --config crustify/wavefront/wavefront-config.json \
  query types --api-only

# Inspect one type, then discover the findings schema.
wavefront /work/project --config crustify/wavefront/wavefront-config.json \
  query types --name widget_st --fields
wavefront /work/project --config crustify/wavefront/wavefront-config.json \
  query types --update-help

# Find functions that take widget_st and eventually call widget_release.
wavefront /work/project --config crustify/wavefront/wavefront-config.json \
  query symbols \
  --taking widget_st --calling widget_release --depth 3
```

#### File inventory

`query files` prints one path per line. With no selector it prints labeled API,
targeted, and imported sections.

| Flag | Meaning |
|---|---|
| `--api-only` | Print headers named by the API inventory. |
| `--targeted-only` | Print files owned by the target. |
| `--imported-only` | Print files in the derived external dependency closure. |

#### Dependency graph

`query dag` has three modes: `--name` prints a dependency closure, `--layer`
prints a complete topological layer, and `--name ... --scc` prints flattened
cycle neighbors. Output is JSON grouped into types, callbacks, functions,
globals, and macros.

| Flag | Meaning |
|---|---|
| `--name NAME [NAME ...]` | Seed a dependency closure, or select entities for `--scc`. |
| `--layer N` | Print every node at layer `N`; mutually exclusive with `--name`. |
| `--scc hi-deps\|lo-deps` | With `--name`, print higher-layer fallback twins or lower-layer back-fill twins from a flattened cycle. |
| `--file FILE [FILE ...]` | Disambiguate a named node by defining file. |
| `--depth N` | Limit closure traversal to `N` dependency hops; the default is the full closure. |
| `--loc` | Report translated LoC estimates for named entities or a layer. |
| `--api-headers-only` | Use the public-signature graph: omit function bodies, retain fields of public definitions, and keep forward declarations opaque. |
| `--api-only` | Restrict layer/LoC output to the published API view. |
| `--targeted-only` | Restrict layer/LoC output to target-owned entities. |
| `--imported-only` | Restrict layer/LoC output to imported entities. |

### `schedule`

```sh
wavefront REPO_ROOT --config PATH schedule --output PATH SELECTION [FLAGS]
```

Scheduling selects semantic units, optionally closes over their dependencies,
orders them into barrier-separated topological waves, and packs each wave into
batches. It writes an objective-neutral sub-campaign schedule; the translation runner
adds the wrap/port objective and execution concurrency later.

Selection and output flags:

| Flag | Meaning |
|---|---|
| `--output PATH` | Required. Write to this exact path; its parent directory must already exist. |
| `--name NAME [NAME ...]` | Select named types or symbols. The option may be repeated. |
| `--file FILE [FILE ...]` | Select every unit defined in these files, or narrow a named selection to them. |
| `--dag-layer N` | Select every eligible node at topological layer `N`; it may be combined with names. |
| `--lifetime-for void\|string` | Emit the synthetic raw-pointer or string-lifetime wave. This is exclusive of names, files, and layers. |
| `--transitive` | Include the selected units' in-scope dependency closure. |
| `--skip NAME [NAME ...]` | Remove named units after selection. The option may be repeated. |
| `--force` | Keep lifecycle primitives that normally ride with their owning type or raw-lifetime tier. |
| `--api-headers-only` | Seed from published declarations and traverse the public-signature graph rather than implementation bodies. |

Batch flags:

| Flag | Default | Meaning |
|---|---:|---|
| `--max-syms N` | `25` | Maximum symbols or callbacks in one symbol batch. |
| `--max-loc N` | `500` | Maximum summed symbol body LoC in one batch; `0` disables this cap. |
| `--max-types N` | `2` | Maximum types in one type batch. |
| `--min-fields N` | `20` | Close a type batch before adding another type once this declared-field threshold is reached; wide types are isolated. |

For example:

```sh
mkdir -p /work/project/crustify/campaigns/widget/logs

wavefront /work/project \
  --config crustify/campaigns/src/widget/wavefront-config.json schedule \
  --name widget_new widget_free \
  --transitive \
  --max-types 2 \
  --output /work/project/crustify/campaigns/widget/waves.json
```

Field meaning is in [`docs/schemas/schedule.md`](docs/schemas/schedule.md); the
complete schema-v3 output example is
[`examples/waves.json`](examples/waves.json). Its major sections are:

- `budgets` and `summary`: the applied packing settings and aggregate counts;
- `waves`: sequential, barrier-separated groups containing concurrently executable batches;
- `waves[*].batches[*].items`: every selected unit exactly once; dependency
  references carry `scope: wrap|port|ext`, so no duplicate plan or dependency
  table or wave-level layer copy is needed;
- `field_anchors`: fields a type wrapper should expose for this target.

Waves execute in order. Batches within a wave may execute concurrently.
Adjacent dependency layers are folded into one wave whenever their selected
units fit a single batch, whether or not `--transitive` selected the units.
Folding never produces parallel producer/consumer batches.

## Artifacts

All semantic artifacts live under the config's explicit `state_dir`:

- `codeql/{db,t1,t2}` — database and extracted facts;
- `ownership-store.json` — submitted ownership findings;
- `.cache/` — disposable deterministic caches.

Dependency-graph caches are content-addressed by the config hash, so identical
configs share a cache regardless of filename and editing a config cannot reuse
a stale graph.

The inventory is composed in memory. There is no persisted `scope.json` or
`oracle.json`. Before using a query subject for the first time, also read its
live `--help`; it is the authority for validation rules and edge cases. Submit
findings only with `--update`; never edit `ownership-store.json` directly.

## Acknowledgements

This material is based upon work supported by the Defense Advanced Research
Projects Agency (DARPA) Translating All C To Rust (TRACTOR) program under
Agreement No. HR00112590134.
