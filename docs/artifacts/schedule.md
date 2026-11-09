# Schedule schema

Field meaning for the document `wavefront <repo> --config PATH schedule
--output PATH` writes. Complete example:
[`examples/schedule.json`](../../examples/schedule.json).

A schedule is objective-neutral: it orders and packs work without deciding
what a consumer does with it. It orders every unit of the config's closure in
the groups its `modules` make, keeps its `schedule_seeds` and every unit they
depend on, and emits one wave per sublayer of each module; a wave runs once
the waves it depends on have, and the batches within one wave may run at
once. A
consumer adds its own objective, grouping and concurrency. How units are
seeded, ordered and packed is in [`batching.md`](../batching.md).

The filename is not identity. `--output` accepts any path whose parent
directory already exists, so a consumer names schedules however its own layout
prefers. Wavefront never creates that directory.

## Version 5

```json
{
  "schema_version": 6,
  "oracle_config": {
    "path": "examples/wavefront-config.json",
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "api_headers_only": false,
  "caps": {"max_syms": null, "max_loc": null, "max_types": null, "min_fields": null},
  "summary": {"unit_count": 4, "seeded_count": 4, "module_count": 2,
              "wave_count": 3, "batch_count": 3, "cut_count": 0},
  "modules": [],
  "waves": []
}
```

`oracle_config` records the exact `--config` input as a repository-relative or
absolute path plus its SHA-256, so a consumer can reject a plan whose config is
missing or has changed since scheduling. `api_headers_only` records the
graph the schedule was made on, and `caps` the batch caps applied, `null` for
each one not given.

`summary` gives totals: the scheduled units, the seeds among them, the
modules that hold any, the waves, the batches, and the cut edges
with a scheduled end. Scheduled items occur exactly once, under their batch.

## Modules

```json
{
  "name": "src/widget.c",
  "layer": 1,
  "unit_count": 3,
  "waves": [1, 2],
  "depends_on": {
    "scheduled": [{"module": "src/mem.c", "unique_edges": 1, "total_edges": 1,
                   "via_dependency": []}],
    "cut": []
  }
}
```

One record per module that holds a scheduled unit, in their order.

| field | meaning |
|---|---|
| `name` | the module's name in the config's `modules` |
| `layer` | its layer in the order of the modules, their cycles cut |
| `unit_count` | the scheduled units it holds |
| `waves` | the indices of its waves |
| `depends_on.scheduled` | the modules its scheduled units depend on that are ordered before it, directly or through units no module claims: each one's `module`; the unit edges that reach its units, from this module's scheduled units or from the unclaimed units they depend on, as `total_edges`, and the distinct units of it they reach as `unique_edges`, what the order weighs; and `via_dependency`, the unclaimed units among those edges' ends. A narrow schedule counts only the edges it holds, so it names no module it leaves out |
| `depends_on.cut` | the modules it depends on whose edges were cut to break a cycle, as `scheduled`, with `items`: each crossing edge as `from` (this module's unit), `to` (the other module's unit) and the `kind` of `to`, as an item's |

A consumer that ships a module once its units are done reaches what a `cut`
record names across a module boundary that is still in the other language.

## Waves

```json
{
  "index": 2,
  "module": "src/widget.c",
  "sublayer": 1,
  "depends_on": {"scheduled": [0, 1], "cut": []},
  "unit_count": 2,
  "batches": [{"items": []}]
}
```

| field | meaning |
|---|---|
| `index` | the wave's position in `waves`, which lists them by layer, then by `sublayer`, then by module; a wave with no module is listed before the module waves of its layer, or, when it holds a dependency, right before the wave that needs it |
| `module` | the module whose units it holds, with the dependencies no module claims that the module needs first; `null` for a wave of seeds no module claims, or of what they alone need first |
| `sublayer` | on a module's wave: its place among its module's waves, from 0 |
| `layer` | on a wave with no module: the layer it is listed in, a seed's place in the order or that of the seed's wave it runs just before. Without `modules`, every wave's place in the units' order |
| `depends_on.scheduled` | the waves that must complete before it: its module's previous wave, and those that hold its units' dependencies, a cut one among them when it is listed before. A consumer that runs each wave once these complete runs every wave as early as it can |
| `depends_on.cut` | the waves listed after it that hold its units' cut dependencies: what it reaches before they run |
| `unit_count` | the items of its batches |
| `batches` | its batches; each batch's `items` is its exact worklist, of structs, unions, enums and generator macros, or of functions, globals, other macros, function pointers and typedefs, never both. A batch packed under a cap also records its `source_file`, a type batch's first type's defining file |

