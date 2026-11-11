"""Shared helpers for the C++ fixture tests.

A fixture directory holds the C++ sources, a `wavefront-config.json`, and
the recorded `t1/` and `t2/` tables that `wavefront extract-ql` produced
for them. `stage` lays a fixture out as a Wavefront repository so the CLI
runs on the recorded tables; `extract` rebuilds the tables with CodeQL.
"""
from __future__ import annotations

import csv
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from wavefront.resources import data_root

TIERS = ("t1", "t2")


def rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def key(row: dict) -> tuple:
    return tuple(row[k] for k in sorted(row))


# Columns naming the file that defines a row's function or type.
DEFINITION_COLUMNS = ("def_file", "function_def_file")


def in_repo(table: list[dict], markers: tuple[str, ...]) -> list[tuple]:
    """Rows that mention one of the fixture's markers (its files, its
    namespaces) and that describe a defined entity. Compiler builtins,
    system headers, and the members a compiler declares implicitly (an empty
    definition file) vary between hosts and CodeQL releases and are not the
    fixture's."""
    kept = []
    for row in table:
        if any(row.get(column) == "" for column in DEFINITION_COLUMNS):
            continue
        if any(marker in value for marker in markers for value in row.values()):
            kept.append(key(row))
    return sorted(kept)


def stage(fixture: Path, repo: Path, sources: tuple[str, ...]) -> Path:
    """Copy the sources, the config, and the recorded tables into `repo`."""
    for name in sources:
        shutil.copy(fixture / name, repo / name)
    tables = repo / ".wavefront" / "codeql"
    for tier in TIERS:
        shutil.copytree(fixture / tier, tables / tier)
    return tables


def wavefront(repo: Path, *args: str) -> str:
    """Run the CLI on `repo` as a subprocess and return its stdout."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(data_root())] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    done = subprocess.run(
        [sys.executable, "-m", "wavefront.cli", str(repo),
         "--config", "wavefront-config.json", *args],
        capture_output=True, text=True, env=env)
    if done.returncode:
        raise AssertionError(f"wavefront {' '.join(args)} failed:\n{done.stderr}")
    return done.stdout


def extract(fixture: Path, repo: Path, sources: tuple[str, ...]) -> Path:
    """Build a CodeQL database for the fixture sources and extract the tables.

    `--build-mode=none` extracts the sources without tracing a compiler, which
    CodeQL cannot do on Apple Silicon without Rosetta. The fixtures include
    no headers beyond their own, so the tables match a traced build.
    """
    for name in sources:
        shutil.copy(fixture / name, repo / name)
    db = repo / ".wavefront" / "codeql" / "db"
    db.parent.mkdir(parents=True)
    subprocess.run(
        ["codeql", "database", "create", str(db), "--language=cpp",
         "--build-mode=none", "--source-root", str(repo)],
        check=True, capture_output=True)
    wavefront(repo, "extract-ql")
    return db.parent


def load_module(path: Path) -> ModuleType:
    """Import a stand-alone script, such as an example's checker."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
