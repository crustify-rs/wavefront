"""extraction — the one composer stage with side effects.

Runs the T1 (entities) + T2 (edges) `.ql` batches against the CodeQL database
at `crustify/oracle/codeql/db/` and writes one CSV per query under
`crustify/oracle/codeql/{t1,t2}/`. Every other artifact derives from those tables on
demand: scope and the dag through :mod:`crustify_oracle.cache`, the type and
symbol records through :mod:`crustify_oracle.manifests`.

The database itself is not produced here — configuring the project, building it
under `codeql database create --language=cpp --command=...`, and depositing the
result is done by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

from crustify_oracle.layout import Layout
from crustify_oracle.resources import data_root


def extract_ql(target: Path) -> None:
    """Run every `.ql` under `entities/` and `edges/`
    against the CodeQL database, writing one CSV per query."""
    import shutil

    from compose.extract_csvs import extract_t1_t2

    if shutil.which("codeql") is None:
        print(
            "error: the `codeql` CLI is not on PATH. Install it and run "
            "`codeql pack install` in the oracle checkout so codeql/cpp-all "
            "resolves.",
            file=sys.stderr,
        )
        sys.exit(1)

    layout = Layout.discover(target)
    db = layout.codeql_db
    if not db.is_dir():
        print(
            f"error: CodeQL database not found at {db}.\n"
            f"       Build the project under CodeQL trace first, e.g.\n"
            f"         codeql database create {db} --language=cpp "
            f"--command=\"<build command>\"",
            file=sys.stderr,
        )
        sys.exit(1)

    succeeded, failed = extract_t1_t2(db, data_root(), layout.codeql)
    print(
        f"[wavefront extract-ql] {succeeded} queries ok, "
        f"{failed} failed"
    )
    if failed:
        print(
            f"error: {failed} query extraction(s) failed; see output above. "
            f"Analyze stages will see empty / missing CSVs for those "
            f"queries.",
            file=sys.stderr,
        )
        sys.exit(1)
