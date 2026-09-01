from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import mock_open, patch

from crustify_oracle.cli import _pin_hash_seed, main


class CliDeterminismTests(unittest.TestCase):
    def test_cli_reexecs_with_stable_hash_seed(self) -> None:
        with patch.dict(os.environ, {"PYTHONHASHSEED": "random"}), \
                patch.object(sys, "argv", ["wavefront", "repo", ".",
                                           "query", "files"]), \
                patch("os.execve") as execute:
            _pin_hash_seed()
        executable, argv, environment = execute.call_args.args
        self.assertEqual(executable, sys.executable)
        self.assertEqual(
            argv,
            [sys.executable, "-m", "crustify_oracle.cli", "repo", ".",
             "query", "files"],
        )
        self.assertEqual(environment["PYTHONHASHSEED"], "0")

    def test_cli_does_not_reexec_when_seed_is_stable(self) -> None:
        with patch.dict(os.environ, {"PYTHONHASHSEED": "0"}), \
                patch("os.execve") as execute:
            _pin_hash_seed()
        execute.assert_not_called()

    def test_cli_silences_a_closed_stdout_pipe(self) -> None:
        replacement = mock_open()
        with patch("crustify_oracle.cli._main", side_effect=BrokenPipeError), \
                patch("builtins.open", replacement), \
                patch.object(sys, "stdout"):
            main()
        replacement.assert_called_once_with(os.devnull, "w")


if __name__ == "__main__":
    unittest.main()
