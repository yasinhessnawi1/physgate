"""Through the real binary: where the volume ignores case, a variant of the path is checked.

``.PHYSGATE/proposals/electrical.driver.json`` is the proposal itself where the
volume ignores case. A bare number written there by the Write tool is refused,
and so is a command that writes there; nothing is left in the proposals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_messages_api import tool
from hook_session import volume_is_case_insensitive
from test_a_node_proposal_is_checked_through_the_real_tool_path import (
    _graph_refusals,
    _node,
    _run,
)

from physgate.hooks import graph
from physgate.state.protocol import REJECT_MISSING_UNIT

pytestmark = pytest.mark.integration

VARIANT = ".PHYSGATE/proposals/electrical.driver.json"


@pytest.fixture(autouse=True)
def _case_insensitive(tmp_path: Path) -> None:
    if not volume_is_case_insensitive(tmp_path / "probe"):
        pytest.skip("this volume tells a case variant from the path itself")


def _nothing_left(tmp_path: Path) -> None:
    proposals = tmp_path / "worktree" / graph.PROPOSALS_DIR
    assert not proposals.exists() or list(proposals.iterdir()) == []


def test_a_bare_number_written_under_a_case_variant_is_refused(tmp_path: Path) -> None:
    bare = {**_node("electrical.driver", "electrical"), "quantities": {"stall_current": 2.4}}
    run, _ = _run(tmp_path, tool("Write", file_path=f"@W/{VARIANT}", content=json.dumps(bare)))
    (reason,) = _graph_refusals(run)
    assert REJECT_MISSING_UNIT in reason
    _nothing_left(tmp_path)


def test_a_command_writing_under_a_case_variant_is_refused(tmp_path: Path) -> None:
    body = json.dumps(_node("electrical.driver", "electrical"))
    command = f"mkdir -p .PHYSGATE/proposals && echo '{body}' > {VARIANT}"
    run, _ = _run(tmp_path, tool("Bash", command=command, description="x"))
    assert _graph_refusals(run) == [graph.SHELL_WRITE]
    _nothing_left(tmp_path)
