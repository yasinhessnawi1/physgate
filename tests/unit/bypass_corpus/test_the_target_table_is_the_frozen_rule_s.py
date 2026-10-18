"""The target table in code is the one R-HK-01's instantiation rule froze.

The placement tests check the table, so the table itself is held to the rule's
own text: a target that drifted in code would be placed, and checked, somewhere
the frozen rule never named.
"""

from __future__ import annotations

import re
from pathlib import Path

from physgate import bypass_corpus as bc

RULE = Path(__file__).resolve().parents[3] / "experiments" / "R-HK-01" / "instantiation-rule.md"
ROW = re.compile(r"^\| `([a-z]+)` \| `(@[WO]/[^`]+)` \|$")


def test_the_table_holds_every_key_and_the_rule_s_path_for_each() -> None:
    rows = dict(m.groups() for line in RULE.read_text().splitlines() if (m := ROW.match(line)))
    assert rows, "no target row was read from the rule"
    assert set(rows) == bc.TARGET_KEYS
    assert rows == bc.TARGET_PATHS
