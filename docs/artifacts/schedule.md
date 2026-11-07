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

## Version 4

```json
{
  "schema_version": 4,
  "oracle_config": {
    "path": "examples/wavefront-config.json",
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "api_headers_only": false,
  "with_enums": false,
  "with_macros": false,
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
graph the schedule was made on, `with_enums` and `with_macros` whether enums
and macros are units, and `caps` the batch caps applied, `null` for
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
| `depends_on.cut` | the modules it depends on whose edges were cut to break a cycle, as `scheduled`, with `items`: each crossing edge as `from` (this module's unit), `to` (the other module's unit) and the `kind` of `to` |

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
  "batches": [{"kind": "symbol", "items": []}]
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
| `batches` | its batches; each batch's `kind` is its route (`type` or `symbol`), and `items` its exact worklist. A batch packed under a cap also records its `source_file`, a type batch's first type's defining file |

## Items

```json
{
  "name": "widget_new",
  "defined_in": "src/widget.c",
  "declared_in": ["include/widget.h", "src/widget.c"],
  "kind": "symbol",
  "source_kind": "function_exported",
  "seeded": true,
  "module": "src/widget.c",
  "loc": 36,
  "stats": {"loc": 36, "params": 2, "pointer_params": 1, "erased_params": 0,
            "returns_pointer": true, "variadic": false, "callers": 0,
            "callees": 2, "field_accesses": 6},
  "depends_on": {"scheduled": {"types": [], "symbols": []},
                 "cut": {"types": [], "symbols": []}},
  "depended_on_by": {"cut": {"types": [], "symbols": []}},
  "type_generator_for": [],
  "used_fields": []
}
```

| field | meaning |
|---|---|
| `name`, `defined_in` | the graph node: its name and defining file (or canonical declaration file) |
| `declared_in` | every file that declares it, its definition included, by which a consumer groups or filters items |
| `kind` | the route: `type` (a type, or a generator macro), `symbol`, or `callback` |
| `source_kind` | what the C entity is: `struct`, `union`, `enum`, `function_*`, `global_*`, `macro*`, `callback`, `external` |
| `seeded` | whether `schedule_seeds` names it; `false` for a unit scheduled because a seed depends on it |
| `module` | the module that claims it; `null` when none does. Its place in the order is its wave's |
| `loc` | a function's body line span, 1 for a global, 0 for a macro; a type's field count |
| `stats` | the counts a consumer weighs the item's work by, below |
| `depends_on.scheduled` | the nodes it depends on whose edges were kept: a unit among them is scheduled before it |
| `depends_on.cut` | the units it depends on whose edges were cut to break a cycle: ordered after it, so it is processed before them |
| `depended_on_by.cut` | the reverse: the units ordered before it whose dependency on it was cut |
| `type_generator_for` | on a generator macro (T3 `type_generators.csv`), the instance types it mints, routed as one type so one generic is written for them; `[]` otherwise |
| `used_fields` | on a type, the fields its users reach: in API mode every field of a type an `api_headers` file defines, and none of a type defined elsewhere; otherwise the fields the closure's own functions access |
| `cpp` | C++ only, absent otherwise: on a class, what its declarations state, with `lifecycle`, the special members folded into it ([`cpp.md`](../cpp.md#lifecycle)) |
| `member` | C++ only, absent otherwise: on a member function, the class it `implements` and what it is to it ([`syms.md`](syms.md#member)) |

Each list is split into `types` and `symbols` by route, a generator macro
among the types, and each reference in them is
`{"name": "...", "defined_in": "...", "scope": "..."}`, so a consumer needs no
second node table. `scope` is:

- `scheduled`: a unit of this schedule;
- `closure`: an entity of the config's closure that is no unit, such as a
  macro;
- `external`: an entity outside the closure, such as a system header's.

### Statistics

`stats` counts what the item is made of and how much of the codebase touches
it, read off the T1/T2 tables. A use counts only when it sits in one of the
closure's files, whatever the schedule holds: a test suite or system header
the closure does not name is no use. They are counts, not weights: a consumer
decides what each costs for its own work.

| item | counts |
|---|---|
| type | `fields`; of them `pointer_fields`, and of those `erased_fields` (`void *`); `field_touchers`, the functions that access a field, and `field_accesses`, their accesses |
| function | `loc`; `params`, of them `pointer_params`, and of those `erased_params`; `returns_pointer`; `variadic`; `callers` and `callees`, distinct functions; `field_accesses` in its body |
| global | `pointer`; `erased`; `users`, the functions that access it |

A function pointer is a pointer, written inline or through a typedef.

A macro or callback typedef has none: `{}`.

Schema-v3 schedules, sequential waves of one config's selection, and schema-v2
schedules with `steps`, `plan_items`, and `dependency_nodes` remain readable
historical records and need not be rewritten. New schedules are always
schema v4.
