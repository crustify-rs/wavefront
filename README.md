# Wavefront

Wavefront analyzes a C codebase and schedules its units in dependency order
for translation to Rust. It extracts entities and dependencies with CodeQL,
builds a cycle-free dependency graph of the codebase's types and symbols, and
packs that graph into ordered waves of batches. Each batch can be translated
once the waves before it are complete.

Wavefront keeps its analysis simple: it infers facts from the codebase without
data-flow or points-to analysis. It is built for neuro-symbolic workflows, in
which human or LLM reasoning complements its static facts. You can state the
polymorphic and type-erased edges it cannot infer; Wavefront loads them into
the dependency graph, and its schedules order units by them. You can also
record pointer-level ownership and lifecycle properties for each type and
symbol, which Wavefront returns with their records.

## Requirements

- Python 3.13 or newer
- The [CodeQL CLI](https://github.com/github/codeql-cli-binaries), on `PATH`

## Installation

```sh
git clone https://github.com/crustify-rs/wavefront.git
cd wavefront
python -m pip install -e .
codeql pack install src/
```

## Usage

```text
wavefront REPO_ROOT --config PATH COMMAND ...
```

`REPO_ROOT` is the root of the C repository. `--config` names its
`wavefront-config.json`; a relative path is resolved from `REPO_ROOT`.

### Configuration

```json
{
  "state_dir": ".wavefront",
  "impl_files": ["src/"],
  "api_headers": ["include/widget.h"],
  "out_of_scope": {"paths": ["src/tests/"]},
  "t3_dir": "t3"
}
```

| Key | Meaning |
|---|---|
| `state_dir` | Directory for the CodeQL database and tables, ownership findings, and caches. |
| `impl_files` | Sources and private headers that implement the library. |
| `api_headers` | Headers that publish the library's API. |
| `out_of_scope.paths` | Files excluded from `impl_files` and `api_headers`. |
| `t3_dir` | Optional. Directory, relative to `state_dir`, holding the T3 tables. |

Paths are relative to `REPO_ROOT`. A trailing slash selects a directory
recursively. See [`examples/wavefront-config.json`](examples/wavefront-config.json).

### 1. Extract

Build the project under CodeQL, then extract the T1 (entity) and T2 (edge)
tables into `<state_dir>/codeql/`:

```sh
codeql database create REPO_ROOT/.wavefront/codeql/db \
  --language=cpp --source-root=REPO_ROOT --command="make -j"
wavefront REPO_ROOT --config wavefront-config.json extract-ql
```

Run `extract-ql` again only when the database changes.

### 2. Query

```sh
wavefront REPO_ROOT --config PATH query {types,symbols,files,dag} [FLAGS]
```

| Subject | Output |
|---|---|
| `types` | Type records: fields, casts, users, and findings. |
| `symbols` | Symbol records: signatures, callers and callees, and findings. |
| `files` | The targeted, imported, and API file sets. |
| `dag` | Dependency closures, graph layers, and cycle twins. |

Common flags:

| Flag | Effect |
|---|---|
| `--name NAME ...` | Select entities by name. Without it, `types` and `symbols` list names. |
| `--file FILE ...` | Select or disambiguate entities by defining file. |
| `--targeted-only`, `--imported-only` | Keep entities the config owns, or the external ones it reaches. |
| `--api-only` | Keep entities the `api_headers` publish. |
| `--update FINDINGS` | Submit findings for one named entity (`-` reads stdin). |
| `--in-tree`, `--out-of-tree` | Listing only: keep entities defined inside, or outside, the repository. |

Type views (one `--name`):

| Flag | Effect |
|---|---|
| `--fields` | Print the declared fields and their records. |
| `--lifecycle-ops` | Print the routines that drop, dispose, clone, or construct the type. |
| `--users` | Print every function that uses the type. |
| `--field-touchers` | Print each field and the functions that access it. |

Symbol searches:

| Flag | Effect |
|---|---|
| `--taking SPEC` | Find functions with an argument of type `SPEC` (a type, `void`, or `string`). |
| `--returning SPEC` | Find functions that return a pointer of type `SPEC`. |
| `--lifetime-for SPEC` | Find the submitted lifecycle routines acting on `SPEC`. |
| `--calling FN,...` | With `--taking` or `--returning`, keep functions that reach one of `FN`. |
| `--callees`, `--callers` | Walk the call graph forward or backward from `--name`. |
| `--depth N` | Hop limit for the walks above; default `1`. |
| `--array` | Keep matches classified as arrays. |

Graph views (`query dag`):

| Flag | Effect |
|---|---|
| `--name NAME ...` | Print the dependency closure of the named nodes. |
| `--depth N` | Limit the closure to `N` hops. |
| `--layer N` | Print every node in layer `N`. |
| `--scc hi-deps\|lo-deps` | With `--name`, print the cycle twins recorded in `fallback` or `back_fill`. |
| `--loc` | Report estimated lines of code. |
| `--api-headers-only` | Use the public-signature graph. |

Examples:

```sh
# List the published types.
wavefront /src/widget --config wavefront-config.json query types --api-only

# Show one type's fields.
wavefront /src/widget --config wavefront-config.json \
  query types --name widget_st --fields

# Find functions that take widget_st and reach widget_release within 3 calls.
wavefront /src/widget --config wavefront-config.json \
  query symbols --taking widget_st --calling widget_release --depth 3

# Show the dependencies of widget_new.
wavefront /src/widget --config wavefront-config.json \
  query dag --name widget_new --depth 1
```

Each subject's `--help` lists its complete flags.

A type or symbol record has two parts: `composed`, which Wavefront derives
from the code, and `findings`, which users fill. `findings` lists every slot
the entity accepts, in the shape `--update` takes, so a user can fill it in
and submit it. See [`docs/artifacts/findings.md`](docs/artifacts/findings.md)
and [`examples/findings.json`](examples/findings.json).

### 3. Schedule

```sh
wavefront REPO_ROOT --config PATH schedule --output PATH SELECTION [FLAGS]
```

| Flag | Default | Effect |
|---|---:|---|
| `--output PATH` | | Required. Output file; its directory must exist. |
| `--name NAME ...` | | Select named types or symbols. |
| `--file FILE ...` | | Select every unit defined in these files. |
| `--dag-layer N` | | Select every unit in graph layer `N`. |
| `--lifetime-for void\|string` | | Emit the single raw-lifetime wave. |
| `--transitive` | | Add the selection's dependency closure. |
| `--skip NAME ...` | | Remove named units. |
| `--api-headers-only` | | Schedule the public API from the public-signature graph. |
| `--max-types N` | `2` | Types per type batch. |
| `--min-fields N` | `20` | Declared fields that close a type batch. |
| `--max-syms N` | `25` | Symbols per symbol batch. |
| `--max-loc N` | `500` | Body lines per symbol batch; `0` disables the limit. |

Example:

```sh
wavefront /src/widget --config wavefront-config.json schedule \
  --file include/widget.h --transitive --api-headers-only \
  --output /src/widget/waves.json
```

See [`examples/waves.json`](examples/waves.json) for the output.

## Documentation

| Document | Contents |
|---|---|
| [`docs/graph.md`](docs/graph.md) | The dependency graph: nodes, edges, type erasure, cycles, polymorphism, and limitations. |
| [`docs/scoping.md`](docs/scoping.md) | Targeted and imported entities, the API view, and default and API modes. |
| [`docs/batching.md`](docs/batching.md) | Selection, waves, and batch limits. |
| [`docs/pointer-properties.md`](docs/pointer-properties.md) | The pointer properties recorded in the ownership store. |
| [`docs/type-lifecycle.md`](docs/type-lifecycle.md) | Lifecycle roles, and how to find the routines that play them. |
| [`docs/artifacts/`](docs/artifacts/) | Field reference for type and symbol records, findings, the ownership store, schedules, and T3 tables. |

## Maintainers

- Marius Momeu, marius.momeu@berkeley.edu

## Acknowledgements

This material is based upon work supported by the Defense Advanced Research
Projects Agency (DARPA) Translating All C To Rust (TRACTOR) program under
Agreement No. HR00112590134.
