"""The operator interface names every physics check the gate records, and no other.

The interface's guard refuses a gate record whose check name its list does not hold, and its
words table gives each listed name a human name and an explanation. Both are held here to the
gate's own list of check names, so a check the gate gains turns this red until the interface can
say it in words.
"""

from __future__ import annotations

import re
import typing
from pathlib import Path

from physgate.orchestrator.protocols import CheckName

ROOT = Path(__file__).resolve().parents[3]


def test_the_interface_s_check_names_are_the_gate_s() -> None:
    text = (ROOT / "ui" / "src" / "api" / "run.ts").read_text()
    listed = re.search(r"export const CHECK_NAMES = \[(.*?)\] as const;", text, re.DOTALL)
    assert listed is not None
    assert re.findall(r'"([a-z_]+)"', listed.group(1)) == list(typing.get_args(CheckName))


def test_the_interface_says_every_check_in_words() -> None:
    words = (ROOT / "ui" / "src" / "words" / "checks.ts").read_text()
    for name in typing.get_args(CheckName):
        assert re.search(rf"\n  {name}: {{\n    name: \"[^\"]+\",", words), name
