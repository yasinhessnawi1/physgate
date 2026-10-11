"""The page's blank note is the queue's: Python's ``str.strip`` whitespace, character for character.

The confirmation shows the decision the page computes from the verb and the note, and the queue
writes the one ``decision_text`` computes; the two agree only if both call the same notes blank.
The page carries the set as a list of code points; this test reads that list from the page's
source and holds it to the interpreter's own set, and to ``decision_text`` itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.queue import decision_text

SOURCE = Path(__file__).resolve().parents[3] / "ui" / "src" / "api" / "queue.ts"


def _page_set() -> set[int]:
    text = SOURCE.read_text()
    body = re.search(r"PYTHON_WHITESPACE[^=]*= new Set\(\[(.*?)\]\)", text, re.S)
    assert body is not None, "the page no longer declares its whitespace set"
    return {int(hex_, 16) for hex_ in re.findall(r"0x([0-9a-fA-F]+)", body.group(1))}


def test_the_page_s_whitespace_is_exactly_what_str_strip_removes() -> None:
    python = {c for c in range(0x110000) if chr(c).isspace()}
    assert len(python) == 29
    assert _page_set() == python
    assert all(chr(c).strip() == "" for c in python)


@pytest.mark.parametrize("char", ["\u001c", "\u001d", "\u001e", "\u001f", "\u0085"])
def test_what_javascript_s_trim_keeps_is_blank_to_the_queue(char: str) -> None:
    assert decision_text("approve", char) == "approve"
    with pytest.raises(QueueError, match="note is required"):
        decision_text("reject", char)


def test_what_javascript_s_trim_strips_but_python_keeps_is_a_note() -> None:
    assert decision_text("approve", "﻿") == "approve: ﻿"
    assert decision_text("reject", "﻿") == "reject: ﻿"
