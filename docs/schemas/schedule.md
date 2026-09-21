# Sub-campaign schedule schema

Field meaning for the document `wavefront <repo> --config PATH schedule
--output PATH` writes. Complete example:
[`examples/waves.json`](../../examples/waves.json).

A schedule is objective-neutral: it orders and packs work without deciding
what a consumer does with it. Waves are sequential and barrier-separated;
the batches within one wave may execute concurrently. A consumer adds its own
objective and concurrency.

The filename is not identity. `--output` accepts any path whose parent
directory already exists, so a consumer names schedules however its own layout
prefers. Wavefront never creates that directory.

## Version 3

```json
{
  "schema_version": 3,
  "oracle_config": {
    "path": "crustify/campaigns/src/widget/wavefront-config.json",
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "api_headers_only": false,
  "budgets": {
    "max_syms": 25,
    "max_loc": 500,
    "max_types": 2,
    "min_fields": 20
  },
  "summary": {
    "unit_count": 3,
    "layer_count": 2,
    "batch_count": 2,
    "file_count": 2
  },
  "waves": [
    {
      "unit_count": 2,
      "batches": [
        {
          "kind": "type",
          "source_file": "include/example.h",
          "items": []
        }
      ]
    }
  ]
}
```

`oracle_config` records the exact `--config` input as a repository-relative or
absolute path plus its SHA-256, so a consumer can reject a plan whose config is
missing or has changed since scheduling. `api_headers_only` records the
selection mode and `budgets` the packing limits applied.

`summary` gives totals for the selected units, underlying dependency layers,
emitted batches, and distinct batch source files. Selected items occur exactly
once under their batch; there is no duplicate `plan_items` table. Dependencies
are self-contained references on those items; there is no separate
`dependency_nodes` table. Each item's `layer` is the sole copy of its DAG
layer; consumers derive a wave's layer set from its batched items.

## Waves and batches

A wave contains one or more topological DAG layers, and must complete before
the next starts. Adjacent layers are folded whenever the merged work fits one
batch, including for non-transitive selections. A fold never creates parallel
producer and consumer batches.

`kind` records the objective-neutral route (`type`, `symbol`, or the special
`raw-lifetime` route), `source_file` records the batch's source grouping, and
`items` is the exact worklist for one agent.

Each item has this shape:

```json
{
  "name": "example_new",
  "defined_in": "src/example.c",
  "kind": "symbol",
  "source_kind": "function",
  "layer": 1,
  "loc": 12,
  "deps": {"types": [], "symbols": []},
  "fallback": [],
  "back_fill": [],
  "generates": [],
  "field_anchors": []
}
```

Every reference in `deps`, `fallback`, and `back_fill` is
`{"name": "...", "defined_in": "...", "scope": "wrap|port|ext"}`. The scope
lets consumers understand dependency context without a second node table.
`field_anchors` occurs on batched items and lists the field accessors assigned
to that type batch.

Schema-v2 schedules with `steps`, `plan_items`, and `dependency_nodes` remain
readable historical records and need not be rewritten. New schedules are always
schema v3.
