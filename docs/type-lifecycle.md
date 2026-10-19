# Type lifecycle

A type's lifecycle is the set of routines that create, copy and release its
objects. C states none of it: `widget_free` is a function like any other.
A user identifies these routines and records them in the ownership store
([`artifacts/ownership-store.md`](artifacts/ownership-store.md)), so a Rust
translation can implement construction, `Clone` and `Drop` with them.

## What the store holds

A lifecycle is recorded on the routines, not on the type. Each routine's
symbol record carries a `lifetime` block: the role it plays and the
parameter it acts on (`for`), or `"return"` for a constructor that returns
the new object. Field schema: [`artifacts/syms.md`](artifacts/syms.md#lifetime).

| role | the routine |
|---|---|
| `is_dropper` | frees the object's own storage: a full destructor. The argument must be owned. |
| `is_disposer` | frees what the object's fields own, but keeps the object's storage: a cleanup or reset that leaves it reusable. |
| `is_cloner` | copies the object: `deep`, a new independent allocation, or `upref`, a reference-count increment that returns the same object. The argument must be borrowed. |
| `is_constructor` | produces an object: `alloc`, a new object the caller owns, returned or stored through a `T **` out-parameter; or `init`, initialization of caller-provided storage in place. |

A routine is a dropper or a disposer, never both. A constructor plays no
other role. A routine that returns storage a separate `init` must still
complete is an allocator, not an `alloc` constructor.

One field per type may be marked `refcount`: the field an up-ref increments
and a down-ref decrements. A reference-counted type is released by its
down-ref and copied by its up-ref; any other type by its dropper and deep
cloner.

The lifecycle is read back from the routines:

- `query types --name T --lifecycle-ops` lists the routines acting on `T`,
  lifecycle roles first;
- `query symbols --lifetime-for T` lists the routines with a role on `T`,
  `void` or `string`.

Lifecycle roles never change the dependency graph
([`graph.md`](graph.md#nodes)): a schedule is made before any role is
known.

## Raw lifetimes: `void` and `string`

Two lifecycles belong to no type. The `void` lifecycle covers untyped
memory (`void *`): the allocators, releasers and copiers of raw bytes. The
`string` lifecycle covers NUL-terminated strings. `schedule --lifetime-for
void|string` emits one unit for each, and type lifecycles build on them,
since a type's routines release its memory through the raw ones.

## How to discover lifecycle routines

The routines worth recording are those that release, dispose of, copy or
construct storage: heap allocations, and the fields of a type embedded by
value or held on the stack. Record a routine when more than one caller uses
it, or when the API publishes it. A helper that only lifecycle routines
call need not be recorded. `query symbols --callers` and `--callees` show
who uses a routine.

### `void`

1. Start from the C library: `free`, `malloc`, `calloc`, `realloc`, `mmap`,
   `munmap`, `memcpy`, `memmove`, `strdup`, `strndup`.
2. Find the project's own routines that call them, and follow callers a few
   hops further for more specialized ones.
3. Keep releasers and copiers that take a `void *` (`--taking void`).
4. Find allocators by their return, since `malloc(size_t)` takes no
   `void *`: `--returning void --calling malloc,calloc --depth N`. Record
   each as an `alloc` constructor, and note whether it zeroes the memory.
5. Do not record a `realloc`-style routine as a constructor: it releases
   and allocates the same storage, and a constructor plays no other role.

Include routines that handle arrays as well as single objects.

### `string`

1. Find routines that take a `char *`, `unsigned char *`, `uint8_t *` or a
   similar character pointer and call one of the `void` routines, then
   follow callers a few hops further.
2. Check the `void` routines as well: some of them also release or copy
   strings, and those are recorded for `string` too.
3. Find constructors with `--returning string`: formatters, tokenizers and
   path joiners that return a new string. Record each as an `alloc`
   constructor.
4. Record a routine that copies a string argument as a cloner, not a
   constructor. A raw allocator stays in the `void` lifecycle even when its
   memory later holds a string, because it does not return one.

### A type `T`

1. Find routines that take a `T *` (`--taking T`) and call one of the
   `void` routines.
2. Follow callers a few hops further to the top-level droppers, disposers
   and cloners, which often reach the raw routines through helpers.
3. Find constructors: `alloc` ones return a `T *` (`--returning T`) or store
   it through a `T **` (`--taking T`, depth 2); `init` ones fill a
   caller's `T *` in place.
4. For a plain type released only as part of an enclosing type, record the
   enclosing type's disposer.

Include routines that handle arrays as well as single objects. Submit the
roles with `query symbols --update`, on each routine; a type's own record
holds no lifecycle.
