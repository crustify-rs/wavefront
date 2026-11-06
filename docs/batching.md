# Batching

`wavefront schedule` orders the units of a config's closure and keeps those
its `schedule_seeds` names, with what they depend on, in waves of batches. It
reads the dependency graph of the closure ([`graph.md`](graph.md)) and its seeds
([`scoping.md`](scoping.md#schedule-seeds)); field meaning of the output is in
[`artifacts/schedule.md`](artifacts/schedule.md).

## Units

The units are every targeted node of the closure, its header macros aside
([`scoping.md`](scoping.md#targeted)). With `--api-headers-only`, they are the
targeted nodes the api view publishes, closed over the public-signature
graph: a private type a public signature names is a unit too. Imported nodes
are never units; they stay dependencies of the units that reach them.

Enums and macros are no units either, but for a type generator, which mints
types and is one: an enum has no fields or lifecycle to process, and a macro
is expanded where it is used. `--with-enums` makes the enums units, and
`--with-macros` every macro the closure's files define, a header's included.
They are leaves of the graph, so leaving them out cuts nothing, but it can
lower the layer of what depends on them: two schedules agree on layers when
they are made with the same flags, which each records.

## Order

The units are ordered over all of them, whatever the seeds: their cycles
are cut ([`graph.md`](graph.md#cycles)) and they are layered by longest path.
Every edge a cut removes stays recorded on both ends: the user lists the
dependency, scheduled after it, in `higher_cuts`, and the dependency lists the
user, scheduled before it, in `lower_cuts`.

The schedule keeps the seeds and every unit they depend on, transitively,
the cut dependencies included: a cycle partner is still needed, after its
user. Each keeps its layer in the order, and `seeded` tells the seeds from
what came along. A schedule of the whole closure and a narrow one agree on
every unit's layer and cuts, so that the schedules of several seeds are parts
of one order, and so is any
grouping a consumer makes of a schedule's items by their `defined_in` and
`declared_in`.

## Waves

Each layer that holds a scheduled unit is a wave. Its units depend only on
units of lower layers, the cut edges aside, so the waves run in order and the
batches of one wave may run at once.

## Batches

Without caps, a wave holds one batch per route: a `type` batch of its types
and generator macros, then a `symbol` batch of its functions, globals and
callbacks. Its consumer splits them by the items' statistics
([`artifacts/schedule.md`](artifacts/schedule.md#items)).

Any cap packs each wave into batches, in name order, and lets adjacent
layers fold into one wave while their merged units still pack into a single
batch: one user then receives them in layer order, so a producer
still comes before its consumer. A fold never creates two batches, which
would run in parallel. A cap that is not given bounds nothing.

**Type batches** close before a type is added when they already hold
`--max-types` types, when the declared fields they hold reach `--min-fields`,
or when the new type alone has `--min-fields` fields or more. A wide type
therefore gets a batch of its own. A type batch's `source_file` is its first
type's defining file.

**Symbol batches** close before a symbol is added when they already hold
`--max-syms` symbols, or when the symbol's body LoC would take their total
past `--max-loc`. A symbol longer than `--max-loc` alone gets a batch of its
own; `--max-loc 0` disables the LoC cap.

| flag | bounds |
|---|---|
| `--max-types` | types in a type batch |
| `--min-fields` | declared fields that close a type batch, and isolate a wide type |
| `--max-syms` | symbols in a symbol batch |
| `--max-loc` | summed body LoC in a symbol batch |

The schedule records the caps under `caps`, `null` for each one not given.

## Used fields

Each type unit carries the fields its users reach (`used_fields`). An API
schedule lists every field of a type the `api_headers` define, and none of a
type defined elsewhere, whose layout the API does not publish. A default
schedule lists the fields the config's own functions access.
