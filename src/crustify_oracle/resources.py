"""Locate source-owned schemas and CodeQL queries in a checkout or wheel."""
from __future__ import annotations

import sysconfig
from pathlib import Path


def source_root() -> Path | None:
    """Repository root for an editable/source install, when present."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "qlpack.yml").is_file() else None


def data_root() -> Path:
    """Installed CodeQL pack root."""
    source = source_root()
    if source is not None:
        return source
    return Path(sysconfig.get_path("data")) / "share" / "wavefront"


def schema_dir() -> Path:
    """Directory containing the type and symbol record schemas."""
    source = source_root()
    if source is not None:
        return source / "docs" / "schemas"
    return data_root() / "schemas"
