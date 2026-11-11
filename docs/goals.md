# Goals

Wavefront orders a C codebase for translation to Rust. It extracts facts
about the codebase's entities and the dependencies between them, builds one
dependency graph from them, and orders every unit of that graph, so that each
can be translated after everything it depends on.

Three parties use it:

- **queries** state facts: the CodeQL queries of T1 (entities) and T2 (edges),
  which read one build of the codebase;
- **judges** correct the facts where a fact needs judgement: an agent or a
  human, through T3 rows and the ownership store;
- **consumers** read the result: a planner deciding modules, an agent binding
  or porting an item, a scheduler packing waves. They read it through the
  `query` and `schedule` commands, and never need to know which of the three
  tiers a dependency came from.

Wavefront exists so that the order is **mechanical where facts suffice, and
judged only where they do not**, with the line between the two explicit.

The goals below are grouped by what they serve. Each states what it means and
how it is checked. A change that departs from one says so, in its commit and
here.

## Facts

### G1. Facts, not data flow

Every fact is syntactic: a declaration, a call, a field access, a cast, an
expansion, as the source writes it at one site in one build. Nothing follows a
value through locals, memory or calls, and no points-to analysis runs. Where
an answer would need data flow, Wavefront records the fact it can see at the
site and leaves the rest to a judge (G7), rather than approximating the flow.

This keeps every fact cheap, local and checkable: a reader confirms it by
looking at one line of source.

*Checked by:* every T1/T2 column is documented as what one source site states,
and each table row names the file and the entity it comes from.

### G2. The facts are C's

Entities are classified in C's own terms: a kind (`function`, `global`,
`macro`, `struct`, `union`, `enum`, `function_pointer`, `typedef`), a
namespace (tag or ordinary identifier), a home (the defining file, or the
declaring one for an entity defined nowhere), and the properties C gives a
declaration (`static`, `inline`, `exported`, `const`). An identity is
`(name, home, namespace)`, the same in every table, record and schedule. No
classification is invented for one codebase, one campaign kind or one
consumer: a consumer's routing is derived from these, by the consumer.

*Checked by:* the kind vocabulary is defined once (`wavefront.kinds`), and
every artifact that names an entity names it by that identity and kind.

### G3. One build, stated

The facts are those of the build the CodeQL database traced, with its
`#ifdef`s resolved. Code that build does not compile contributes nothing, and
the documentation says so wherever it matters, rather than guessing at other
configurations.

