"""The rule that no screen shows a terminal command knows every subcommand ``physgate`` has.

The operator UI's rule test and the desktop shell's read what a command looks like from one
file. A subcommand missing from it would be a command a screen could show unnoticed, so the
file's list is held equal to the command's own.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from physgate.cli import main

SHAPES = Path(__file__).resolve().parents[3] / "ui" / "src" / "rules" / "terminal-commands.json"


def _subcommands(capsys: pytest.CaptureFixture[str]) -> list[str]:
    with pytest.raises(SystemExit):
        main(["--help"])
    usage = capsys.readouterr().out
    found = re.search(r"\{([a-z,-]+)\}", usage)
    assert found is not None, usage
    return sorted(found.group(1).split(","))


def test_the_rule_lists_exactly_the_command_s_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    listed = json.loads(SHAPES.read_text(encoding="utf-8"))["subcommands"]
    actual = _subcommands(capsys)
    assert len(actual) > 10, "the command's help was read"
    assert sorted(listed) == actual
