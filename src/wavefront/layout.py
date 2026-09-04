"""Filesystem layout for the standalone oracle capability."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

_REPO_ROOT: Path | None = None
_CONFIG_PATH: Path | None = None


def set_repo_root(repo_root: Path) -> None:
    global _REPO_ROOT
    _REPO_ROOT = Path(repo_root).resolve()


def set_config_path(config_path: Path | None) -> None:
    """Set the explicit config used by extraction, queries, and scheduling."""
    global _CONFIG_PATH
    _CONFIG_PATH = None if config_path is None else Path(config_path).resolve()


def find_repo_root(start: Path) -> Path:
    return _REPO_ROOT if _REPO_ROOT is not None else Path(start).resolve()


class Layout:
    """Repository and explicitly configured Wavefront state paths."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        config_path = self.config()
        try:
            config = json.loads(config_path.read_text())
        except (OSError, ValueError) as exc:
            raise SystemExit(f"invalid Wavefront config at {config_path}: {exc}")
        state_dir = config.get("state_dir")
        if not isinstance(state_dir, str) or not state_dir.strip():
            raise SystemExit(
                f"Wavefront config at {config_path} needs a non-empty state_dir")
        root = Path(state_dir)
        self.root = (root if root.is_absolute() else self.repo_root / root).resolve()

    @classmethod
    def discover(cls, start: Path) -> "Layout":
        return cls(find_repo_root(start))

    @property
    def codeql(self) -> Path:
        return self.root / "codeql"

    @property
    def t1(self) -> Path:
        return self.codeql / "t1"

    @property
    def t2(self) -> Path:
        return self.codeql / "t2"

    @property
    def codeql_db(self) -> Path:
        return self.codeql / "db"

    @property
    def ownership_store(self) -> Path:
        return self.root / "ownership-store.json"

    @property
    def cache_dir(self) -> Path:
        return self.root / ".cache"

    def config(self, _scope: Path | None = None) -> Path:
        if _CONFIG_PATH is None:
            raise RuntimeError("wavefront config path was not set")
        return _CONFIG_PATH

    def config_provenance(self) -> dict[str, str]:
        config = self.config()
        try:
            path = config.relative_to(self.repo_root).as_posix()
        except ValueError:
            path = str(config)
        return {
            "path": path,
            "sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        }

    def deps_dag(self, _scope: Path | None = None, *,
                 api_headers_only: bool = False) -> Path:
        suffix = "api" if api_headers_only else "full"
        digest = self.config_provenance()["sha256"]
        return self.cache_dir / "configs" / digest / f"deps-dag.{suffix}.json"
