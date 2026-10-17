"""The raw agent's session (profile ``baseline``) cannot read the held-out tier, for real.

The same method as the bypass suite: every attempt is a real Claude Code tool call,
driven by the scripted endpoint so no model can decline it, and judged mechanically.
**Shown** is the held-out content appearing in anything the session was told; **caught**
is the hook layer's own log holding a refusal for the attempt. The raw agent is the arm
the harness is measured against, so a read of the held-out tier by it would make the
measurement meaningless exactly as one by a role session would.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import run_session

pytestmark = pytest.mark.integration

ANSWER = "the held-out answer of scenario 01"


def bash(command: str) -> dict[str, Any]:
    return tool("Bash", command=command, description="x")


#: Every way a session's own tools offer to read a file: the file tools, a plain
#: command, a redirect, a here-document feeding an interpreter, and an in-language read.
ATTEMPTS: list[tuple[str, dict[str, Any]]] = [
    ("read-tool", tool("Read", file_path="@H/scenario_01.json")),
    ("cat", bash("cat @H/scenario_01.json")),
    ("redirect", bash("while read -r l; do echo $l; done < @H/scenario_01.json")),
    (
        "heredoc",
        bash("python3 - <<'PY'\nprint(open('@H/scenario_01.json').read())\nPY"),
    ),
    ("in-language", bash("python3 -c \"print(open('@H/scenario_01.json').read())\"")),
    ("copy-out", bash("cp @H/scenario_01.json leaked.json && cat leaked.json")),
]


def _place(step: dict[str, Any], held: Path) -> dict[str, Any]:
    placed = dict(step)
    placed["input"] = {
        k: v.replace("@H", str(held)) if isinstance(v, str) else v for k, v in step["input"].items()
    }
    return placed


@pytest.mark.parametrize(("name", "step"), ATTEMPTS, ids=[n for n, _ in ATTEMPTS])
def test_no_way_of_reading_shows_the_raw_agent_the_held_out_tier(
    tmp_path: Path, name: str, step: dict[str, Any]
) -> None:
    held = tmp_path / "outside" / "heldout"
    held.mkdir(parents=True)
    (held / "scenario_01.json").write_text('{"answer": "' + ANSWER + '"}\n')
    run = run_session(
        tmp_path,
        Script(main=[_place(step, held), text("end")]),
        profile="baseline",
        role=None,
        own_branch=None,
        store_root=None,
        held_out=(str(held),),
    )
    caught = [e for e in run.hook_log if e.get("decision") == "refuse"]
    assert ANSWER not in run.told_after(1), f"{name}: the raw agent was shown held-out content"
    assert caught, f"{name}: no refusal from the hook layer is on record"
    assert not (run.worktree / "leaked.json").exists()