## Items

```json
{
  "name": "widget_new",
  "defined_in": "src/widget.c",
  "declared_in": ["include/widget.h", "src/widget.c"],
  "kind": "function",
  "seeded": true,
  "module": "src/widget.c",
  "loc": 36,
  "stats": {"static": false, "exported": true, "inline": false, "loc": 36,
            "params": 2, "pointer_params": 1, "erased_params": 0,
            "returns_pointer": true, "variadic": false, "callers": 0,
            "callees": 2, "field_accesses": 6},
  "depends_on": {
    "scheduled": [{"name": "widget_st", "defined_in": "include/widget.h",
                   "kind": "struct", "scope": "scheduled"},
                  {"name": "malloc", "defined_in": "/usr/include/stdlib.h",
                   "kind": "function", "scope": "external"}],
    "cut": []},
  "depended_on_by": {"cut": []},
  "type_generator_for": [],
  "used_fields": [],
  "opaque_after": null,
  "memory_unmanaged_after": null,
  "unreferenced_after": {
    "closure": {"users": 0,
                "items": [{"name": "widget_new", "defined_in": "src/widget.c",
                           "kind": "function", "module": "src/widget.c", "wave": 2}],
                "modules": ["src/widget.c"]},
    "scheduled": {"users": 0,
                  "items": [{"name": "widget_new", "defined_in": "src/widget.c",
                             "kind": "function", "module": "src/widget.c", "wave": 2}],
                  "waves": [2], "modules": ["src/widget.c"]}
  }
}
```

