# The dependency graph

Wavefront orders a C codebase so that every item can be written after the
items it needs. It builds one directed graph over the codebase's types and
symbols, cuts its cycles, and sorts it into layers in type order: a field's
type below the struct that holds it, a base below its derived types, a
generic container below its instances, a type below the functions whose
signatures name it, a callee below its callers. Layer 0 holds the leaves;
a node in layer N depends only on nodes in layers below N.

The graph is a pure function of the extracted CodeQL facts (T1, T2), the
authored T3 tables and the config's inventory. Ownership findings an agent
submits never move a node, so the same inputs always give the same layers.
[`scoping.md`](scoping.md) describes which entities a config owns and
imports, and [`batching.md`](batching.md) how a schedule cuts the layers into
waves and batches.

There are two graphs per config:

- the **default graph**, body-deep: what the config's own functions call and
  touch orders them;
- the **API graph** (`--api-headers-only`), the public-signature graph: no
  function body is read, and only the layouts the `api_headers` define are
  walked.

Both are cached under `state_dir/.cache/`, keyed by the inputs' hashes.

## Nodes

A node is one entity, keyed `(name, defined_in)`. A bare name does not
identify one: same-named file-local statics, and a struct a `.c` file
defines locally, recur across translation units.

- **Types**: structs, unions and enums, keyed by tag and defining file (or
  the declaring header for a declaration-only type). A typedef of an
  aggregate is an alias resolved onto its tag, not a node of its own; a
  typedef of a primitive is no node at all, nor is an anonymous aggregate
  (it cannot be named). Only types in the config's inventory are nodes.
- **Symbols**: functions, globals, macros and callbacks (function-pointer
  typedefs), keyed by defining file, or the canonical declaration file for
  one that is declared but never defined. A symbol whose name is also a
  type tag is represented by the type node.
- **External leaves**: a function or type something depends on that the
  database never defines (libc, a compiler builtin) is a leaf with subkind
  `external` or `builtin`, so the order is complete.

A type's lifecycle routines are not folded into it: each is a symbol node
that depends on the type through its own signature. Folding would project
the call graph onto the types, and make the graph depend on which routines
agents judge droppers or cloners.

## Edges

`A -> B` means A needs B first. Each edge comes from one fact:

