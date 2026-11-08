# Batching

`wavefront schedule` orders the units of a config's closure and keeps those
its `schedule_seeds` names, with what they depend on, in waves of batches. It
reads the dependency graph of the closure ([`graph.md`](graph.md)) and its seeds
([`scoping.md`](scoping.md#schedule-seeds)); field meaning of the output is in
[`artifacts/schedule.md`](artifacts/schedule.md).

## Units

The units are every node the closure owns
([`scoping.md`](scoping.md#closure)): every node of the closure section but
the macros its headers define, which C still built may include and which
stay C's. With `--api-headers-only`, they are the owned nodes the api view
publishes, closed over the public-signature graph: a private type a public
signature names is a unit too. External nodes are never units; they stay
dependencies of the units that reach them.

Enums and macros are no units either, but for a type generator, which mints
types and is one wherever the closure defines it, a header included: an enum has no fields or
lifecycle to process, and a macro is expanded where it is used.
`--with-enums` makes the enums units, and `--with-macros` every macro the
closure's files define, a header's included.
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
recorded on both ends: the user lists the dependency, ordered after it, in its
`depends_on.cut`, and the dependency lists the user, ordered before it, in its
`depended_on_by.cut`. A cut between two modules is recorded on the user's module with
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

A unit no module claims, which the schedule warns of, is placed by what it
is:

- a dependency goes in the wave listed right before the first one that
  needs it, so that it arrives when it is needed. Before a module's wave,
  that is the module's previous wave, or a new wave of the module ahead of
  its first, so that the module's waves hold what it needs and its
  `sublayer`s count them all; the item itself still names no module. Before
  a wave with no module, it is a wave of its own;
- a seed keeps its place in the order, in a wave of its own listed before
  the module waves of its layer.

A wave with no module records the `layer` it is listed in. Without
`modules`, no unit is claimed and none is warned of: every wave has no
module, its `layer` its place in the units' order, and a dependency goes in
the previous layer's wave.

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

## Release points

A unit's users are processed in the order too, and each one's place tells a
consumer when the unit is no longer needed in its original form:

- a struct or union is **opaque** after its **layout users**: the functions,
  globals and aggregates that read its members, take its size, alignment or
  an offset into it, hold it by value, or step a pointer over it
  (`t2/layout_uses.csv`). Once all of them are processed, what remains holds
  it only through pointers. A type held by value inside another is also used
  by every layout user of its holder, transitively, since they depend on the
  holder's layout and so on its own;
- a function or global is **unreferenced** after its **referrers**: the units
  that call it, take its address or access it, the edges of the body-deep
  graph between functions and globals.

Users are read off the body-deep graph and the layout-use table. Only the
closure's units count: an external function, a test the closure leaves out,
or a macro, whose uses are recorded where it is expanded, is no user.

A schedule made with `--api-headers-only` has no release points: its items'
`opaque_after` and `unreferenced_after` are `null`. It binds what the
headers publish and keeps the C behind it, so nothing it schedules retires a
layout or an export, and its order, the API graph's, does not hold most of
the users.

Each item records its release point, `opaque_after` or
`unreferenced_after`
([`artifacts/schedule.md`](artifacts/schedule.md#release-points)); its users
are a query away, `query types --layout-users` and `query symbols --callers`.
The point is a frontier rather than one wave: the waves are listed in one
topological order, which puts a wave after others it does not depend on, so
the point is, of the unit's own wave and its scheduled users', those no other
one depends on, transitively through `depends_on.scheduled`. Its items are the users in
those waves, the unit itself when its own wave is one: within a wave nothing
is ordered, so each of them is a last user. A consumer that runs waves once
their dependencies complete has released the unit once all of them have; one
that runs them in their listed order, once the highest has. The modules
answer the same over the order of the modules, counting a user no module
claims toward the module whose wave holds it: a consumer that switches a
module whole, once its last wave has run, reads them rather than the waves,
since a user's wave can end before the module that holds it does.

Each point has two records, `closure` over every user and `scheduled` over
those the schedule holds. A narrow schedule may leave users out: a user
depends on the unit, not the other way round, so the unit's seeds need not
reach it. Its `scheduled` record then counts fewer users, and its waves are a
lower bound, while the `closure` record names the last users in the order of
the whole closure, which a narrow schedule keeps, and their modules.

The layout uses are syntactic, as every fact is
([`graph.md`](graph.md#assumptions-and-limitations)): a size written as a
number, or an offset computed by hand, reads no layout Wavefront can see, and
neither does a byte buffer copied without `sizeof` of the type, or a union
that puns it.
