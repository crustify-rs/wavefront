# Scoping

A config names the program Wavefront analyzes, its `closure`, and what
`wavefront schedule` orders, its `schedule_seeds`. From the closure Wavefront
composes, in memory, an inventory with two sections and one view; nothing is
written to disk. Field meaning of the config itself is in the
[README](../README.md#inputs).

## Files

`closure.impl_files` names the sources and private headers that implement the
program, and `closure.api_headers` the headers that publish it, each as two
lists: `included` names files and directories, and the optional `excluded`
removes what they would otherwise select. An entry ending in `/` expands to
every C or C++ source and header beneath it, in either list; a file an
`included` entry selects is removed when it matches its key's `excluded` list.
The resulting candidates are then anchored on the T1 tables: a file the traced
build never compiled, or whose body an `#ifdef` elides, contributes no
entities.

The closure is the whole program: the graph, every query and the usage counts
of a schedule's items ([`artifacts/schedule.md`](artifacts/schedule.md#statistics))
read it, whatever part of it a schedule covers. Code the closure leaves out,
such as a test suite, is no use of the program's entities.

## Modules

`modules`, optional, groups the closure's units for `wavefront schedule`
([`batching.md`](batching.md#order)). It lists module records,
`{"name": ..., "files": [...]}`: a unique name and file entries, each as
[`schedule_seeds`](#schedule-seeds) writes one. A module claims the units
whose home is one of its files, its defining file or, without one, its
declaration, as its items narrow them. A shared header is split this way,
each module naming the items it defines that the module takes, and a TU
between two modules, one `included` and the other `excluded` the same items.
An item names an entity its file is home to: one its file only declares, its
definition elsewhere, is an error, since the module would not claim it. A
unit two modules claim is an error, and a module that claims no unit of the
closure is warned of. `modules` may cover only part of the closure: the
modules of what a schedule holds, its seeds and every unit they depend on. A
unit the schedule holds that no module claims is ordered alone, and warned
of; one it does not reach needs no module.

## Schedule seeds

`schedule_seeds`, optional, names the units `wavefront schedule` starts from
([`batching.md`](batching.md)). It lists file entries, each a path, a
directory written with a trailing slash, or
`{"path": ..., "items": {"included": [...], "excluded": [...]}}`. A file
seeds the targeted entities it defines or declares: `src/libgit2/repository.c`
the functions it defines, and `include/git2/repository.h` those it declares,
wherever they are defined. A schedule holds its seeds and every unit they
depend on, so that it is complete on its own. A config without
`schedule_seeds` seeds every targeted entity.

Each item is `{"name": ..., "kind": ...}`, an entity its file defines or
declares: its name, and its kind, `type` for a struct, union or enum tag or a
typedef, `symbol` for a function, global, macro or callback typedef. C keeps
tags apart from ordinary identifiers, so a struct and a function or global may
share a name in one file, as `static const struct typelen {...} typelen[]`
does; the kind tells them apart. `included` seeds only the entities it names
of its file, `excluded` none of those it names; an item that names no such
entity, or that both lists name, is an error, as is a file outside the
closure. A directory names the closure's files under it, and takes no items;
one that holds none is an error.

The seeds never change the order: a schedule orders every unit of the
closure and keeps the ones it holds in it, so that schedules of several seeds
are parts of one order, and the selections a consumer makes, by file, module
or any other grouping, of a schedule are too. Two schedules hold
the dependencies they share both; each item's key tells them apart.

## Targeted

The **targeted** section is what the closure owns: every entity whose
definition sits in `impl_files` or `api_headers`. An entity with no
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
- a schedule orders every targeted node; an imported node is a dependency
  of the units that reach it, never a unit.

## API mode

`--api-headers-only` reads the library as its public interface:

- every function contributes its signature only, targeted or not;
- only a struct the `api_headers` define keeps its field edges; any other
  is an opaque handle;
- only a generator macro the `api_headers` define mints instances: one
  defined elsewhere orders no API type;
- the **API reach** is what the public signatures and fields reach from
  the api view, walked before any cast edge exists. Cast edges are added
  only between its nodes ([`graph.md`](graph.md#type-erasure)), so a cast
  never pulls a type into the reach;
- a schedule seeds only from the api view, and holds what those seeds reach
  of the targeted nodes. An imported item is a node of the
  graph and a dependency of the items that reach it, but not a unit.
  `query dag --name X --imported-only` lists X's imported dependencies.

A library is scheduled from a config whose closure covers it, so that the
relations between its parts, cast edges included, are in the one graph its
schedules order them on; a [`schedule_seeds`](#schedule-seeds) selects the part each one
holds.

## Queries

`--targeted-only`, `--imported-only` and `--api-only` filter `query` output by
section and view. They intersect: `--api-only --imported-only` keeps
re-exports. `query files` lists each set's files.