| edge | from | to | graphs |
|---|---|---|---|
| field | a struct | each non-scalar field type; the types in a function-pointer field's signature; a callback typedef a field has | both |
| signature | a function or callback | the types of its parameters and return | both |
| body | a function the config owns | the functions, globals and macros it references; the types its body uses | default |
| generator | a type a T3 generator mints | the generator macro | both |
| cast | see [Type erasure](#type-erasure) and [Polymorphism](#polymorphism) | | both |

A struct's field edges are narrowed to the layout that matters to the
config. A struct defined in a layout file (any targeted file in the default
graph; an `api_headers` file in the API graph) keeps every field edge: its
layout is the config's own. Any other struct keeps only the fields the
config's own functions access, which in the API graph is none, so an
opaque handle orders no work.

An imported function contributes its signature only: it is bound, not
translated. In the API graph every function does.

Field edges carry their multiplicity (how many fields of A have type B),
which weighs them when a cycle is cut.

### Type erasure

A type-erased slot (`void *`, `void **`, or a scalar pointer such as
`uint8_t *` that code casts to a named type) hides the type it holds from
the signatures and fields. Wavefront recovers it from the conversions the
code writes at the slot (`t2/arg_casts.csv`, `t2/field_casts.csv`) and adds
edges for it:

- **parameter reads**: a function whose own body reads its `void *`
  parameter as `T` depends on `T`, as on a typed parameter
  (`av_vlog(void *avcl)` reads `*(AVClass **)avcl`);
- **field variants**: the types stored into a type-erased field or read out
  of it are its variants (`erased_as` in the type records). Each variant
  depends on the field's owner, as a derived type on its base: the owner is
  the generic container, and each variant one instance of it
  (`AVFrameSideData.data` read as `AVStereo3D`). In Rust the owner can be
  generic over its variants, bound by a marker trait;
- **slot-mediated casts**: two named types joined by a cast into and out of
  one slot (`av_log(avctx)` stores an `AVCodecContext` where `av_vlog`
  reads an `AVClass`) are a cast pair like a direct cast (`casted_via`), and
  are ordered as [Polymorphism](#polymorphism) describes.

What wavefront cannot see, and what it sees wrongly, is corrected in T3
([`artifacts/t3.md`](artifacts/t3.md)): an `add` row states an edge no
conversion shows (a `void *` handed on through a chain of calls), a `drop`
row removes a derived cast edge that is no type relation (an alignment pun,
a reused slot). An `erased_arg` row is a parameter read, an `erased_field`
row a variant, a `base_derived` row a cast pair.

Cast edges come from function bodies, which can reach any type. In the API
graph they are therefore added in a second phase: the API closure is built
first, over field and signature edges only, from the items the
`api_headers` publish, and a cast edge is then added only when both of its
ends are in that closure. A cast to an internal type (`AVCodec -> FFCodec`)
thus neither pulls the type in nor reorders around it, while one to a public
type another library owns (`AVCodecContext -> AVClass`) is kept. The slot
that witnesses a cast is evidence, not a node, and need not be public.

## Cycles

C allows cycles that a topological order cannot: a parent and a child that
point at each other, mutually recursive functions, two types each cast to
the other. Wavefront finds the strongly connected components (Tarjan) and
flattens each one by a weighted feedback arc set:

1. order the component's members by net weight, how much more each is
   depended on than it depends, heaviest first (ties by id);
2. every edge from a member to one ordered after it is a **back-edge**, and
   is cut.

The rest is acyclic and layered by longest path. The cut edges stay
recorded on both ends: the user lists the dependency in `fallback` (its
wrapper refers to the type raw, as `ffi::T`, since it is not yet wrapped),
and the dependency lists the user in `back_fill` (once wrapped, those users
switch to the wrapper). `query dag --name X --scc hi-deps|lo-deps` reads the
two lists. The greedy order is deterministic but not a minimum cut.

### Polymorphism

A cast between two named types, direct (`t2/casts.csv`) or through a slot,
is an edge in its written direction: `X` cast to `T` makes X depend on T.
An upcast to a base orders the base first, and an erasure to an engine
orders the engine first. A downcast alone would order a base after its
derived type; a T3 `base_derived` row states the pair's direction, and
replaces the written edge for that pair with `derived -> base`.

Where the remaining cast edges form a cycle (both directions written, or a
ring through several types) the written direction settles nothing, and
**cast centrality** decides: inside the cycle `X -> T` survives only when T
is cast to or from strictly more types than X. A polymorphic base or a
generic engine is a hub, cast to and from by many types; an instance or a
derived type by few, so the edges run from the instances up to the hub, and
no cast cycle survives. In the API graph a type's degree counts only casts
to types in the API closure.

Field variants need no centrality: they are directed by construction, from
the variant to its owner. They can still close a cycle with field edges. A
context whose `priv_data` is read as `AVClass` by the first-member
convention (the private struct's first member is an `AVClass *`) makes
`AVClass` a variant of the context, while the context's `av_class` field
makes the context depend on `AVClass`. That variant is no instance of the
owner, and a T3 `drop` row removes it. A cycle that a field edge closes with
a cast edge is otherwise flattened like any other.

## Assumptions and limitations

The facts are syntactic, extracted from one build: the configuration the
CodeQL database traced, with `#ifdef`s resolved. Code that build does not
compile contributes nothing.

There is **no data-flow analysis**. A conversion is recorded at the slot
access that writes it, and nothing follows a value through locals, memory
or calls. Within one slot the analysis is path-insensitive: a read guarded
by a type check joins every type stored into that slot.

False negatives (missing edges):

- a type-erased value handed on through calls (`av_log(void *avcl)` only
  passes `avcl` to `av_vlog`): only the function whose body reads it
  depends on the type. Following the chain would join every type reaching
  the callee with every type any branch reads, so it is left to T3 `add`
  rows;
- a value carried through a local or through memory before its cast;
- a family of types minted by one macro: unrelated in C, a family only once
  T3 names its macro a generator;
- anything the traced build does not compile.

False positives (spurious edges):

- an alignment pun: a buffer read through `union unaligned_32` by the
  `AV_RN*` macros is no variant of its owner;
- a reused slot: `AVStream.priv_data` holding an `AVPacket` in one muxer;
- the `AVClass` first-member convention (see [Polymorphism](#polymorphism));
- casts are keyed by tag alone (`casts.csv` names no file), so two
  unrelated types sharing a tag share their cast edges;
- a callee named without a file that matches several same-named symbols
  depends on all of them.

Spurious cast edges are corrected with T3 `drop` rows; field, signature and
body edges are declarations and are never dropped. Wavefront warns when a
T3 row no longer corrects anything it derives, typically after a
re-extraction.

Cast centrality is a heuristic: it assumes a hub is cast more widely than
its instances. A base cast to by only one derived type, in both directions,
is ordered by the tie rule, which keeps neither edge.
