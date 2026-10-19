# Findings schema

Field meaning for findings: the judgements a user records about an entity,
which wavefront cannot derive from the source. Every type and symbol record
that `query` prints has two parts:

```json
{"composed": {}, "findings": {}, "_analysis": {}}
```

`composed` is what wavefront derives from the CodeQL tables
([`types.md`](types.md), [`syms.md`](syms.md)). `findings` lists every slot a
user may fill for the entity, with `null` where nothing is recorded, in
exactly the shape `--update` accepts:

```sh
wavefront REPO_ROOT --config PATH query symbols --name widget_new --update findings.json
```

A user can therefore copy a record's `findings`, fill it in, and submit it.
[`examples/findings.json`](../../examples/findings.json) holds a filled
example of each kind. `--update` validates the whole document against the
composed record and applies nothing if any rule fails; the error lists every
failure. Accepted findings are kept in the ownership store
([`ownership-store.md`](ownership-store.md)).

## Types

```json
{
  "_comment_user": "...",
  "fields": {
    "<field name>": {"ptr": {}, "refcount": false, "locked_by": null}
  }
}
```

| key | meaning |
|---|---|
| `_comment_user` | Free-text note on the type: the reasoning behind its findings. |
| `fields` | One entry per declared field, keyed by the field's name. |
| `fields.<name>.ptr` | The field's pointer properties ([`pointer-properties.md`](../pointer-properties.md)); pointer fields only. |
| `fields.<name>.refcount` | `true` on the one field that stores the type's reference count: the value an up-ref increments and a down-ref decrements ([`type-lifecycle.md`](../type-lifecycle.md)). |
| `fields.<name>.locked_by` | The lock that guards the field, pointer or not: `null`, or a [lock binding](#lock-binding). |

A type has no lifecycle slot. Its lifecycle routines record their roles on
their own symbol records.

## Symbols

The slots depend on the symbol's kind.

**Functions and callbacks:**

```json
{
  "ptr_args": {"<arg name>": {"ptr": {}}},
  "ptr_ret": {"ptr": {}},
  "lifetime": null
}
```

| key | meaning |
|---|---|
| `ptr_args` | One entry per pointer parameter, keyed by the parameter's name (never its position). |
| `ptr_args.<name>.ptr` | The parameter's pointer properties. |
| `ptr_ret.ptr` | The returned pointer's properties; present only when the symbol returns a pointer. |
| `lifetime` | The symbol's [lifecycle role](#lifetime), or `null`. |

**Callbacks** take `forks` as well: see [Forks](#forks).

**Globals:**

| key | meaning |
|---|---|
| `ptr` | The global's pointer properties, when it stores a pointer; `null` otherwise. |
| `locked_by` | The lock that guards the global: `null`, or a [lock binding](#lock-binding). |

**Macros** take no findings.

A symbol has no note slot: the reasoning behind a pointer's properties goes
in that pointer's `ptr.note`.

### lifetime

The lifecycle role the symbol plays, and the object it acts on.

| key | meaning |
|---|---|
| `for` | The parameter the role acts on, by name (`s`, not `arg:s` or a position); or `"return"` for an `alloc` constructor that returns its object. |
| `is_dropper` | The symbol frees the object's own storage: a full destructor. |
| `is_disposer` | The symbol frees what the object's fields own, and keeps the object's storage: a cleanup or reset. |
| `is_cloner` | `null`, or `{deep, upref}`: the symbol copies the object. `deep` is a new, independent allocation; `upref` a reference-count increment that returns the same object. Both may be set when the copy depends on the path taken. |
| `is_constructor` | `null`, or `{alloc, init}`: the symbol produces an object. `alloc` hands the caller a new object it owns, returned or stored through a `T **` out-parameter; `init` initializes caller-provided storage in place. Exactly one is set. |

`--update` rejects a `lifetime` block unless:

- it sets at least one role; `null` states that the symbol has none;
- `for` names one of the symbol's pointer parameters, or is `"return"` on an
  `alloc` constructor that returns a pointer;
- an `alloc` through a parameter names a `T **` (depth 2 or more), and an
  `init` a `T *` (depth 1);
- `is_dropper` and `is_disposer` are not both set, and a constructor sets no
  other role;
- the mode flags of `is_cloner` and `is_constructor` are booleans, and
  `alloc` and `init` are not both set;
- the subject's pointer properties agree: a dropper's argument is owned, a
  cloner's is borrowed, an `alloc` constructor's return is owned, and a
  constructor's argument is not immutable.

The last rule reads the subject's `ptr` as it stands after the update, and is
skipped while that `ptr` is `null`. [`type-lifecycle.md`](../type-lifecycle.md)
describes the roles and how to find the routines that play them.

### Forks

A callback whose invokers realize different contracts is split into forks:
one record per contract, each with its own pointer properties and role. On
the callback's primary record, `forks` lists them:

```json
{
  "forks": [
    {"ptr_args": {}, "ptr_ret": {}, "lifetime": null, "callsites": ["<invoker>"]}
  ]
}
```

| key | meaning |
|---|---|
| `forks[].ptr_args`, `ptr_ret`, `lifetime` | The fork's own findings, as on the primary. |
| `forks[].callsites` | The invokers that realize this fork's contract; the primary keeps the rest. Each invoker belongs to at most one fork. |

Each fork's own record shows its findings with its `callsites`. Forks are
submitted through the primary's `forks`, which replaces every earlier fork.

## Lock binding

`locked_by` names the lock that guards a field or a global:

| key | meaning |
|---|---|
| `lock` | The field or global that stores the lock object. |
| `lock_op` | The routines that acquire it. Which ones appear shows how readers and writers lock. |
| `unlock_op` | The routines that release it. |

## Merging

`--update` merges a submission into what is already recorded:

- a type's fields merge one by one, and each named key replaces its value;
  `_comment_user` is replaced when present;
- a symbol's parameters merge one by one, and a `ptr` block replaces the
  previous one entirely, so it must be complete;
- for a symbol, a `null` slot (`lifetime`, a parameter's or the return's
  `ptr`, a global's `ptr`) leaves the recorded value as it is;
- `locked_by` is replaced when present, and `null` clears it;
- `forks` replaces every earlier fork of the callback.

Submitting a record's own `findings` unchanged therefore leaves every
recorded value as it is.
