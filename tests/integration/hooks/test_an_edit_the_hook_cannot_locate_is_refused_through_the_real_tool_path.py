"""Through the real binary: an Edit the hook cannot locate in a proposal is refused.

Claude Code 2.1.301 finds an Edit's old text where an exact match would not: it
takes curly quotes for straight ones, and matches across a lone carriage return.
Each edit here would leave a bare number in the proposal, which the hook refuses
when it sees it. Before, the hook found no old text, checked the file unchanged
and allowed the edit, and the bare number landed. Now the edit is refused and the
proposal is left as it was written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_messages_api import tool
from test_a_node_proposal_is_checked_through_the_real_tool_path import (
    _graph_refusals,
    _node,
    _proposal,
    _run,
)

from physgate.hooks import graph

pytestmark = pytest.mark.integration

NAME = "electrical.driver.json"
PATH = f"@W/{graph.PROPOSALS_DIR}/{NAME}"


def _edited(tmp_path: Path, content: str, old: str, new: str) -> tuple[list[str], bytes]:
    run, _ = _run(
        tmp_path,
        _proposal(NAME, content),
        tool("Read", file_path=PATH),
        tool("Edit", file_path=PATH, old_string=old, new_string=new),
    )
    return _graph_refusals(run), (run.worktree / graph.PROPOSALS_DIR / NAME).read_bytes()


def test_an_edit_with_curly_quotes_is_refused_and_the_proposal_is_unchanged(
    tmp_path: Path,
) -> None:
    content = json.dumps(_node("electrical.driver", "electrical"))
    quantity = (
        '{"value": 2.4, "unit": "A", "source": "datasheet", "written_by": "electrical"}'
    ).replace('"', "“")
    refusals, after = _edited(tmp_path, content, quantity, "2.4")
    assert len(refusals) == 1 and "occurs 0 times" in refusals[0]
    assert after == content.encode()


def test_an_edit_across_a_lone_carriage_return_is_refused_and_the_proposal_is_unchanged(
    tmp_path: Path,
) -> None:
    lines = json.dumps(_node("electrical.driver", "electrical"), indent=1)
    start = lines.index('"stall_current"')
    old = lines[start : lines.index("}", start) + 1].replace("\n", "\r")
    content = lines.replace("\n", "\r")
    refusals, after = _edited(tmp_path, content, old, '"stall_current": 2.4')
    assert len(refusals) == 1 and "occurs 0 times" in refusals[0]
    assert after == content.encode()
