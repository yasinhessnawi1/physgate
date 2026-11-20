"""The quantity names the queue page knows are the physics gate's catalogue, name for name.

A person deciding a part may state a quantity the plan does not name. The page says, beside a
name the catalogue does not know, that its value is recorded as unchecked; it can say so only
from a list of the catalogue's names it carries, since no route serves the catalogue. This row
holds that list equal to the catalogue, so the page never marks a known name or misses one.
"""

from __future__ import annotations

import json
from pathlib import Path

from physgate.gate.catalogue import QUANTITIES
from physgate.state.vocabulary import QUANTITY_NAMES

NAMES = Path(__file__).resolve().parents[3] / "ui" / "src" / "api" / "catalogue-names.json"


def test_the_parts_pages_quantity_names_are_the_gates_catalogue() -> None:
    assert NAMES.is_file(), f"the page carries no list of the catalogue's names at {NAMES}"
    listed = json.loads(NAMES.read_text(encoding="utf-8"))
    assert listed == sorted(QUANTITIES)
    assert listed == list(QUANTITY_NAMES)
