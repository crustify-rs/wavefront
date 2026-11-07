# The dependency graph

Wavefront orders a C codebase so that every item can be written after the
items it needs. It builds one directed graph over the codebase's types and
symbols, cuts its cycles, and sorts it into layers in type order: a field's
type below the struct that holds it, a base below its derived types, a
generic container below its instances, a type below the functions whose
signatures name it, a callee below its callers. Layer 0 holds the leaves;
a node in layer N depends only on nodes in layers below N.

The graph is a pure function of the extracted CodeQL facts (T1, T2), the
authored T3 tables and the config's inventory. Ownership findings a user
submits never move a node, so the same inputs always give the same layers.
[`scoping.md`](scoping.md) describes which entities a config's closure
holds and owns and which it reaches outside, and [`batching.md`](batching.md) how a schedule cuts the layers into
waves and batches.

There are two graphs per config:

- the **default graph**, body-deep: what the config's own functions call and
  touch orders them;
- the **API graph** (`--api-headers-only`), the public-signature graph: no
  function body is read, and only the layouts the `api_headers` define are
  walked.

Both are cached under `state_dir/.cache/`, keyed by the inputs' hashes.

## Nodes

A node is one entity, keyed `(name, defined_in, kind)`, its kind `type` or
`symbol`. A bare name does not identify one: same-named file-local statics,
and a struct a `.c` file defines locally, recur across translation units.
Nor does a name and its file: C keeps tags apart from ordinary identifiers,
so `static const struct typelen {...} typelen[]` is a type and a global of
one name in one file, two nodes.

- **Types**: structs, unions and enums, keyed by tag and defining file (or
  the declaring header for a declaration-only type). A typedef of an
  aggregate is an alias resolved onto its tag, not a node of its own; a
  typedef of a primitive is no node at all, nor is an anonymous aggregate
  (it cannot be named). Only types in the config's inventory are nodes.
  C gives a tag no identity across translation units, so a forward
  declaration is matched to a definition by its tag: the database may record
  it as an entity of its own, which folds into the definition of its tag.
  When the tag has several definitions, as file-local structs of one tag
  have, it folds into each, and Wavefront warns.
- **Symbols**: functions, globals, macros and callbacks (function-pointer
  typedefs), keyed by defining file, or the canonical declaration file for
  one that is declared but never defined.
- **External leaves**: a function or type something depends on that the
  database never defines (libc, a compiler builtin) is a leaf with subkind
  `external` or `builtin`, so the order is complete.

A type's lifecycle routines are not folded into it: each is a symbol node
that depends on the type through its own signature. Folding would project
the call graph onto the types, and make the graph depend on which routines
users judge droppers or cloners.

A C++ class's lifecycle is the exception: its constructors, destructor, copy
and move are the language's, not a judgement, so they fold into the class's
node, which takes their edges and lists them as its `cpp.lifecycle`. Its
other members stay symbol nodes that depend on the class and say which class
they implement. A C++ entity is keyed by its qualified name, an instantiation
by its template's ([`cpp.md`](cpp.md#identity)).

## Edges

`A -> B` means A needs B first. Each edge comes from one fact:

| edge | from | to | graphs |
|---|---|---|---|
| field | a struct | each non-scalar field type; the types in a function-pointer field's signature; a callback typedef a field has | both |
| signature | a function or callback | the types of its parameters and return | both |
| body | a function, global or `.c` macro the config owns | the functions, globals and macros it references; the types its body uses | default |
| generator | a type a T3 generator mints | the generator macro | both |
| base | a C++ class | each base class, and the primary template a specialization specializes | both |
| member | a C++ member function | its class | both |
| override | a C++ override | the virtual function it overrides | both |
| cast | see [Type erasure](#type-erasure) and [Polymorphism](#polymorphism) | | both |

A struct's field edges are narrowed to the layout that matters to the
config. A struct defined in a layout file (any closure file in the default
graph; an `api_headers` file in the API graph) keeps every field edge: its
layout is the config's own. Any other struct keeps only the fields the
config's own functions access, which in the API graph is none, so an
opaque handle orders no work.

An external function contributes its signature only: it is bound, not
translated. So does a macro a closure header defines, which stays C's
([`scoping.md`](scoping.md#default-mode)). In the API graph every function
does.

### Type erasure

A type-erased slot (`void *`, `void **`, or a scalar pointer such as
`uint8_t *` that code casts to a named type) hides the type it holds from
the signatures and fields. Wavefront recovers it from the conversions the
code writes at the slot (`t2/arg_casts.csv`, `t2/field_casts.csv`) and adds
edges for it:

- **parameter reads**: a function whose own body reads its `void *`
  parameter as `T` depends on `T`, as on a typed parameter
  (`log_vmsg(void *ctx)` reads `*(const ObjClass **)ctx`);
- **field variants**: the types stored into a type-erased field or read out
  of it are its variants (`erased_as` in the type records). Each variant
  depends on the field's owner, as a derived type on its base: the owner is
  the generic container, and each variant one instance of it
  (`SideData.data` read as `HdrMetadata`). In Rust the owner can be
  generic over its variants, bound by a marker trait;
- **slot-mediated casts**: two named types joined by a cast into and out of
  one slot (`log_msg(dec)` stores a `Decoder` where `log_vmsg` reads an
  `ObjClass`) are a cast pair like a direct cast (`casted_via`), and
  are ordered as [Polymorphism](#polymorphism) describes.

What wavefront cannot see, and what it sees wrongly, is corrected in T3
([`artifacts/t3.md`](artifacts/t3.md)): an `add` row states an edge no
conversion shows (a `void *` handed on through a chain of calls), a `drop`
row removes a derived cast edge that is no type relation (an alignment pun,
a reused slot). An `erased_arg` row is a parameter read, an `erased_field`
row a variant, a `base_derived` row a cast pair.

Cast edges come from function bodies, which can reach any type. In the API
graph they are therefore added in a second phase: the API reach is built
first, over field and signature edges only, from the items the
`api_headers` publish, and a cast edge is then added only when both of its
ends are in that reach. A cast to an internal type (`Codec -> CodecInternal`)
thus neither pulls the type in nor reorders around it, while one to a public
type another library owns (`Decoder -> ObjClass`) is kept. The slot
that witnesses a cast is evidence, not a node, and need not be public.

## Cycles

C allows cycles that a topological order cannot: a parent and a child that
point at each other, mutually recursive functions, two types each cast to
the other. Wavefront finds the strongly connected components (Tarjan) and
flattens each one by a feedback arc set:

1. order the component's members by how many more of its edges reach them
   than leave them, the most depended on first (ties by id). An edge counts
   once, however often its user refers to its dependency: cutting it leaves
   one binding of the dependency to write;
2. every edge from a member to one ordered after it is a **back-edge**, and
   is cut.

The rest is acyclic and layered by longest path. The cut edges stay
recorded on both ends: the user lists the dependency in `fallback`, since it
is processed before the dependency it refers to, and the dependency lists the
user in `back_fill`, the units that already refer to it.
`query dag --name X --scc hi-deps|lo-deps` reads the
two lists. The greedy order is deterministic but not a minimum cut. A
schedule cuts its units' cycles the same way, between its modules and
within each, and records its cuts in its items' `depends_on.cut` and
`depended_on_by.cut`
([`batching.md`](batching.md#order)).

### Polymorphism

A cast between two named types, direct (`t2/casts.csv`) or through a slot,
is an edge in its written direction: `X` cast to `T` makes X depend on T.
An upcast to a base orders the base first, and an erasure to an engine
orders the engine first. A downcast alone would order a base after its
derived type; a T3 `base_derived` row states the pair's direction, and
replaces the written edge for that pair with `derived -> base`. A C++ base
class states it in the class head, and replaces the written edge the same
way, without a row.

Where the remaining cast edges form a cycle (both directions written, or a
ring through several types) the written direction settles nothing, and
**cast centrality** decides: inside the cycle `X -> T` survives only when T
is cast to or from strictly more types than X. A polymorphic base or a
generic engine is a hub, cast to and from by many types; an instance or a
derived type by few, so the edges run from the instances up to the hub, and
no cast cycle survives. In the API graph a type's degree counts only casts
to types in the API reach.

Field variants need no centrality: they are directed by construction, from
the variant to its owner. They can still close a cycle with field edges. A
context whose `priv` is read as `ObjClass` by a first-member convention
(the private struct's first member is an `ObjClass *`) makes `ObjClass` a
variant of the context, while the context's own `cls` field makes the
context depend on `ObjClass`. That variant is no instance of the
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

- a type-erased value handed on through calls (`log_msg(void *ctx)` only
  passes `ctx` to `log_vmsg`): only the function whose body reads it
  depends on the type. Following the chain would join every type reaching
  the callee with every type any branch reads, so it is left to T3 `add`
  rows;
- a value carried through a local or through memory before its cast;
- a family of types minted by one macro: unrelated in C, a family only once
  T3 names its macro a generator;
- anything the traced build does not compile.

False positives (spurious edges):

- an alignment pun: a buffer read through `union unaligned32` by an
  unaligned-load macro is no variant of its owner;
- a reused slot: `Stream.priv` holding a `Packet` in one file;
- a first-member convention (see [Polymorphism](#polymorphism));
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
