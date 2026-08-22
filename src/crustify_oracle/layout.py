"""Filesystem layout for the standalone oracle capability."""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT: Path | None = None


def set_repo_root(repo_root: Path) -> None:
    global _REPO_ROOT
    _REPO_ROOT = Path(repo_root).resolve()


def find_repo_root(start: Path) -> Path:
    return _REPO_ROOT if _REPO_ROOT is not None else Path(start).resolve()


class Layout:
    """All semantic artifacts live below ``<repo>/crustify/oracle``."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.crustify = self.repo_root / "crustify"
        self.root = self.crustify / "oracle"

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

    def rel_target(self, target: Path) -> str:
        resolved = Path(target).resolve()
        return "." if resolved == self.repo_root else resolved.relative_to(self.repo_root).as_posix()

    def target_dir(self, target: Path) -> Path:
        return self.root / "targets" / self.rel_target(target)

    def config(self, target: Path) -> Path:
        return self.target_dir(target) / "oracle-config.json"

    def deps_dag(self, target: Path, *, api_headers_only: bool = False) -> Path:
        suffix = "api" if api_headers_only else "full"
        return self.cache_dir / "targets" / self.rel_target(target) / f"deps-dag.{suffix}.json"
