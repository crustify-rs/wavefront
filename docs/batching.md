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

The units are ordered over all of them, whatever the seeds, in groups: each
module's ([`scoping.md`](scoping.md#modules)), and each unit no module claims
alone, so that without `modules` every unit is a group of its own. An edge
between two groups weighs the distinct units the one depends on in the other:
a cut leaves each of them to a binding, however many edges reach it. A unit
edge weighs 1 ([`graph.md`](graph.md#cycles)). The groups' cycles are cut as the graph's
are: within each, the group the others depend on most, net of what it depends
on, comes first, and every edge from a group to one placed after it is cut.
The groups are layered by longest path: a module's `layer` is its place in
the order of the modules. Each module's units are then ordered within it,
their own cycles cut the same way, and layered by longest path.

Every unit edge a cut removes, between groups or within a module, stays
recorded on both ends: the user lists the dependency, scheduled after it, in
`higher_cuts`, and the dependency lists the user, scheduled before it, in
`lower_cuts`. A cut between two modules is recorded on the user's module with
the unit edges it crosses: what the module uses of a module ordered after it.

The schedule keeps the seeds and every unit they depend on, transitively, the
cut dependencies included: a cycle partner is still needed, after its user.
`seeded` tells the seeds from what came along. A schedule of the whole
closure and a narrow one agree on every unit's order and cuts, so that the
schedules of several seeds are parts of one order, and so is any grouping a
consumer makes of a schedule's items by their `defined_in` and `declared_in`.

## Waves

Each layer of a module's units is a wave, its `sublayer` its place among the
module's waves, from 0. A wave depends on its module's previous wave and on
the waves that hold its units' dependencies, the cut ones aside: a consumer
that runs each wave once those complete runs every wave as early as it can,
and one that runs the waves in their listed order, by layer and sublayer,
runs them correctly too, if later.

A dependency no module claims, which the schedule warns of, goes in the wave
right before the first one listed that needs it, so that work outside the modules arrives when they need
it. Before a module's wave, that is the module's previous wave, or a new wave
of the module ahead of its first, so that the module's waves hold what it
needs and its `sublayer`s count them all; the dependency's item still names
no module. Without `modules`, it is the previous layer's wave. A seed no
module claims keeps its place in the order instead, in a wave of its own
listed before its layer's module waves, with what it alone needs in waves of
their own just before it. Such a wave has no module, and the `layer` it is
listed in; without `modules`, every wave is one, and its `layer` is its place
in the units' order.

## Batches

Without caps, a wave holds one batch per route: a `type` batch of its types
and generator macros, then a `symbol` batch of its functions, globals and
callbacks. Its consumer splits them by the items' statistics
([`artifacts/schedule.md`](artifacts/schedule.md#items)).

Any cap packs each wave into batches, in name order, and lets a module's
adjacent layers of units fold into one wave while their merged units still pack into a
single batch: one user then receives them in layer order, so a producer
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
