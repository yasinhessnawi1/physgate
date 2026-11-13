"""How each pin treats a PreToolUse hook command that ends other than by refusing.

The hook layer refuses by exiting 2, and every failure inside a hook is turned into that refusal,
because the binary treats any other end as no refusal at all: the tool runs. That is a property of
the binary, so it is measured on each pin, by putting, for one session, a command that ends in
each other way where the generated PreToolUse command stands (exit 1, exit 3, killed, an
interpreter that is not there, past its timeout), and seeing whether the shell command it guards
ran. Exit 2 is the control: it refuses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import pinned_version, run_session

from physgate.hooks.settings import Installed

pytestmark = pytest.mark.integration

#: Each way a hook command can end, as a command line in place of the generated one.
ENDS = {
    "exit 2": "sh -c 'echo refused >&2; exit 2'",
    "exit 1": "sh -c 'exit 1'",
    "exit 3": "sh -c 'exit 3'",
    "killed": "sh -c 'kill -9 $$'",
    "interpreter missing": "/nonexistent/interpreter -c pass",
    "past its timeout": "sh -c 'sleep 5'",
}

#: Measured per pin: whether the guarded command ran. 2.1.301's values are the contract the hook
#: layer was built on (only exit 2 refuses); 2.1.322's are measured on CI.
_ONLY_2_REFUSES = {end: end != "exit 2" for end in ENDS}
RAN: dict[str, dict[str, bool]] = {"2.1.301": _ONLY_2_REFUSES, "2.1.322": _ONLY_2_REFUSES}


def _replacing(command: str) -> Any:  # noqa: ANN401 - the harness's settings hook
    def replace(installed: Installed, given: dict[str, Any]) -> None:
        settings = json.loads(json.dumps(given))
        for group in settings["hooks"]["PreToolUse"]:
            for hook in group["hooks"]:
                hook["command"] = command
                hook["timeout"] = 1
        installed.settings_path.write_text(json.dumps(settings))

    return replace


def test_only_a_hook_that_exits_2_stops_the_tool_on_each_pin(tmp_path: Path) -> None:
    ran: dict[str, bool] = {}
    for i, (end, command) in enumerate(ENDS.items()):
        run = run_session(
            tmp_path / str(i),
            Script(main=[tool("Bash", command="echo ran > ran.txt", description="x"), text("end")]),
            check_installed=_replacing(command),
        )
        ran[end] = (run.worktree / "ran.txt").exists()
    assert ran == RAN[pinned_version()], json.dumps(ran)
