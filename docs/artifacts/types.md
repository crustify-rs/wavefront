# Type record schema

Field meaning for the `composed` part of a type record: what wavefront
derives from the CodeQL tables. The `findings` part, which users fill, is
described in [`findings.md`](findings.md).

Each `## <field>` section documents one record field; the heading name is the
field key.

## name

The type's identifier: the C struct/union/enum tag. Composer-filled.

## typedef

List of typedef aliases that resolve to this tag. Composer-filled; `[]` when
there is none.

## kind

Composer-emitted: `struct`, `union`, or `enum`.

## declared_in

List of repo-root-relative header paths that declare the type (always a JSON
array, even for a single header). Same shape as the syms base. Composer-filled
for composer-emitted types.

## defined_in

Repo-root-relative path to the file holding the definition; nullable.
Composer-filled.

## casted

`{to: [tags], from: [tags]}`, composer-filled from the raw struct<->struct
pointer-cast graph (`edges/casts.ql`). `to` = tags this type is cast INTO (it is
a cast operand); `from` = tags cast INTO this type (it is a cast result). Both
are canonical struct tags (typedef spellings resolved), `[]` when none.

## casted_via

`{to: [{type, via}], from: [{type, via}]}`, composer-filled from the
SLOT-MEDIATED cast graph (`edges/arg_casts.ql` + `edges/field_casts.ql`,
joined by `compose/slot_casts.py`). It holds the casts `casted` cannot see
because a type-erased slot sits between the two types:

    log_vmsg(dec, ...)          Decoder -> param log_vmsg.0          (from)
    *(const ObjClass **) ctx    param log_vmsg.0 -> ObjClass         (to)

gives `Decoder.casted_via.to ∋ {type: ObjClass, via: [slot]}`. `via`
names the one slot both casts meet at (two when a named slot is stored into
another named slot), as `kind:name.member@file` with `kind` in `param` |
`ret` | `field`.

Only direct casts: both casts sit at the same slot. A value handed on
through calls, locals or memory is not followed, and a type-erased field
yields no pair: its variants are recorded on the field as `erased_as` (see
`fields`). Pairs are formed program-wide, function bodies included. How they
order the graph, and which of them are false positives, is in
[`graph.md`](../graph.md#polymorphism).

## opaque_in

Composer-filled `{file: [symbols]}` footprint: functions that touch this type
but only as an OPAQUE HANDLE, never accessing a field. A user reads it for
lifecycle/forwarder op candidates. COMPLETE: every consumer
tree-wide is listed.

## non_opaque_in

Composer-filled `{file: [symbols]}` footprint: functions that read/write a FIELD
of this type and so need its concrete layout (incl. transitive `a->b->field`
reachers). COMPLETE: the FULL cross-codebase footprint for every
type.

## _analysis

Derived at read time, never stored and never submitted.

- **`submitted`** -- whether the ownership store holds a record for this entity.
  A null slot cannot say this on its own: `lifetime: null` reads the same
  whether nobody has looked or a user looked and found no lifecycle role.
- **`pending`** -- the pointer slots carrying no ownership block, as dotted
  paths. Under `--targeted-only` / `--imported-only` it counts only the fields that
  scope's code touches, so it agrees with what `--fields` shows.

`submitted: true` with a non-empty `pending` is a partial analysis.

## fields

Per-field records:

- Scalar single -> `{name}` (layout-agnostic; the FFI binding carries it).
- Scalar array / by-value aggregate / aggregate array -> `{name, type, ref:"value", array?}`.
- Pointer (single or array) -> `{name, type, ref:"pointer", array?}`.

`type` is the element type (full, including `*`), omitted for scalar singles.
`ref` is value/pointer (the element's reference kind), omitted for scalar
singles. `array` is `{size:N}` (fixed) / `{size:null}` (flexible/incomplete
member), omitted when not an array.

`ref` is decided by the field's true pointer depth (CodeQL `ptr_depth`), not by
looking for a `*` in `type`. C hides the star behind a name in two shapes the
string cannot show, both of which used to collapse to a bare scalar with no
`findings` slot -- an **object-pointer typedef** (`typedef struct _filesec
*filesec_t;`) and a **bare function pointer** (`int (*ctrl)(Stream *, int)`).

- **`sig_types`** -- composer-filled, present ONLY when `type` is a string that
  names nothing: a bare function pointer (`..(*)(..)`) or an anonymous
  aggregate. It lists the user types named inside that type -- for a function
  pointer, its signature (`int (*ctrl)(Stream *, …)` -> `["Stream"]`). Without it a
  vtable struct is a dependency LEAF: every slot renders `..(*)(..)`, so the
  DAG sees no edge and would schedule the struct before the types its function
  pointers traffic in. An ordinary `T *` field needs no help and carries none.
- **`erased_as`** -- composer-filled, present ONLY on a type-erased pointer
  field (`void *`, `uint8_t *`, ...) that some code casts: `{stored: [tags],
  read_as: [tags]}`, the named types written into it and the ones its reads
  are converted to (`Decoder.priv`: `stored` one private context,
  `read_as` every decoder's). These are the field's variants: which type an
  instance holds is a runtime choice, so they are never `casted_via`
  pairs. Every one is listed, including those a T3 `drop` row removes from
  the graph ([`graph.md`](../graph.md#type-erasure)).
