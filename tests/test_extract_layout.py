from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from compose.extract_csvs import extract_all, extract_t1_t2


class ExtractLayoutTests(unittest.TestCase):
    def test_standalone_query_directories_are_used(self) -> None:
        root = Path("/oracle")
        out = Path("/repo/crustify/oracle/codeql")
        with patch("compose.extract_csvs.extract_all",
                   side_effect=[(6, 0, []), (16, 0, [])]) as run, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(
                extract_t1_t2(Path("/db"), root, out), (22, 0))
        self.assertEqual(run.call_args_list[0].args,
                         (Path("/db"), root / "entities", out / "t1"))
        self.assertEqual(run.call_args_list[1].args,
                         (Path("/db"), root / "edges", out / "t2"))

    def test_empty_query_directory_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    extract_all(Path("/db"), root / "queries", root / "out"),
                    (0, 1, [f"no .ql files in {root / 'queries'}"]),
                )


if __name__ == "__main__":
    unittest.main()
