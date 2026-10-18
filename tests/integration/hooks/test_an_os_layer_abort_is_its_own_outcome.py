"""Through the real binary: a command that ends as bubblewrap's abort is recorded as that.

A real abort needs two sandboxed sessions racing over one placeholder, which no test
can schedule. What every reader keys on is the shell's result: an error carrying
bubblewrap's own line. So the command here ends exactly so, ``bwrap: ...`` on its
error stream and exit status 1, and the session runs without the OS layer, so that
nothing but the command's own words is in play. The hook layer logs it as an abort and
never as a refusal, and the dispatcher's reading of the stream finds it by its call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import run_session

from physgate.oslayer.abort import OS_LAYER_ABORTED, aborted_tool_uses

pytestmark = pytest.mark.integration

#: What bubblewrap printed when a sibling session removed its placeholder (Oracle VM).
ABORT = "bwrap: Can't find source path /tmp/pytest-of-u/pytest-1/.mcp.json: No such file"
#: The decisions every count of refusals reads in the hook log.
REFUSALS = {"refuse", "put back", "halt", "node mismatch"}


def test_an_aborted_command_is_logged_as_an_abort_and_never_as_a_refusal(
    tmp_path: Path,
) -> None:
    command = f"echo {json.dumps(ABORT)} >&2; exit 1"
    run = run_session(
        tmp_path, Script(main=[tool("Bash", command=command, description="abort"), text("end")])
    )
    told = run.told_after(1)
    assert "bwrap:" in told and "Exit code 1" in told, told
    aborts = [e for e in run.hook_log if e.get("decision") == OS_LAYER_ABORTED]
    assert [(e["hook"], e["event"], e["told"]) for e in aborts] == [
        ("os_abort", "PostToolUseFailure", ABORT)
    ]
    assert not [e for e in run.hook_log if e.get("decision") in REFUSALS]
    stream = "\n".join(json.dumps(event) for event in run.stream)
    (aborted,) = aborted_tool_uses(stream)
    assert aborted.startswith("toolu_")


def test_a_command_that_only_mentions_bubblewrap_is_no_abort(tmp_path: Path) -> None:
    run = run_session(
        tmp_path,
        Script(
            main=[tool("Bash", command="echo 'see bwrap: its manual'", description="x"), text("e")]
        ),
    )
    assert not [e for e in run.hook_log if e.get("decision") == OS_LAYER_ABORTED]
    assert aborted_tool_uses("\n".join(json.dumps(event) for event in run.stream)) == ()
