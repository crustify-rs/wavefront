# crustify-oracle

Deterministic semantic analysis and scheduling for C-to-Rust work. It does not
run translation agents and does not know whether a campaign wraps or ports.

Python 3.13 or newer is required. Install with `python -m pip install -e .`.

```sh
crustify-oracle <repo> <target> extract-ql
crustify-oracle <repo> <target> query types --name TYPE
crustify-oracle <repo> <target> query symbols --name SYMBOL
crustify-oracle <repo> <target> query files --targeted-only
crustify-oracle <repo> <target> query dag --name NAME
crustify-oracle <repo> <target> schedule --output PATH --name NAME...
```

The authored target definition is
`<repo>/crustify/oracle/targets/<target>/oracle-config.json`:

```json
{
  "impl_files": ["src/"],
  "api_headers": ["include/public.h"],
  "out_of_scope": {"paths": []}
}
```

Both file sets are always inventory inputs. `schedule --api-headers-only`
selects declarations published by `api_headers`, follows signature and type
dependencies, includes fields of public definitions, and treats forward
declarations as opaque. Without it, scheduling uses implementation bodies and
full targeted layouts.

Scheduling owns semantic selection, dependency closure, topological steps, and
the `--max-syms`, `--max-loc`, `--max-types`, and `--min-fields` batch budgets.
It writes a schema-versioned, objective-neutral wave document to the exact
free-form path supplied with `--output`. The orchestrator must scaffold its
parent directory first; the oracle never creates output directories. The
translation runner supplies the wave objective and execution concurrency
later. Steps execute in order behind barriers, while their batches may execute
concurrently.

All semantic artifacts live under `<repo>/crustify/oracle/`:

- `codeql/{db,t1,t2}` — database and extracted facts
- `ownership-store.json` — submitted ownership findings
- `targets/<target>/oracle-config.json` — authored inventory
- `.cache/` — disposable deterministic caches

The inventory is composed in memory. There is no persisted `scope.json` or
`oracle.json`.

Before the first query subject, read its help. Submit findings only with
`query {types|symbols} --update`; never edit the ownership store directly.
