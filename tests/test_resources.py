from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from crustify_oracle.cli import build_parser
from crustify_oracle.resources import data_root, schema_dir


class ResourceOwnershipTests(unittest.TestCase):
    def test_source_install_owns_schemas_and_codeql_pack(self) -> None:
        self.assertTrue((schema_dir() / "types.md").is_file())
        self.assertTrue((schema_dir() / "syms.md").is_file())
        self.assertTrue((data_root() / "qlpack.yml").is_file())
        self.assertTrue(any((data_root() / "entities").glob("*.ql")))
        self.assertTrue(any((data_root() / "edges").glob("*.ql")))

    def test_removed_manifest_flag_is_rejected(self) -> None:
        parser = build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([
                "/repo", ".", "query", "types", "--name", "foo_st",
                "--manifest",
            ])


if __name__ == "__main__":
    unittest.main()
