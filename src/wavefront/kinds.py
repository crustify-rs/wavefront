"""What an entity is in C: its ``kind``, the one vocabulary the schedule, the
config's items and ``query`` share.

A kind is ``function``, ``global``, ``macro``, ``struct``, ``union``,
``enum``, ``function_pointer`` or ``typedef``. A typedef folds into what it
names: into the struct, union or enum, its identity when that one has no tag
(`typedef struct { ... } T;`), or into the function pointer, which the
typedef declaring it identifies; each such entity lists the typedefs naming
it. A typedef that names none of them, a primitive or a pointer, is a
``typedef`` of its own. A function pointer written inline is a
``function_pointer`` too, identified by its signature and the file it is
written in. A generator macro is a ``macro``, whatever it mints.

The tables classify entities more finely, by linkage (``function_static``,
``global_extern``, ...) or by shape (``callback``, a function-pointer
typedef); :func:`of` folds that
class into the kind, and the rest of it is a property of the declaration
(``static``, ``inline``, ``exported``), not a kind.

C keeps tags and ordinary identifiers apart: a struct, union or enum lives in
the tag namespace, ``type``, and every other kind among the ordinary
identifiers, ``symbol``. The graph keys a node by its namespace, so a struct
and a function of one name in one file are two nodes.
"""
from __future__ import annotations

KINDS = ("function", "global", "macro", "struct", "union", "enum",
         "function_pointer", "typedef")

#: The kinds of the tag namespace.
TAG_KINDS = ("struct", "union", "enum")

#: The plural each kind's `query` subject takes.
PLURAL = {k: k + "s" for k in KINDS}

def of(subkind: str | None, namespace: str | None = None) -> str | None:
    """The kind of a table class or graph subkind: ``function_static`` is a
    ``function``, ``callback`` a ``function_pointer``. ``None`` for one that names no
    kind, such as the ``external`` placeholder of a node the closure only
    reaches."""
    sub = subkind or ""
    if sub in TAG_KINDS:
        return sub
    if namespace == "type":
        return None
    if sub in ("callback", "function_pointer"):
        return "function_pointer"
    if sub == "typedef":
        return "typedef"
    for kind in ("function", "global", "macro"):
        if sub.startswith(kind):
            return kind
    return None


def namespace(kind: str) -> str:
    """The namespace a kind lives in: ``type`` for a tag, ``symbol`` else."""
    return "type" if kind in TAG_KINDS else "symbol"


class Index:
    """The kind of every entity of one set of T1 tables, keyed as the graph
    keys a node: ``(name, home, namespace)``, the home its definition file or,
    for an entity defined nowhere, each file that declares it. A name only one
    entity of a namespace bears answers for any home, so an external node the
    composer homes at a declaration the tables do not list still resolves."""

    def __init__(self, t1) -> None:
        from pathlib import Path

        from compose.scope import load_csv

        def rows(name: str) -> list[dict]:
            path = Path(t1) / name
            return load_csv(path) if path.is_file() else []

        self._exact: dict[tuple[str, str, str], str] = {}
        by_name: dict[tuple[str, str], set[str]] = {}

        def add(name: str, kind: str | None, files) -> None:
            if not name or kind is None:
                return
            ns = namespace(kind)
            for f in files:
                self._exact.setdefault((name, f, ns), kind)
            by_name.setdefault((name, ns), set()).add(kind)

        def homes(row: dict) -> list[str]:
            decls = [d for d in (row.get("decl_files") or "").split("|") if d]
            return [row.get("def_file") or ""] + decls

        for row in rows("functions.csv"):
            add(row["name"], "function", homes(row))
        for row in rows("globals.csv"):
            add(row["name"], "global", homes(row))
        for row in rows("macros.csv"):
            add(row["name"], "macro", [row.get("def_file") or ""])
        from compose import scope as compose_scope

        types = rows("types.csv")
        type_index = compose_scope.build_types_index(types)
        for row in types:
            kind = row.get("kind")
            if kind == "typedef":
                # The typedef declaring a function pointer is it; one naming an
                # untagged type is that type; a typedef of its own is a
                # typedef; an alias folds into what it names, and is none.
                unalias = row.get("unaliased_kind") or ""
                kind = ("function_pointer" if unalias == "callback"
                        else unalias.split("_")[0] if unalias.endswith("_anonymous")
                        else "typedef" if compose_scope.own_typedef(row, type_index)
                        else None)
            add(row["name"], of(kind), homes(row))
        # The typedefs naming each struct, union, enum or function pointer,
        # the one that identifies an untagged type or declares a function
        # pointer aside: every alias, a same-named one too, chains included.
        self._aliases: dict[tuple[str, str], set[str]] = {}
        for row in types:
            cls = compose_scope.typedef_class(row, type_index)
            if cls is None or cls[0] == compose_scope.OWN_TYPEDEF or cls[1] is row:
                continue
            end = cls[1]
            ns = "symbol" if cls[0] == compose_scope.FOLDS_CALLBACK else "type"
            self._aliases.setdefault((end["name"], ns), set()).add(row["name"])
        # Function pointers written inline, by signature and home.
        fp_path = Path(t1).parent / "t2" / "function_pointer_uses.csv"
        if fp_path.is_file():
            for row in load_csv(fp_path):
                add(row["signature"], "function_pointer", [row["def_file"]])
        self._unique = {k: next(iter(v)) for k, v in by_name.items() if len(v) == 1}

    def typedefs(self, name: str, ns: str) -> list[str]:
        """The typedefs that name the struct, union, enum or function pointer
        ``name`` of namespace ``ns`` and fold into it, sorted."""
        return sorted(self._aliases.get((name, ns), ()))

    def kind(self, name: str, home: str | None, ns: str) -> str | None:
        """The kind of ``(name, home, ns)``, or ``None`` when the tables do
        not say: a compiler builtin, or a name several kinds bear."""
        if name.startswith("__builtin_") and ns == "symbol":
            return "function"
        return (self._exact.get((name, home or "", ns))
                or self._unique.get((name, ns)))