| field | meaning |
|---|---|
| `name`, `defined_in` | the graph node: its name and defining file (or canonical declaration file) |
| `declared_in` | every file that declares it, its definition included, by which a consumer groups or filters items |
| `kind` | what the C entity is: `function`, `global`, `macro`, `struct`, `union`, `enum`, `function_pointer`, or `typedef` ([`graph.md`](../graph.md#nodes)). A function pointer is named by the typedef declaring it, or by its signature when written inline. A generator macro is a `macro`, which `type_generator_for` tells apart |
| `typedefs` | the typedefs that name it and fold into it, a same-named one (`typedef struct ctx ctx;`) and aliases of aliases included, so that its consumer writes them with it: on a struct, union, enum or function pointer declared by a typedef; `[]` otherwise. The typedef that identifies an untagged type, or declares a function pointer, is its `name` |
| `seeded` | whether `schedule_seeds` names it; `false` for a unit scheduled because a seed depends on it |
| `module` | the module that claims it; `null` when none does. Its place in the order is its wave's |
| `loc` | a function's body line span, 1 for a global, 0 for a macro; a type's field count |
| `stats` | the properties of its declaration, its linkage among them, and the counts a consumer weighs its work by, below |
| `depends_on.scheduled` | the nodes it depends on whose edges were kept: a unit among them is scheduled before it |
| `depends_on.cut` | the units it depends on whose edges were cut to break a cycle: ordered after it, so it is processed before them |
| `depended_on_by.cut` | the reverse: the units ordered before it whose dependency on it was cut |
| `type_generator_for` | on a generator macro (T3 `type_generators.csv`), the instance types it mints, routed as one type so one generic is written for them; `[]` otherwise |
| `used_fields` | on a type, the fields its users reach: in API mode every field of a type an `api_headers` file defines, and none of a type defined elsewhere; otherwise the fields the closure's own functions access |
| `opaque_after` | on a struct, union or enum, the point after which none of its layout users is left ([Release points](#release-points)); `null` on any other item, and in an API schedule |
| `memory_unmanaged_after` | on a struct or union, the point after which none of its raw sites is left, no C allocating or freeing it with a raw routine; `null` on any other item, in an API schedule, and when the ownership store holds no raw routine |
| `unreferenced_after` | on a function, global or macro, a generator included, the point after which none of its referrers is left; `null` on any other item, and in an API schedule |

Each list holds references, each
`{"name": "...", "defined_in": "...", "kind": "...", "scope": "..."}`, so a
consumer needs no second node table. `kind` is the entity's, as an item's; an
external one's is the T1 tables', `null` when they do not say, as for a name
that two kinds bear. `scope` says where the entity sits, not what it is:

- `scheduled`: a unit of this schedule;
- `closure`: an entity of the config's closure this schedule does not hold;
- `external`: an entity outside the closure, such as a system header's.

### Release points

How users and release points are found is in
[`batching.md`](../batching.md#release-points). A user is a unit of the
closure, whether or not the schedule holds it. The users themselves are not
recorded: `query structs --name T --layout-users` lists a type's layout
users, with the sites and kinds of each use, `query structs --name T
--raw-sites` its raw sites, and `query functions --name F --callers` a
function's, global's or macro's referrers among the functions and globals; a
type whose declaration expands a macro is a referrer it does not list.

A release point, `opaque_after`, `memory_unmanaged_after` or `unreferenced_after`, has two records: the
point among every user, in the order of the whole closure, and the point among
the users this schedule holds, in its waves. They agree when the schedule
holds every user. Each record's candidates are the item and its users, and
its last are those no other candidate depends on, transitively: its frontier.

| field | meaning |
|---|---|
| `closure.users` | how many users the closure has |
| `closure.items` | of the item and its users, those no other one depends on in the order of the whole closure, over its kept edges |
| `closure.modules` | the same over the order of the modules, of the item's module and every user's |
| `scheduled.users` | how many of the users the schedule holds; fewer than `closure.users` when a narrow schedule leaves some out |
| `scheduled.waves` | of the item's wave and its scheduled users' waves, those no other one depends on through `depends_on.scheduled`. The highest index among them is always one: the listing is one topological order of the waves, and the others are those it orders before it without a dependency |
| `scheduled.items` | the item and its scheduled users whose wave is one of `scheduled.waves`: not every item of those waves |
| `scheduled.modules` | the same as `closure.modules`, over the item and its scheduled users |

An item is `{"name", "defined_in", "kind", "module", "wave"}`: `kind` is
the user's, as an item's: a function, global or macro, or an aggregate that
holds the type by value or declares itself with a macro; `module` is the module that claims it, `null` when none does;
and `wave` its wave, absent when the schedule does not hold it. A user no
module claims counts toward the module whose wave holds it. `modules` is
`null` without `modules`. An item with no user has itself as its release
point.

The two records can name different items even when they agree on the users:
the closure's are ordered by their dependencies, while a wave also follows
its module's previous wave, so a user can be last in the closure and not in
the schedule.

A schedule made with `--api-headers-only` has no release points, as
[`batching.md`](../batching.md#release-points) describes.

### Statistics

`stats` gives the properties of the item's declaration, then what it is made
of and how much of the codebase touches it, read off the T1/T2 tables. A use
counts only when
it sits in one of the closure's files, whatever the schedule holds: a test
suite or system header the closure does not name is no use. They are counts,
not weights: a consumer decides what each costs for its own work.

| item | properties | counts |
|---|---|---|
| struct, union, enum | `anonymous`: it has no tag, and the typedef that names it is its identity (`typedef struct { ... } T;`) | `fields`; of them `pointer_fields`, and of those `erased_fields` (`void *`); `field_touchers`, the functions that access a field, and `field_accesses`, their accesses |
| function | `static`: internal linkage; `exported`: external linkage, its opposite; `inline`: declared `inline`, apart from its linkage: a header's inline is `static inline` or an `extern` one | `loc`; `params`, of them `pointer_params`, and of those `erased_params`; `returns_pointer`; `variadic`; `callers` and `callees`, distinct functions; `field_accesses` in its body |
| global | `static` and `exported`, as a function's; `const`: the global itself, not what it points to (`char *const`, not `const char *`) | `pointer`; `erased`; `users`, the functions that access it |
| macro | `function_like`: it takes arguments | none |
| function pointer | none | none |
| typedef | `base_type`: what it names, as C writes it (`int64_t`, `unsigned char[8]`) | none |

A function pointer is a pointer, written inline or through a typedef. A
property the tables do not record is `null`: a function's linkage and
`inline` need `functions.csv` extracted with its `is_static` and `is_inline`
columns.

Schema-v5 schedules, which record `with_enums` and `with_macros` because
enums and macros were units only with those flags, give no enum an
`opaque_after` nor any macro but a generator an `unreferenced_after`, whose
items' and batches' `kind` is the route (`type`, `symbol`, `callback`), whose
items carry the tables' class as `source_kind`, whose `depends_on` lists
split their references into `types` and `symbols`, whose only typedefs are
callbacks, and whose items list no `typedefs`,
schema-v4 schedules,
which have no release points, schema-v3
schedules, sequential waves of one config's selection, and schema-v2
schedules with `steps`, `plan_items`, and `dependency_nodes` remain readable
historical records and need not be rewritten. New schedules are always
schema v6.
