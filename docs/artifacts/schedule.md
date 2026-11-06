# Schedule schema

Field meaning for the document `wavefront <repo> --config PATH schedule
--output PATH` writes. Complete example:
[`examples/schedule.json`](../../examples/schedule.json).

A schedule is objective-neutral: it orders and packs work without deciding
what a consumer does with it. It orders every unit of the config's closure,
keeps its `schedule_seeds` and every unit they depend on, and emits
one wave per layer of the order;
the waves run in order, and the batches within one wave may run at once. A
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
  "summary": {"unit_count": 4, "seeded_count": 4, "wave_count": 2,
              "batch_count": 3, "cut_count": 0},
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
waves, the batches, and the cut edges with a scheduled end. Selected items occur exactly once, under their
batch.

## Waves

```json
{
  "index": 1,
  "layers": [1],
  "unit_count": 2,
  "batches": [{"kind": "symbol", "items": []}]
}
```

| field | meaning |
|---|---|
| `index` | the wave's position in `waves` |
| `layers` | the layers of the order it holds; several only when a cap folded them |
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
  "layer": 1,
  "loc": 36,
  "stats": {"loc": 36, "params": 2, "pointer_params": 1, "erased_params": 0,
            "returns_pointer": true, "variadic": false, "callers": 0,
            "callees": 2, "field_accesses": 6},
  "deps": {"types": [], "symbols": []},
  "higher_cuts": [],
  "lower_cuts": [],
  "generates": [],
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
| `layer` | its layer in the order of the whole closure, whatever the seeds |
| `loc` | a function's body line span, 1 for a global, 0 for a macro; a type's field count |
| `stats` | the counts a consumer weighs the item's work by, below |
| `deps` | the nodes it depends on whose edges were kept: a unit is of a lower layer |
| `higher_cuts` | the dependencies whose edges were cut to break a cycle: of a higher layer, so it is processed before them |
| `lower_cuts` | the reverse: the units of lower layers whose dependency on it was cut |
| `generates` | on a generator macro (T3 `type_generators.csv`), the instance types it mints, routed as one type so one generic is written for them; `[]` otherwise |
| `used_fields` | on a type, the fields its users reach: in API mode every field of a type an `api_headers` file defines, and none of a type defined elsewhere; otherwise the fields the closure's own functions access |

Every reference in `deps`, `higher_cuts`, and `lower_cuts` is
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
