"""Re-extract the committed T1/T2 tables of the test fixtures.

    PYTHONPATH=src python tests/regenerate_tables.py [FIXTURE ...]

Builds each fixture's CodeQL database, extracts every query, and replaces
`tests/fixtures/<name>/codeql/{t1,t2}/` with the result; without arguments,
every fixture `codeql_fixtures.BUILDS` names. Run it after changing a query
or a fixture's C, and review the CSV diff as a golden's: the default suite
reads these tables and runs no CodeQL.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codeql_fixtures as cf  # noqa: E402


def regenerate(name: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        extracted = cf.extract(name, Path(td))
        dest = cf.tables(name)
        for tier in ("t1", "t2"):
            shutil.rmtree(dest / tier, ignore_errors=True)
            (dest / tier).mkdir(parents=True)
            for p in sorted((extracted / tier).glob("*.csv")):
                shutil.copy2(p, dest / tier / p.name)
    print(f"{name}: {dest}")


def main(argv: list[str]) -> int:
    if shutil.which("codeql") is None or shutil.which("gcc") is None:
        print("error: codeql and gcc must be on PATH", file=sys.stderr)
        return 1
    names = argv or sorted(cf.BUILDS)
    unknown = [n for n in names if n not in cf.BUILDS]
    if unknown:
        print(f"error: no committed tables for {', '.join(unknown)}; "
              f"known: {', '.join(sorted(cf.BUILDS))}", file=sys.stderr)
        return 1
    for name in names:
        regenerate(name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
