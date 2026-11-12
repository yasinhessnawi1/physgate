"""No command hands a shell a startup file through its environment.

``BASH_ENV`` names a file bash runs as it starts, however it is started; it has no other use,
so a command that sets it at all is refused. ``ENV`` names the file sh runs, and is also an
everyday name in other programs' environments: it is refused where the command it is set for
is itself a shell, and let through anywhere else. An ``export ENV=...`` is let through too:
whether a later command is a shell that would read it cannot be told from the words.

Inside the sandbox such a shell is bounded like any command; the refusal is one more layer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_helpers import event, write_config

from physgate.hooks import shell_paths
from physgate.hooks.config import HookInput

REFUSED = [
    ("BASH_ENV=/tmp/rc bash -c true", "BASH_ENV"),
    ("BASH_ENV=/tmp/rc make all", "BASH_ENV"),
    ("env BASH_ENV=/tmp/rc bash script.sh", "BASH_ENV"),
    ("env -i BASH_ENV=/tmp/rc PATH=/bin /bin/bash -c true", "BASH_ENV"),
    ("export BASH_ENV=/tmp/rc", "BASH_ENV"),
    ("export BASH_ENV", "BASH_ENV"),
    ("declare -x BASH_ENV=/tmp/rc", "BASH_ENV"),
    ("typeset -x BASH_ENV=/tmp/rc", "BASH_ENV"),
    ("BASH_ENV=/tmp/rc", "BASH_ENV"),
    ("true && BASH_ENV=/tmp/rc ./build.sh", "BASH_ENV"),
    ("ENV=/tmp/rc sh -c true", "ENV"),
    ("ENV=/tmp/rc /bin/sh script.sh", "ENV"),
    ("ENV=/tmp/rc dash", "ENV"),
    ("ENV=/tmp/rc bash --posix -i", "ENV"),
    ("env ENV=/tmp/rc sh -c true", "ENV"),
    ("env -i ENV=/tmp/rc /bin/sh", "ENV"),
    ("command env ENV=/tmp/rc dash -c true", "ENV"),
    ("ENV=/tmp/rc exec sh", "ENV"),
    ("A=1 ENV=/tmp/rc B=2 zsh -c true", "ENV"),
]

ALLOWED = [
    "ENV=production make deploy",
    "ENV=test python3 manage.py check",
    "env ENV=staging npm run build",
    "export ENV=production",
    "ENV=production",
    "echo ENV=x sh",
    "printf '%s\\n' 'BASH_ENV=x bash'",
    "grep -r BASH_ENV .",
    "echo $ENV",
    "MY_BASH_ENV=1 bash -c true",
    "ENVIRONMENT=x sh -c true",
    "sh -c true",
    "bash script.sh",
]


def _decision(tmp_path: Path, command: str, profile: str = "role") -> tuple[bool, str]:
    overrides = {"profile": profile, "role": "electrical" if profile == "role" else None}
    _, _, config = write_config(tmp_path, **overrides)
    hook_input = HookInput.model_validate(
        event(cwd=config.worktree, tool_name="Bash", tool_input={"command": command})
    )
    decision = shell_paths.pre_tool_use(hook_input, config)
    return decision.allow, decision.reason or ""


@pytest.mark.parametrize(("command", "name"), REFUSED)
@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_command_that_hands_a_shell_a_startup_file_is_refused(
    tmp_path: Path, command: str, name: str, profile: str
) -> None:
    allowed, reason = _decision(tmp_path, command, profile)
    assert not allowed, command
    assert f"sets {name}, which names a file a shell runs as it starts" in reason


@pytest.mark.parametrize("command", ALLOWED)
def test_an_ordinary_use_of_the_name_is_let_through(tmp_path: Path, command: str) -> None:
    allowed, reason = _decision(tmp_path, command)
    assert allowed, (command, reason)
