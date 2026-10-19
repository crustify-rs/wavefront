# Batching

`wavefront schedule` turns a selection of graph nodes into a schedule:
sequential waves, each a set of batches that may run concurrently, each
batch one agent's worklist. It reads the layers of the dependency graph
([`graph.md`](graph.md)); field meaning of the output is in
[`artifacts/schedule.md`](artifacts/schedule.md).

## Selection

1. **Seeds.** `--name`, `--file` and `--dag-layer` select nodes the config
   owns or imports ([`scoping.md`](scoping.md)). With `--api-headers-only`,
   only items the `api_headers` publish are seeds. A macro is never a unit
   unless T3 names it a generator. A name matching several nodes must be
   narrowed with `--file`.
2. **Closure.** `--transitive` adds every dependency of the seeds, walked
   over the graph's edges (not its cut `fallback` edges) and kept to the
   inventory. A name the walk reached resolves to the node it reached, not
   to a same-named twin elsewhere.
3. **Skips.** `--skip` removes named units.
4. **API ownership.** With `--api-headers-only`, imported items leave the
   selection: another config's `api_headers` own them, and that config's
   schedule wraps them. They stay dependencies of the units that reach them.

`--lifetime-for void|string` is separate: it emits one wave with one
synthetic `raw-lifetime` unit and selects nothing from the graph.

## Waves

The selected units are grouped by their graph layer. Each layer is a wave,
except that adjacent layers fold into one wave while their merged units
still pack into a single batch. One agent then receives them, in layer
order, so a producer still comes before its consumer; a fold never creates
two batches, which would run in parallel. Folding applies whether or not
`--transitive` chose the units.

Within an unfolded wave, no unit depends on another: they share a layer.
A cycle's cut edges are the exception the graph records, as `fallback` and
`back_fill`.

## Batches

Each wave is packed into batches by route, in selection order (by name for
`--transitive`, `--file` and `--dag-layer` selections).

**Type batches** hold types and generator macros. Before a type is added,
the open batch closes when it already holds `--max-types` types, when the
declared fields it holds reach `--min-fields`, or when the new type alone
has `--min-fields` fields or more. A wide type therefore gets a batch of
its own, and narrow types share one up to the type cap. A type batch's
`source_file` is its first type's defining file.

**Symbol batches** hold functions, globals and callbacks, kept apart by
section: targeted and imported symbols never share a batch. The open batch
closes before a symbol is added when it already holds `--max-syms` symbols,
or when the symbol's body LoC would take its total past `--max-loc`. A
symbol longer than `--max-loc` alone gets a batch of its own. `--max-loc 0`
disables the LoC cap.

| flag | default | bounds |
|---|---:|---|
| `--max-types` | 2 | types in a type batch |
| `--min-fields` | 20 | declared fields that close a type batch, and isolate a wide type |
| `--max-syms` | 25 | symbols in a symbol batch |
| `--max-loc` | 500 | summed body LoC in a symbol batch; `0` disables it |

The schedule records the applied values under `budgets`.

## Field anchors

Each type unit carries the fields its wrapper should expose
(`field_anchors`). An API schedule lists every field of a type the
`api_headers` define, and none of a type defined elsewhere, whose layout
stays opaque. A default schedule lists the fields the config's own
functions access.
