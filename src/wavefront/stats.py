"""Per-item statistics a consumer weighs an item's work by.

Read off the T1/T2 tables: the properties of the item's declaration (its
linkage, `inline`, `const`, a function-like macro, what a typedef names, a
type named only by its typedef), what it is made of (fields,
parameters, body lines) and how much of the codebase touches it (callers,
field touchers, users). A property the tables do not record is `null`. A use counts only when it sits in one of the config's
files, whatever a schedule selects: code the closure does not name,
such as a test suite or the system headers, would skew them. They are
objective-neutral: a consumer decides what each count costs for its own work,
and how many items one batch can take.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from compose.scope import load_csv

_QUALIFIERS = re.compile(r"\b(const|volatile|restrict)\b")


def _csv(path: Path) -> list[dict]:
    return load_csv(path) if path.is_file() else []


def _true(value) -> bool:
    return str(value).lower() in ("true", "1")


def _type() -> dict:
    return {"fields": 0, "pointer_fields": 0, "erased_fields": 0}


def top_level_const(ctype: str) -> bool:
    """Whether a declared C type is itself `const`: `const int` and
    `char *const` are, `const char *` is not, its pointee being. An array of
    `const` elements is, as nothing of it can be written."""
    outer = ctype.rsplit("*", 1)[1] if "*" in ctype else ctype
    return "const" in re.findall(r"\w+", outer)


def _flag(row: dict, column: str):
    """A `0`/`1` column, or `None` when the table predates it."""
    value = row.get(column)
    return None if value in (None, "") else _true(value)


class Stats:
    """The statistics of every node of one set of tables, keyed by
    ``(name, defined_in, kind)`` as the dag keys its nodes."""

    def __init__(self, t1: Path, t2: Path, files: set[str]) -> None:
        """``files``: the config's files, where a use counts."""
        # A struct, union or enum without a tag of its own, named by the
        # typedef that is its identity (`typedef struct { ... } T;`).
        self._anonymous = {
            (row["name"], row.get("def_file") or "")
            for row in _csv(t1 / "types.csv")
            if row.get("kind") == "typedef" and row.get("unaliased_kind") in (
                "struct_anonymous", "union_anonymous", "enum_anonymous")}
        # What a typedef of its own names, as C writes it.
        self._base_types = {
            row["name"]: row.get("base_type") or row.get("aliases") or None
            for row in _csv(t1 / "types.csv") if row.get("kind") == "typedef"}
        self._function_like = {
            (row["name"], row.get("def_file") or ""):
                (row.get("head") or "").startswith(row["name"] + "(")
            for row in _csv(t1 / "macros.csv")}

        self._types: dict[tuple[str, str], dict] = defaultdict(_type)
        for row in _csv(t1 / "fields.csv"):
            entry = self._types[(row["struct_name"], row.get("struct_def_file") or "")]
            entry["fields"] += 1
            entry["pointer_fields"] += int(row.get("ptr_depth") or 0) > 0
            entry["erased_fields"] += _true(row.get("is_erased"))

        touchers: dict[tuple[str, str], set] = defaultdict(set)
        accesses: dict[tuple[str, str], int] = defaultdict(int)
        body_accesses: dict[tuple[str, str], int] = defaultdict(int)
        for row in _csv(t2 / "field_accesses.csv"):
            if row.get("access_file") not in files:
                continue
            struct = (row["struct_name"], row.get("struct_def_file") or "")
            accesses[struct] += 1
            if row.get("enclosing_name"):
                user = (row["enclosing_name"], row.get("access_file") or "")
                touchers[struct].add(user)
                body_accesses[user] += 1
        self._touchers = {k: len(v) for k, v in touchers.items()}
        self._accesses = dict(accesses)

        self._functions: dict[tuple[str, str], dict] = {}
        for row in _csv(t1 / "functions.csv"):
            key = (row["name"], row.get("def_file") or "")
            head = (row.get("signature") or "").split(row["name"] + "(", 1)[0]
            static = _flag(row, "is_static")
            inline = _flag(row, "is_inline")
            self._functions[key] = {
                "static": static,
                "exported": None if static is None else not static,
                "inline": inline,
                "loc": int(row.get("loc") or 0),
                "params": 0, "pointer_params": 0, "erased_params": 0,
                "returns_pointer": "*" in head,
                "variadic": _true(row.get("is_variadic")),
                "callers": 0, "callees": 0,
                "field_accesses": body_accesses.get(key, 0),
            }
        for row in _csv(t1 / "params.csv"):
            entry = self._functions.get(
                (row["function_name"], row.get("function_def_file") or ""))
            if entry is None:
                continue
            entry["params"] += 1
            entry["pointer_params"] += int(row.get("ptr_depth") or 0) > 0
            entry["erased_params"] += _true(row.get("is_erased"))
        callers: dict[tuple[str, str], set] = defaultdict(set)
        callees: dict[tuple[str, str], set] = defaultdict(set)
        for row in _csv(t2 / "function_calls.csv"):
            caller = (row["caller_name"], row.get("caller_file") or "")
            callee = (row["callee_name"], row.get("callee_def_file") or "")
            callees[caller].add(callee)
            if caller[1] in files:
                callers[callee].add(caller)
        for key, entry in self._functions.items():
            entry["callers"] = len(callers.get(key, ()))
            entry["callees"] = len(callees.get(key, ()))

        users: dict[tuple[str, str], set] = defaultdict(set)
        for row in _csv(t2 / "global_accesses.csv"):
            if row.get("enclosing_name") and row.get("access_file") in files:
                users[(row["global_name"], row.get("global_def_file") or "")].add(
                    (row["enclosing_name"], row.get("access_file") or ""))
        self._globals: dict[tuple[str, str], dict] = {}
        for row in _csv(t1 / "globals.csv"):
            key = (row["name"], row.get("def_file") or "")
            ctype = row.get("type") or ""
            static = row.get("linkage") == "global_static"
            self._globals[key] = {
                "static": static,
                "exported": not static,
                "const": top_level_const(ctype),
                "pointer": "*" in ctype,
                "erased": _QUALIFIERS.sub(" ", ctype).split() == ["void", "*"],
                "users": len(users.get(key, ())),
            }

    def of(self, name: str, defined_in: str | None, kind: str,
           source_kind: str | None) -> dict:
        """The item's statistics. ``source_kind`` is the class the tables give
        the C entity (``function_static``, ``global_extern``, ``struct``,
        ``macro``, ``callback``, ...), which picks them; it is no statistic,
        its linkage being the properties ``static`` and ``exported``."""
        home = defined_in or ""
        sub = source_kind or ""
        out: dict = {}
        if kind == "type":
            out["anonymous"] = (name, home) in self._anonymous
            out.update(self._types.get((name, home)) or _type())
            out["field_touchers"] = self._touchers.get((name, home), 0)
            out["field_accesses"] = self._accesses.get((name, home), 0)
        elif sub.startswith("function"):
            out.update(self._functions.get((name, home)) or {})
        elif sub.startswith("global"):
            out.update(self._globals.get((name, home)) or {})
        elif sub.startswith("macro"):
            out["function_like"] = self._function_like.get((name, home))
        elif sub == "typedef":
            out["base_type"] = self._base_types.get(name)
        return out
