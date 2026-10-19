# Ownership store schema

Field meaning for `<state_dir>/ownership-store.json`: the judgements about a
codebase that no query can derive from its source. The file holds the
pointer properties ([`pointer-properties.md`](../pointer-properties.md)),
the lifecycle roles ([`type-lifecycle.md`](../type-lifecycle.md)), the
refcount and locking bindings, and the user's notes, each keyed to the C
entity it describes.

The structural half of each record (field layout, signatures, footprints,
casts) is composed from the CodeQL tables on demand. `query types` and
`query symbols` merge the store into it, so a reader sees one whole record,
and a re-extraction rewrites nothing in the store.

Records show each entity's findings in the shape users submit them
([`findings.md`](findings.md)); the store keeps them in the shape below.
`query types --update` and `query symbols --update` write the store. They
validate each submission against the composed record and replace the
judgements they name; the file itself carries no validation, so it should
not be edited by hand. Concurrent updates are serialized, and each one is
written atomically, with records sorted by key.

The store describes the C code and is shared by every config of a
repository.

## Top level

```json
{
  "_comment": "...",
  "types": [],
  "symbols": []
}
```

`_comment` describes the file for a reader. `types` and `symbols` hold one
record per analyzed entity.

## types

```json
{
  "name": "widget_st",
  "defined_in": "include/widget.h",
  "_comment_user": "...",
  "fields": [
    {"name": "buf", "ptr": {}, "refcount": false, "locked_by": null}
  ]
}
```

| key | meaning |
|---|---|
| `name`, `defined_in` | the type's tag and defining file; together, the record's key |
| `_comment_user` | the user's free-text note on the type |
| `fields[].name` | the field; the key within the record |
| `fields[].ptr` | the field's pointer properties; pointer fields only |
| `fields[].refcount` | `true` on the one field that stores the type's reference count |
| `fields[].locked_by` | the lock that guards the field: `null` or `{lock, lock_op, unlock_op}` |

A type stores no lifecycle of its own. Which routines drop, dispose, clone
or construct it is recorded on those routines' symbol records.

## symbols

```json
{
  "name": "widget_new",
  "defined_in": "src/widget.c",
  "lifetime": {"for": "return", "is_constructor": {"alloc": true, "init": false}},
  "ptr_args": [{"name": "opts", "ptr": {}}],
  "ptr_ret": {"ptr": {}}
}
```

| key | meaning |
|---|---|
| `name`, `defined_in` | the symbol and its defining file (or canonical declaration file); with `variant`, the record's key |
| `variant` | a callback fork's index, from 1; absent on the primary record |
| `lifetime` | the symbol's lifecycle role, and the argument it acts on |
| `ptr_args[].name` | a pointer parameter, keyed by name rather than position, so a signature change cannot move a judgement to another parameter |
| `ptr_args[].ptr` | that parameter's pointer properties |
| `ptr_ret.ptr` | the returned pointer's properties |
| `ptr` | a global's pointer properties |
| `locked_by` | the lock that guards a global: `null` or `{lock, lock_op, unlock_op}` |
| `callsites` | a callback fork's invokers: the call sites that realize this fork's contract |

A callback whose invokers realize different contracts is split into forks.
Each fork is a record of its own, with the primary's `name` and
`defined_in`, its own `variant`, and only its own judgements and
`callsites`; the signature it shares with the primary is composed at read
time.

A symbol record carries no note: reasoning about a pointer goes in that
pointer's `ptr.note`.
