"""cache.py — fingerprinted on-disk caches for the composed artifacts.

The dependency graph is a pure function of `oracle-config.json` and the CodeQL
tables. It is cached privately under `crustify/oracle/.cache/`; the in-memory
inventory is never persisted.

`_VERSION` is the composer's contribution to the fingerprint: bump it when a
composer changes what it emits from unchanged inputs.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

#: Bump when a composer's OUTPUT changes for unchanged inputs.
#:  1 — pair-keyed type nodes; `deps.types` carries `defined_in`.
#:  3 — `wrap.anchors`; anonymous tags dropped from `wrap.types`.
#:  4 — dag keeps every field of an anchor-DEFINED wrap struct.
#:  5 — anchored `declared_in` falls back to one canonical header, not all.
#:  6 — sections renamed port/wrap -> target/import; anchors removed.
#:  7 — authored config split into impl_files/api_headers;
#:      sections renamed target/import -> targeted/imported.
#:  8 — scope is objective-independent: `targeted` is impl+api on both
#:      campaigns, `imported` is always the external closure, and the new
#:      `api` view carries the declaration-anchored public surface. The
#:      seeded import walk and `imported.seeds` are gone.
_VERSION = 9


def fingerprint(layout, target) -> dict:
    """The identity of every input the scope / dag composers read.

    `oracle-config.json` by content hash. The CSVs by `(size, mtime_ns)`:
    `codeql/` is shared, so every worktree sees one inode.

    `ownership-store.json` is not an input — neither artifact depends on agent
    submissions.
    """
    inputs: dict[str, object] = {}

    # `oracle-config.json` is hashed, not stat'd. It is tracked, so every
    # worktree may hold its own copy with a different checkout mtime. Content
    # hashing keeps cache identity stable across those checkouts.
    cfg = layout.config(target)
    try:
        inputs["oracle-config.json"] = hashlib.sha256(cfg.read_bytes()).hexdigest()
    except OSError:
        inputs["oracle-config.json"] = None    # absent is itself a state

    # The CSVs stay on (size, mtime): they live under `codeql/`, which IS
    # shared, so every worktree sees the same inode and the same mtime. Hashing
    # 100 MB per query to learn what a stat already settles is the worse trade.
    for d in (layout.t1, layout.t2):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.csv")):
            try:
                st = p.stat()
            except OSError:
                inputs[p.name] = [-1, -1]
                continue
            inputs[p.name] = [st.st_size, st.st_mtime_ns]
    return {"version": _VERSION, "inputs": inputs}


def load(path: Path, fp: dict) -> dict | None:
    """The cached artifact when its fingerprint still matches, else ``None``.

    Any read failure — missing, truncated, not JSON — reads as a miss.
    """
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("_fingerprint") != fp:
        return None
    return doc


def atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` atomically, preserving the file's mode.

    The mode of the file being replaced wins; a new file gets 0644. Reading the
    umask instead would need `os.umask` twice, which races the scheduler's
    thread pool. The temp file is created in the destination directory so the
    rename cannot cross a filesystem.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = p.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    tmp = tempfile.NamedTemporaryFile(
        "w", dir=str(p.parent), delete=False, suffix=".tmp")
    try:
        try:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        finally:
            tmp.close()
        os.chmod(tmp.name, mode)
        os.replace(tmp.name, p)
    except BaseException:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def store(path: Path, doc: dict, fp: dict) -> dict:
    """Write `doc` with its fingerprint attached, atomically, and return it.

    A cache write failure is swallowed; a cache must not take the query with it.
    """
    doc = {"_fingerprint": fp, **doc}
    try:
        atomic_write(path, json.dumps(doc, indent=1) + "\n")
    except OSError:
        pass                      # a cache must not take the query with it
    return doc


def strip(doc: dict) -> dict:
    """The artifact without its cache bookkeeping, for `--dump`."""
    return {k: v for k, v in doc.items() if k != "_fingerprint"}
