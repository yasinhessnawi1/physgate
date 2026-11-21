"""A settings file in the worktree supplies nothing to a session, on each pin.

A role session is started with no setting source but the generated file. Later binaries fixed a
leak in which a settings file left out that way could still supply some of its settings, so what
a worktree's own settings files supply is measured on each pin rather than taken from the flag's
description: a hook of their own, a rule denying the shell, and an environment variable, in both
the shared and the local file, present before the session starts. A session then runs one shell
command; it must run, under the generated hooks only, without the variable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import pinned_version, run_session

pytestmark = pytest.mark.integration

_NOTHING = {"the command ran": True, "variable": "unset", "the file's own hook ran": False}
#: Measured per pin: what the worktree's settings files supplied.
SUPPLIED: dict[str, dict[str, Any]] = {"2.1.301": _NOTHING, "2.1.322": _NOTHING}


def _plant(worktree: Path) -> None:
    ran = worktree.parent / "the-file-s-own-hook-ran"
    own = {"hooks": [{"type": "command", "command": f"sh -c 'echo ran > {ran}'"}]}
    settings = {
        "hooks": {
            "PreToolUse": [{"matcher": "*", **own}],
            "SessionStart": [own],
        },
        "permissions": {"deny": ["Bash"]},
        "env": {"PLANTED_VARIABLE": "supplied"},
    }
    directory = worktree / ".claude"
    directory.mkdir()
    for name in ("settings.json", "settings.local.json"):
        (directory / name).write_text(json.dumps(settings))


def test_what_a_worktree_s_settings_files_supply_on_each_pin(tmp_path: Path) -> None:
    command = 'echo "${PLANTED_VARIABLE:-unset}" > out.txt'
    run = run_session(
        tmp_path,
        Script(main=[tool("Bash", command=command, description="x"), text("end")]),
        prepare=_plant,
    )
    assert (run.worktree / ".claude" / "settings.local.json").exists()  # there all along
    out = run.worktree / "out.txt"
    measured = {
        "the command ran": out.exists(),
        "variable": out.read_text().strip() if out.exists() else None,
        "the file's own hook ran": (tmp_path / "the-file-s-own-hook-ran").exists(),
    }
    shown = {"told": run.told_after(1)[:300], "started": dict(run.hook_commands_started())}
    assert measured == SUPPLIED[pinned_version()], json.dumps([measured, shown])
