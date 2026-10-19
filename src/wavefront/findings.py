"""findings.py — split a record into what wavefront composes and what users find.

Internally a record is one merged entry: the composer's structure with the
ownership store overlaid (:mod:`wavefront.manifests`), which is what the
searches read. A reader sees it split in two:

    {"composed": {...}, "findings": {...}, "_analysis": {...}}

``composed`` is the structure, with every user-owned slot removed.
``findings`` is every slot a user may fill for the entity -- ``null`` where
nothing is submitted -- in exactly the shape ``query ... --update`` accepts,
so a reader can fill in the record's own ``findings`` and submit it. See
``docs/artifacts/findings.md``.
"""
from __future__ import annotations

import copy

#: User-owned keys on a type field, in submission order.
FIELD_KEYS = ("ptr", "refcount", "locked_by")
#: User-owned keys at a type record's top level.
TYPE_KEYS = ("_comment_user",)
#: User-owned keys at a symbol record's top level.
SYM_KEYS = ("lifetime", "ptr", "locked_by", "_comment_user")


def _is_pointer_field(f: dict) -> bool:
    return f.get("ref") == "pointer"


def type_findings(entry: dict, keep: set | None = None) -> dict:
    """The type's findings: its note, and every field's slots. ``keep``
    narrows the fields, as ``--targeted-only`` / ``--imported-only`` do."""
    fields = {}
    for f in entry.get("fields") or []:
        if not isinstance(f, dict) or (keep is not None and f.get("name") not in keep):
            continue
        slot = {}
        if _is_pointer_field(f):
            slot["ptr"] = f.get("ptr")
        slot["refcount"] = bool(f.get("refcount"))
        slot["locked_by"] = f.get("locked_by")
        fields[f.get("name")] = slot
    return {"_comment_user": entry.get("_comment_user"), "fields": fields}


def type_composed(entry: dict, keep: set | None = None) -> dict:
    """The type's record less its findings. ``keep`` narrows the fields."""
    out = {k: copy.deepcopy(v) for k, v in entry.items()
           if k not in TYPE_KEYS and k != "_analysis"}
    out["fields"] = composed_fields(entry.get("fields") or [], keep)
    return out


def composed_fields(fields: list, keep: set | None = None) -> list:
    return [{k: copy.deepcopy(v) for k, v in f.items() if k not in FIELD_KEYS}
            for f in fields
            if isinstance(f, dict) and (keep is None or f.get("name") in keep)]


def _ptr_slots(entry: dict) -> dict:
    out = {}
    args = {a.get("name"): {"ptr": a.get("ptr")}
            for a in entry.get("ptr_args") or [] if isinstance(a, dict)}
    out["ptr_args"] = args
    if isinstance(entry.get("ptr_ret"), dict):
        out["ptr_ret"] = {"ptr": entry["ptr_ret"].get("ptr")}
    return out


def symbol_findings(entry: dict, forks: list[dict] | None = None) -> dict:
    """The symbol's findings. A global takes ``ptr`` and ``locked_by``; a
    function or callback its arguments, return and ``lifetime``; a callback's
    primary its ``forks`` too, and a fork its ``callsites``. ``forks`` is the
    primary's fork records, already merged."""
    kind = entry.get("kind") or ""
    if kind.startswith("global"):
        return {"ptr": entry.get("ptr"), "locked_by": entry.get("locked_by")}
    if kind.startswith("macro"):
        return {}
    out = _ptr_slots(entry)
    out["lifetime"] = entry.get("lifetime")
    if kind == "callback":
        if entry.get("variant"):
            out["callsites"] = list((entry.get("used_by") or {}).get("call") or [])
        else:
            out["forks"] = [{**symbol_findings(fk), "callsites":
                             list((fk.get("used_by") or {}).get("call") or [])}
                            for fk in forks or []]
            for fk in out["forks"]:
                fk.pop("forks", None)
    return out


def symbol_composed(entry: dict) -> dict:
    """The symbol's record less its findings."""
    out = {k: copy.deepcopy(v) for k, v in entry.items()
           if k not in SYM_KEYS and k != "_analysis"}
    out["ptr_args"] = [{k: v for k, v in a.items() if k != "ptr"}
                       for a in entry.get("ptr_args") or [] if isinstance(a, dict)]
    if isinstance(entry.get("ptr_ret"), dict):
        out["ptr_ret"] = {k: v for k, v in entry["ptr_ret"].items() if k != "ptr"}
    return out


def split_type(entry: dict, keep: set | None = None) -> dict:
    return {"composed": type_composed(entry, keep),
            "findings": type_findings(entry, keep),
            "_analysis": entry.get("_analysis")}


def split_symbol(entry: dict, forks: list[dict] | None = None) -> dict:
    return {"composed": symbol_composed(entry),
            "findings": symbol_findings(entry, forks),
            "_analysis": entry.get("_analysis")}
