"""The fixtures' CodeQL side, shared by the tests and `regenerate_tables.py`.

Running CodeQL is slow: each query costs seconds even on a fixture of a few
lines, so the default suite runs none. Tests that compose, query or schedule
a fixture read its committed tables, `fixtures/<name>/codeql/{t1,t2}/`, which
`regenerate_tables.py` extracts. The tests that build a fixture's database
and run the queries are opt-in, under `WAVEFRONT_CODEQL_TESTS=1`: they check
the queries against the golden tables and the committed tables against a
fresh extraction, and must pass before a change to a query, or to a fixture's
C, lands.
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

#: The variable that opts in to the CodeQL tests.
OPT_IN = "WAVEFRONT_CODEQL_TESTS"

#: The fixtures whose full T1/T2 tables are committed, with their builds: one
#: command per translation unit, since CodeQL splits a `--command` on
#: whitespace and honours no shell quoting.
BUILDS: dict[str, tuple[str, ...]] = {
    "enum_constant_uses": ("gcc -std=c11 -I. -c buf.c -o /dev/null",),
    "header_macro_bodies": ("gcc -std=c11 -I. -c mem.c -o /dev/null",
                            "gcc -std=c11 -I. -c use.c -o /dev/null"),
}


def codeql_enabled() -> bool:
    """The CodeQL tests are opted in, and CodeQL and gcc are on PATH."""
    return (os.environ.get(OPT_IN) == "1"
            and shutil.which("codeql") is not None
            and shutil.which("gcc") is not None)


SKIP_REASON = f"CodeQL tests are opt-in: set {OPT_IN}=1 (needs codeql and gcc)"


def rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def key(r: dict) -> tuple:
    return tuple(r[k] for k in sorted(r))


def relative(table: list[dict]) -> list[dict]:
    """The rows that name no absolute path: the fixture's own, not the host's
    system headers, which differ between hosts."""
    return [r for r in table if not any(str(v).startswith("/") for v in r.values())]


def tables(name: str) -> Path:
    """The fixture's committed `codeql/` directory, holding `t1/` and `t2/`."""
    return FIXTURES / name / "codeql"


def state_dir(name: str, td: Path) -> Path:
    """A state dir under ``td`` holding a copy of the fixture's committed
    tables: a command writes its caches below its state dir, never into the
    fixture."""
    state = td / "state"
    shutil.copytree(tables(name), state / "codeql")
    return state


def extract(name: str, td: Path) -> Path:
    """Build the fixture's database under ``td`` and extract every T1/T2
    table from it; return the `codeql/` directory holding them."""
    from compose.extract_csvs import extract_t1_t2
    from wavefront.resources import data_root

    db = td / "db"
    subprocess.run(
        ["codeql", "database", "create", str(db), "--language=cpp",
         "--source-root", str(FIXTURES / name),
         *(f"--command={c}" for c in BUILDS[name])],
        check=True, capture_output=True)
    out = td / "codeql"
    _ok, failed = extract_t1_t2(db, data_root(), out)
    if failed:
        raise RuntimeError(f"{name}: {failed} queries failed")
    return out


def differences(name: str, extracted: Path) -> list[str]:
    """The tables of a fresh extraction whose fixture rows differ from the
    committed ones, or that only one side has."""
    out = []
    committed = tables(name)
    for tier in ("t1", "t2"):
        fresh = {p.name for p in (extracted / tier).glob("*.csv")}
        kept = {p.name for p in (committed / tier).glob("*.csv")}
        for table in sorted(fresh | kept):
            if table not in fresh or table not in kept:
                out.append(f"{tier}/{table}: only {'extracted' if table in fresh else 'committed'}")
                continue
            got = sorted(map(key, relative(rows(extracted / tier / table))))
            want = sorted(map(key, relative(rows(committed / tier / table))))
            if got != want:
                out.append(f"{tier}/{table}")
    return out
