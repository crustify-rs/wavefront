# Scoping

A config names the files a project owns. Wavefront composes from them, in
memory, an inventory with two sections and one view; nothing is written to
disk. Field meaning of the config itself is in the
[README](../README.md#inputs).

## Files

`impl_files` names the sources and private headers that implement the
library, and `api_headers` the headers that publish it. An entry ending in
`/` expands to every C or C++ source and header beneath it; an entry
matching `out_of_scope.paths` is removed. The resulting candidates are then
anchored on the T1 tables: a file the traced build never compiled, or whose
body an `#ifdef` elides, contributes no entities.

## Items

A config owns its files whole by default. Two optional lists narrow it to entities, so
that two configs can share a file and split what it defines:

- `items` names the only entities the config owns: its targeted section holds those of
  its files' entities that the list names, and nothing else;
- `out_of_scope.items` names entities the config never owns, although its files define
  or publish them.

Each entry is `{"name": ..., "defined_in": ...}`: the entity's name and the
repo-relative file of its definition, or of its declarations when the database holds no
definition. A typedef follows the type it names, so naming a struct or its typedef
selects both. A header macro is imported in every config, as the Targeted section
describes, so an entry cannot select one.

An entity a list names but the config's files do not define or publish is an error, as
is one both lists name. An entity left out of a config's targeted section by either list
is not dropped: whatever reaches it imports it, as the Imported section describes.

The lists are the counterparts of one another across configs. A config narrowed by
`items` shares its files with the config that owns the rest of them, which names the same
entities in `out_of_scope.items`, so that each entity is targeted by exactly one config
and scheduled once. A project-wide config, whose files are the union of every config's,
sets neither list and owns everything.

## Targeted

The **targeted** section is what the config owns: every entity whose
definition sits in `impl_files` or `api_headers`, narrowed by its
[items](#items). An entity with no
definition in the database is targeted when all of its declarations sit in
those files. A typedef takes the section of the type it finally names, so a
typedef and its struct never fall on opposite sides. A macro defined in a
header is always imported, since any C still built may include that header;
only a macro defined in a targeted `.c` file is targeted.

## Imported

The **imported** section is derived: everything the targeted entities
reach that the config does not own, its external frontier. Two walks build
it:

- **symbols**: from each targeted function, through its callees and the
  types its signature and body name; a reached function the config does not
  own is imported, and is not walked further;
- **types**: through the field graph. A targeted struct is walked through
  every field; an imported one only through the fields targeted code
  accesses. This pulls in a type embedded by value (`pthread_mutex_t`).

An imported item's declaring headers are narrowed to those the targeted
translation unit that reached it actually includes, through the build's
include graph. An item imported through more than one header is marked
`reexport`.

## API view

The **api** view is what `api_headers` publish: every entity declared there,
or defined there outright (an inline function, a macro, a struct with its
layout). It is not a section. Publication and ownership are independent, so
an entity is in the view and in whichever section owns it: a function an
`api_headers` file declares but that some other library defines is api and
imported at once, which is what a re-export is.

## Default mode

The default graph and schedule are body-deep:

- a targeted function depends on what its body calls and touches; an
  imported function contributes its signature only;
- a struct defined in a targeted file keeps every field edge; an imported
  struct only the fields targeted code accesses;
- a schedule seeds from targeted and imported nodes, and `--transitive`
  adds the imported items the closure reaches. They are scheduled with the
  rest, in symbol batches of their own section.

## API mode

`--api-headers-only` reads the library as its public interface:

- every function contributes its signature only, targeted or not;
- only a struct the `api_headers` define keeps its field edges; any other
  is an opaque handle;
- only a generator macro the `api_headers` define mints instances: one
  defined elsewhere orders no API type;
- the **API closure** is what the public signatures and fields reach from
  the api view, walked before any cast edge exists. Cast edges are added
  only between its nodes ([`graph.md`](graph.md#type-erasure)), so a cast
  never pulls a type into the closure;
- a schedule seeds only from the api view, and holds only items the config
  owns, after its [items](#items) narrow it. An imported item is a node of the graph and a dependency of the
  items that reach it, but not a unit: the config whose `api_headers` own it
  schedules it, after its own fields. `query dag --name X --imported-only`
  lists X's imported dependencies.

A library split into several configs is therefore scheduled once per
config, each schedule holding its own items. The relations between configs,
including cast edges whose two ends two configs own, show in the graph of a
project-wide config whose `api_headers` are their union.

## Queries

`--targeted-only`, `--imported-only` and `--api-only` filter `query` output by
section and view. They intersect: `--api-only --imported-only` keeps
re-exports. `query files` lists each set's files.