*Checked by:* every limitation that follows from the traced build is listed in
[`graph.md`](graph.md#assumptions-and-limitations).

## Order

### G4. A total order over every unit

Every unit of the closure gets a place in the order: functions, globals,
macros, structs, unions, enums, function pointers and typedefs alike. Nothing
is left out because its dependencies are hard to see. The order is a
dependency order: a unit comes after everything it depends on, except across
an edge cut to break a cycle.

*Checked by:* a schedule's units are exactly the closure's units its seeds
reach, and each layer depends only on earlier ones and on recorded cuts.

### G5. Through hidden slots

A dependency the declarations hide is still a dependency. A type stored in a
`void *` or a scalar pointer and cast back, a family of types one macro
mints, a function pointer written inline, a type reached only through a
typedef chain: each is recovered from the facts the code writes at its slots
and ordered like a visible one, from the evidence the slot gives, not from the
slot's declared type alone.

*Checked by:* each kind of hidden slot has a fixture whose order would be
wrong without the recovered edge.

### G6. Cuts are explicit and deterministic

C permits cycles that no order satisfies. Wavefront breaks each one by a
documented, deterministic rule, and records every cut edge on both ends, so
that the unit placed first knows what it refers to before it exists and the
other knows who already refers to it. A cut is never silent, and never decided
by iteration order.

*Checked by:* the same inputs give byte-identical graphs and schedules, and
every cut appears in both of its items' `cut` lists.

## Judgement

### G7. Judges correct the edges, Wavefront applies them

Where a fact is missing (a `void *` handed on through calls) or misleading
(an alignment pun, a reused slot), a judge states the correction as data: a T3
row that adds or drops an edge, or names a generator macro. Wavefront applies
it like any other fact, and the order follows. A correction is never code:
a heuristic that would fix one codebase's edges is a T3 row in that codebase,
not a rule in Wavefront.

*Checked by:* every T3 row kind has its documented meaning as an edge, and the
edges it can add or drop are the only ones a judge can change.

### G8. Corrections are checked, and stale ones reported

A correction names entities that exist, at positions that exist, of the kind
it claims. A row that fails is an error, listed by file and line, and is never
skipped. A row that no longer changes anything, because the code or the
extraction now states what it said, is reported as stale.

*Checked by:* the T3 loader's checks, and a test per check.

### G9. Facts and judgement stay apart

Every edge can be traced to its source: a T2 row, a T3 row, or a rule over
them. Judgement never overwrites a fact in place. It is a separate tier, so a
re-extraction refreshes the facts and leaves the judgement to be re-checked
against them (G8).

*Checked by:* the tables of each tier are separate files with separate
owners: T1/T2 regenerated by `extract-ql`, T3 and the ownership store tracked
with the project.

## Rules

### G10. General rules, no overfitting

A mechanical rule (a query, a composer step, a script) follows from C's
semantics and holds for every codebase. It does not:

- match names, prefixes or paths of one codebase (`git_*`, `src/util/`), or
  conventions only some codebases follow; C's own reserved names
  (`__builtin_*`) are C's semantics, not a convention;
- special-case the entity that motivated it;
- count on one codebase's shape: a header layout, a naming scheme, a build
  system.

A case the general rule gets wrong is a T3 correction (G7), or a documented
limitation (G12), until a general rule covers it. A rule written for a corner
case is not accepted because it fixes the corner case.

*Checked by:* each rule has a minimal fixture written for it, and is validated
on a codebase other than the one that motivated it, with a before/after
schedule diff that changes only what the rule says it changes.

### G11. Every change is measured on real code

A change to a query, composer or rule is run on at least one real codebase
before it lands, and its effect stated: how many units, edges, cuts or
fields changed, and that nothing else did. An unexplained difference is a
defect until it is explained.

*Checked by:* the commit message states the measured effect.

### G12. Limits are stated, not hidden

Every known false negative and false positive class is documented, with the
correction a judge can make for it. When Wavefront drops, narrows or merges
something (an entity no seed reaches, two same-tag definitions merged by the
database), it says so in its output or its documentation, not by omission.

*Checked by:* [`graph.md`](graph.md#assumptions-and-limitations) lists every
class, and the commands warn where an input leaves something out.

## Interface

### G13. Deterministic and reproducible

The same database, config and T3 tables produce the same bytes. Caches are
keyed by every input that affects their content and by a version bumped when
a composer's output changes, so a cache never returns what the current code
would not compute.

*Checked by:* golden tests over the composed artifacts, and a cache version
bump in every commit that changes composed output.

### G14. Selection never moves the order

Seeds, modules and caps select and pack units; they never change the order
those units take. The order is computed over every unit of the closure, so a
narrow schedule keeps the order and cuts of the whole, and a schedule grown
later agrees with the one before it.

*Checked by:* a schedule of a subset lists its units in the order the full
schedule gives them.

### G15. Versioned artifacts, migrated

Every artifact a consumer reads has a documented schema with a version. A
change of meaning is a new version with its history recorded, and existing
campaigns are migrated to it. Wavefront does not carry compatibility layers
for old schemas.

*Checked by:* each schema document has a version history, and the examples
match the current version.

### G16. C first

Wavefront targets C. C++ is added beside C, not folded into it: its
entities and edges (classes, templates, overloads) get their own facts, and
what the two share is factored out from what they actually share, without
changing what a C campaign reads.

*Checked by:* a C codebase's artifacts are unchanged by a C++ addition.

## Non-goals

- **Data-flow and points-to analysis.** See G1. Where they would be needed,
  a judge decides.
- **Deciding ownership or lifecycles.** Wavefront stores and returns the
  ownership facts judges record; it does not infer them.
- **Translating or binding.** Wavefront orders the work and states what each
  item depends on; writing the Rust is its consumers'.
- **An optimal order.** Cuts follow a deterministic greedy rule, not a
  minimum feedback arc set. Determinism and explicit cuts matter more than
  the fewest cuts.
- **Configurations the build did not trace.** See G3.

## Known departures

- Some composers still parse C type strings (`types_manifest.py`'s array and
  element patterns, `deps_dag.py`'s base type names) where a query could
  emit the structured fact (G1, G10).
- A seed that lists items drops its file's other macros without a warning
  (G12).
- Casts are keyed by tag alone, so two unrelated types sharing a tag share
  their cast edges (G2).
