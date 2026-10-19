# Symbol record schema

Field meaning for the `composed` part of a symbol record: what wavefront
derives from the CodeQL tables. The `findings` part, which users fill, is
described in [`findings.md`](findings.md).

One record per symbol: a function, macro, global, or callback (a
function-pointer typedef), keyed by its definition site — or, when the symbol
is never defined (a header typedef/decl), its canonical declaration.

Each `## <field>` section documents one record field; the heading name is the
field key.

## name

The C identifier exactly as written at the definition site. Composer-filled;
users never edit it.

## kind

The symbol's category. Composer-filled -- users never edit
it. The enum is `function_{exported,static,inline_header,inline_tu}`, `macro`,
`global_{static,extern}`, `callback`.

### kind.callback

A callback is a function-pointer typedef (CodeQL identifies it
deterministically: a typedef whose unwrap chain reaches a RoutineType).
Composer-filled kind; signature-shaped (carries `ptr_args` / `ptr_ret` /
`used_by.{call,ref}` / a signature `depends_on`, NO body). `defined_in` is null (a
header typedef). Its findings are those of a function, read off its
invokers in `used_by.call`. When the invokers realize different contracts,
a user splits it into forks ([`findings.md`](findings.md#forks)): records
with the same name and type, told apart by `variant`, that partition
`used_by.call`.

## variant

Callback forks only, absent otherwise: the fork's index, from 1. The primary
record has no `variant`. A fork's `used_by.call` is the subset of invokers
that realize its contract.

## _analysis

Derived at read time, never stored and never submitted.

- **`submitted`** -- whether the ownership store holds a record for this entity.
  A null slot cannot say this on its own: `lifetime: null` reads the same
  whether nobody has looked or a user looked and found no lifecycle role.
- **`pending`** -- the pointer slots carrying no ownership block, as dotted
  paths. Under `--targeted-only` / `--imported-only` it counts only the fields that
  scope's code touches, so it agrees with what `--fields` shows.

`submitted: true` with a non-empty `pending` is a partial analysis.

## declared_in

Sorted list of header files that declare or export the symbol. Composer-filled.

## defined_in

The single file holding the definition: `.c` for functions and globals, `.h` for
inline functions and macros. Null when the symbol is declared in the DB but never
defined. Composer-filled.

## type

The full C signature for functions, the declared C type for globals, and null
for macros (a macro has no type). Composer-filled.

## is_variadic

`true` when the function takes a trailing `...` (a C variadic like `printf`),
`false` otherwise. Composer-filled from CodeQL (`Function.isVarargs()`) and
terminal. Present on function kinds; absent on macros, globals and
callbacks.

## loc

Body line span (`endLine-startLine+1`) of a function's definition; 1 for a
global, 0 for a macro; 0 when absent (a pre-loc extraction). Composer-filled from
`functions.csv`. A schedule's `--max-loc` budget sums it per symbol batch
([`batching.md`](../batching.md#batches)).

## ptr_args/ptr_ret

The two pointer records at a call boundary. `ptr_args` is a LIST -- one record
per pointer parameter, ordered by position (empty when the function has no
pointer params); `ptr_ret` is a single record, or null when the return type
isn't a pointer. Both carry the SAME fields, `position` / `name` for `ptr_args`.

COMPOSER fields (skeleton, always set), at the record's TOP level: on each
`ptr_args` record `position` and `name` (param name as written, falling back to
`arg<N>`); on both `ptr_args` and `ptr_ret` `type` (verbatim innermost pointee
type -- a user tag like `Widget`, a primitive like `char`/`void`, or the
synthetic markers `(routine)`/`(array)`), `const` (is the innermost pointee
const-qualified?), and `depth` (1 for `T*`, 2 for `T**`, ...).

A parameter's or the return's pointer properties are findings, keyed by the
parameter's name ([`findings.md`](findings.md#symbols)).

## used_by

Composer-filled (users must not modify). `call` and `ref`
name the enclosing functions (or file paths for file-scope macro expansions) that
reach this entry. By kind: `function_*` -> `{call:[callers], ref:[addr-of users]}`,
where a site that both calls and takes the address is listed only under `call`;
`global_*` -> `{call:null, ref:[accessors]}`; `macro_*` -> `{call:[expansion
sites], ref:[]}`. The composer's default bucketing is fine for most kinds; a
user may re-bucket `call`<->`ref` when a macro kind justifies it.

## depends_on

Composer ground-truth (users must not modify).
`depends_on.syms` is the forward callee/reference set: each record is `{name,
defined_in, declared_in}`, with `defined_in` nullable for externals (e.g. libc
functions not in the DB) -- resolve via `defined_in` first, else
`declared_in[0]`. `depends_on.types` is the forward type-use list: each record is
`{type, fields}`, where `type` is the canonical struct/union/enum tag (typedef
chains resolved) and `fields` are the accessed field names. The composer unions
signature types (parameters/return) with body-touched types from
`t2/field_accesses.csv`; signature types come first (signature order), body-only
types follow (first-encounter order); a signature type whose body touches no
field carries `fields:[]` (opaque use).
