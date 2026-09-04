from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from compose.extract_csvs import extract_all, extract_t1_t2
from wavefront.layout import Layout, set_config_path, set_repo_root


class ExtractLayoutTests(unittest.TestCase):
    def test_standalone_query_directories_are_used(self) -> None:
        root = Path("/pack")
        out = Path("/repo/crustify/wavefront/codeql")
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

    def test_explicit_configs_use_content_addressed_dag_caches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            first = repo / "campaigns" / "one" / "wavefront-config.json"
            second = repo / "campaigns" / "two" / "wavefront-config.json"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            content = ('{"state_dir":"analysis","impl_files":["src/a.c"],'
                       '"api_headers":["include/a.h"]}\n')
            first.write_text(content)
            second.write_text(content)
            set_repo_root(repo)
            try:
                set_config_path(first)
                first_layout = Layout.discover(repo)
                first_cache = first_layout.deps_dag(api_headers_only=True)
                provenance = first_layout.config_provenance()

                set_config_path(second)
                second_cache = Layout.discover(repo).deps_dag(
                    api_headers_only=True)
            finally:
                set_config_path(None)
                set_repo_root(repo)

            self.assertEqual(first_cache, second_cache)
            self.assertEqual(first_cache.parent.parent.parent,
                             repo / "analysis" / ".cache")
            self.assertEqual(provenance["path"],
                             "campaigns/one/wavefront-config.json")
            self.assertEqual(len(provenance["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
