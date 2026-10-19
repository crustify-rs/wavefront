# Pointer properties

A C pointer type states where a pointer points, but not how much it points
at, who releases it, or whether it may be null. A user records those facts
as a pointer's properties, in the ownership store
([`artifacts/ownership-store.md`](artifacts/ownership-store.md)). A Rust
translation reads them to choose the pointer's Rust type: a reference, a
slice, a string, an owning box, an `Option`.

## Where pointers occur

The same block of properties, `ptr`, describes a pointer wherever it occurs:

| site | record | ownership is relative to |
|---|---|---|
| parameter | `ptr_args[].ptr` on a function or callback | the call: the callee takes it, or borrows it |
| return | `ptr_ret.ptr` on a function or callback | the call: the caller receives it, or borrows it |
| field | `fields[].ptr` on a type | the enclosing struct |
| global | `ptr` on a global | the program |

A composed record carries `ptr: null` until a user submits a block, so
`null` means the pointer has not been analyzed. A submitted block replaces
the previous one entirely and must be complete.

## Shape

Three properties state what the pointer points at. A pointer sets at least
one of them, and may set several when different execution paths use it
differently.

| property | value | meaning |
|---|---|---|
| `scalar` | `null`, `{by_val: true}`, or `{by_ref: {owned, borrowed}}` | On some path the pointer refers to a single pointee: one value (`by_val`, an ordinary `T *`), or one pointer (`by_ref`, a `T **` such as an out-parameter). |
| `array` | `null`, `{by_val: true}`, or `{by_ref: {owned, borrowed}}` | On some path the pointer refers to a buffer: of values (`by_val`), or of pointers (`by_ref`, a container). |
| `string` | `true` or `false` | On some path the pointer refers to a NUL-terminated string. |

Under `by_ref`, `owned` and `borrowed` describe the inner pointers, the
pointee of a `T **` or the elements of a container, with the same
meaning as at the top level. The top-level `owned` and `borrowed` then
describe the outer pointer. `scalar.by_ref` and `array.by_ref` differ only
in how many inner pointers there are.

## Ownership

| property | value | meaning |
|---|---|---|
| `owned` | `true` or `false` | Whoever holds the pointer must release it. A parameter's ownership passes to the callee; a return's passes to the caller; a field's belongs to the struct. |
| `borrowed` | `null` or `{lifetime}` | The pointer is valid only while another entity is; `lifetime` names it. |

A pointer is owned, borrowed, or both; never neither. Both are set when
ownership depends on the path taken: owned on one, borrowed on another. The
same holds for each `by_ref` inner pointer.

A borrowed lifetime names its source in the vocabulary of the site:

| site | sources |
|---|---|
| parameter, return | `arg:<name>`, `arg:<name>-><path>`, `static`, `other` |
| field | `self` (the enclosing struct), `field:<name>` (a sibling field's storage), `static`, `other` |
| global | `static`, `other` |

A parameter is named by its name, never by its position. A pointer that is
read only during the call borrows from itself: `arg:<its own name>`.

## Access

| property | value | meaning |
|---|---|---|
| `nullable` | `true` or `false` | The pointer may be `NULL`. |
| `mutable` | `true`, `false`, or `null` | Code writes through the pointer. A `const` pointee forces `false`; `null` only when it cannot be determined, as for an external function with no body. |
| `note` | text | The reasoning behind the block, and its gaps and corner cases. |

## Invariants

`query --update` rejects a block, and applies nothing, unless:

- `scalar` and `array` are each `null` or exactly one of `by_val` and
  `by_ref`;
- at least one of `scalar`, `array` and `string` is set;
- `string` and `owned` are booleans, never `null`;
- the pointer, and each `by_ref` inner pointer, is owned or borrowed;
- a borrowed pointer has a lifetime, and an `arg:<name>` lifetime names a
  parameter of the same symbol;
- a `const` pointee has `mutable` other than `true`;
- `ptr_ret` is set only on a symbol that returns a pointer.

## Related bindings

Two more judgements sit beside `ptr` on a field or a global, because they
apply to non-pointer data as well:

- `refcount` marks the one field that stores its type's reference count
  ([`type-lifecycle.md`](type-lifecycle.md));
- `locked_by` names the lock that guards a field or global, and the
  routines that acquire and release it: `{lock, lock_op, unlock_op}`.
