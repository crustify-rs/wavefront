# Batching

`wavefront schedule` orders the units of a config's closure and keeps those
its `schedule_seeds` names, with what they depend on, in waves of batches. It
reads the dependency graph of the closure ([`graph.md`](graph.md)) and its seeds
([`scoping.md`](scoping.md#schedule-seeds)); field meaning of the output is in
[`artifacts/schedule.md`](artifacts/schedule.md).

## Units

The units are every node the closure owns
([`scoping.md`](scoping.md#closure)), its enums included, and every macro the
closure's files define and the graph holds, a header's included: a header
macro is not owned, since C still built may include it, but its Rust
counterpart is still to be written. The graph holds a header macro the closure
expands, one that mints a type the closure reaches, and every one an
`api_headers` file defines but its include guard
([`scoping.md`](scoping.md#default-mode)); a header macro nothing expands and
no header publishes is no unit.
With `--api-headers-only`, they are the owned nodes the api view
publishes, closed over the public-signature graph: a private type a public
signature names is a unit too, as is a macro it reaches. External nodes are
never units; they stay dependencies of the units that reach them.

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

Without caps, a wave holds two batches: one of its structs, unions, enums
and generator macros, then one of its functions, globals, other macros,
function pointers and typedefs. Its consumer splits them by the items' statistics
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

- a struct, union or enum is **opaque** after its **layout users**: the
  functions, globals and aggregates that read its members, name an enum's
  enumerators, take its size, alignment or an offset into it, hold it by
  value, or step a pointer over it (`t2/layout_uses.csv`). Once all of them
  are processed, what remains holds it only through pointers. A type held by
  value inside another is also used by every layout user of its holder,
  transitively, since they depend on the holder's layout and so on its own.
  An enum is used whole wherever it is used at all, so once it is opaque C
  holds it, if at all, only through a pointer;
- a struct or union's memory is **unmanaged** after its **raw sites**: the functions
  that allocate it with an allocator of untyped memory, or free or dispose
  of it with a releaser of untyped memory. Once all of them are processed,
  no C hands its storage to C's allocator, and a consumer may move it to
  another. Its own constructors, destructors and cloners are functions like
  any other, unreferenced after their callers: what they call does not
  matter to C, which only calls them;
- a function, global, macro, function pointer or typedef is
  **unreferenced** after its **referrers**: the units that call it, take its
  address, access it, expand it or name it, the edges of the body-deep graph
  into it. A macro's referrers are the functions whose bodies expand it,
  through another macro's expansion too, and the types whose declarations do
  (`char buf[GIT_OID_MAX_SIZE]`). A function pointer a typedef declares is
  referred to by what names the typedef or an alias of it, and by the code
  that calls through it;
- a function pointer written inline has no name, so C needs its signature
  for as long as anything reaches a **site** that writes it. Its users are
  each site and what reaches the site from outside:

  | site | reached by |
  |---|---|
  | a struct's field | the struct's layout users: `s->open(...)` reads the field |
  | a function's parameter or return | the function's referrers, which pass or receive it |
  | a global | the global's referrers |
  | a function's local, or a cast in it | nothing: only the function sees it |

  One signature written at several sites of its file is one function
  pointer, and has the users of every site.

Users are read off the body-deep graph, the layout-use table and, for raw
sites, `t2/arg_casts.csv`. Only the closure's units count: an external
function or a test the closure leaves out is no user. A macro is no layout
user either, since its uses are recorded where it is expanded.

A schedule made with `--api-headers-only` has no release points: its items'
`opaque_after`, `memory_unmanaged_after` and `unreferenced_after` are `null`. It binds what the
headers publish and keeps the C behind it, so nothing it schedules retires a
layout or an export, and its order, the API graph's, does not hold most of
the users.

Each item records its release points, `opaque_after` and `memory_unmanaged_after`
or `unreferenced_after`
([`artifacts/schedule.md`](artifacts/schedule.md#release-points)); their
users are a query away, `query structs --layout-users`, `query structs
--raw-sites` and `query functions --callers`.
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

### Raw sites

The raw routines are the ownership store's: a lifecycle role on a
type-erased pointer ([`type-lifecycle.md`](type-lifecycle.md)), a dropper,
a disposer or an out-parameter allocator acting on its `void *` parameter,
an allocator or a deep cloner returning new untyped storage. They are the
`void` lifecycle, established while planning; a store without them knows no
raw site, and `memory_unmanaged_after` is `null`. A role on a typed pointer is no
raw routine, whatever it calls.

A raw site is one conversion `t2/arg_casts.csv` records at a raw routine's
parameter or return, and its type is what the conversion's other end holds,
nothing being followed further:

| the other end | the type |
|---|---|
| a value of a named type: `free(db)`, `db = malloc(...)` | that type |
| a slot declared to hold one: a typed parameter, field or return | that type |
| a `void *` parameter | the one type its body reads it as, or what T3 `erased_arg` rows say it holds. A parameter read as several types is dispatched on (`opt_free_elem(type, void *ptr)`), and its free is one branch's: it names none |
| a `void *` field | every type stored into it or read out of it, less T3 `drop` rows, with T3 `erased_field` rows: freeing the field frees whatever any instance stored (`av_freep(&ctx->priv_data)`) |
| a scalar pointer: a byte or character buffer | none: it holds no struct |

A raw site on a type-erased end that names no type is unresolved: a byte
buffer in a `void *` field, a raw routine wrapping another, a generic
container's storage. A schedule warns of how many there are, and
`query structs --raw-sites --unresolved` lists them; T3 rows type those that
hold a struct. A named type's conversion carries no pointer depth, so the
storage of a `T **` array of pointers counts as `T`'s, which errs late.
