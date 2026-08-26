from __future__ import annotations

import argparse
import unittest
from pathlib import Path

from crustify_oracle.cli import build_parser


def _long_options(parser: argparse.ArgumentParser) -> set[str]:
    options: set[str] = set()
    for action in parser._actions:
        options.update(option for option in action.option_strings
                       if option.startswith("--") and option != "--help")
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                options.update(_long_options(child))
    return options


class ReadmeTests(unittest.TestCase):
    def test_readme_mentions_every_cli_flag(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text()
        for option in sorted(_long_options(build_parser())):
            with self.subTest(option=option):
                self.assertIn(f"`{option}", readme)


if __name__ == "__main__":
    unittest.main()
