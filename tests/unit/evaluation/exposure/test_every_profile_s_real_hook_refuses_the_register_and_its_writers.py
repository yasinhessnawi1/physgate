"""Through the real hook, for every kind of session: the register, its roots, its writers refused.

Each kind of session is installed by the real generator with the store's protected places among
its held-out roots, as every run on the role names them, and its generated ``PreToolUse`` command
is run as Claude Code runs it, a fresh interpreter fed the event. A read or a write of either log
or its head, and a shell command that reads one or runs any of the three writers on the role's
withheld root, is refused, and refused as the held-out tier where the kind of session has the
tool at all (a tool it does not have is refused by its tool list first). The orchestrator's own
harness sessions are by design allowed to read the held-out tier, never to write it
(``HELD_OUT_READERS_REFUSED``), so for that kind only the writes and the writers are asked.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, get_args

import pytest
from exposure_fixtures import StandInStore, stand_in_store, with_run_root

from physgate.evaluation.tiers.store import withheld_root
from physgate.hooks.config import Profile
from physgate.hooks.paths import HELD_OUT_READERS_REFUSED
from physgate.hooks.reasons import HELD_OUT_REASON
from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import PROFILE_TOOLS, InstallRequest, install

SESSION = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
OWN_TEMP = "/var/tmp/pgs/0123456789"
LOGS = ("register.jsonl", "register.head", "run-roots.jsonl", "run-roots.head")


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    made = stand_in_store(tmp_path / "s")
    with_run_root(made, tmp_path / "runs")
    return made


def _install(base: Path, profile: str, made: StandInStore) -> tuple[list[str], Path]:
    worktree = base / "worktree"
    for d in ("worktree", "store", "state", "session", "config", "home", "sessions"):
        (base / d).mkdir(parents=True, exist_ok=True)
    fields: dict[str, Any] = {
        "profile": profile,
        "role": "control",
        "worktree": str(worktree),
        "own_branch": "subtask/control-1",
        "store_root": str(base / "store"),
        "state_dir": str(base / "state"),
        "target_dir": str(base / "session"),
        "claude_config_dir": str(base / "config"),
        "user_home": str(base / "home"),
        "token_ceiling": 40960,
        "sessions_root": str(base / "sessions"),
        "temp_dir": OWN_TEMP,
        "held_out": tuple(made.held_out),
    }
    if profile == "baseline":
        fields.update(role=None, own_branch=None, store_root=None)
    if profile == "reviewer":
        fields["read_roots"] = (str(worktree),)
    done = install(InstallRequest(**fields), REGISTRY)
    settings = json.loads(done.settings_path.read_text())
    argv = shlex.split(settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
    # /bin/sh <trampoline> <watchdog> <interpreter> -I -m physgate.hooks <its arguments>
    assert argv[4:7] == ["-I", "-m", "physgate.hooks"], argv
    return [argv[3], "-I", "-m", "physgate.hooks", *argv[7:]], worktree


def _decision(
    command: list[str], worktree: Path, tool: str, tool_input: dict[str, str]
) -> dict[str, Any]:
    event = {
        "session_id": SESSION,
        "cwd": str(worktree),
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
    }
    done = subprocess.run(
        command, input=json.dumps(event), capture_output=True, text=True, check=False
    )
    try:
        said: dict[str, Any] = json.loads(done.stdout)["hookSpecificOutput"]
        return said
    except (ValueError, KeyError):
        return {"permissionDecision": "none", "stdout": done.stdout, "stderr": done.stderr[-400:]}


@pytest.mark.parametrize("profile", get_args(Profile))
def test_each_kind_of_session_s_real_hook_refuses_the_register_its_roots_and_its_writers(
    tmp_path: Path, made: StandInStore, profile: str
) -> None:
    command, worktree = _install(tmp_path / "session", profile, made)
    withheld = withheld_root(made.store, "control")
    reads: list[tuple[str, dict[str, str]]] = []
    writes: list[tuple[str, dict[str, str]]] = []
    for name in LOGS:
        target = str(withheld / name)
        reads += [
            ("Read", {"file_path": target}),
            ("Bash", {"command": f"cat {target}", "description": "read it"}),
        ]
        writes += [
            ("Write", {"file_path": target, "content": "x\n"}),
            ("Bash", {"command": f": > {target}", "description": "empty it"}),
        ]
    for writer in ("scan-exposures", "mark-exposed", "add-run-root"):
        typed = f"physgate tiers {writer} --withheld {withheld}"
        writes.append(("Bash", {"command": typed, "description": "run a writer"}))
    refused_reads = profile in HELD_OUT_READERS_REFUSED
    assert refused_reads or profile == "orchestrator", f"{profile} may read the held-out tier"
    calls = [*reads, *writes] if refused_reads else writes
    allowed = set(PROFILE_TOOLS[profile])  # type: ignore[index]
    for tool, tool_input in calls:
        said = _decision(command, worktree, tool, tool_input)
        assert said.get("permissionDecision") == "deny", (
            f"a {profile} session's hook lets {tool} {tool_input}: {said}"
        )
        if tool in allowed:
            reason = str(said.get("permissionDecisionReason", ""))
            assert HELD_OUT_REASON[:40] in reason, (
                f"a {profile} session's {tool} {tool_input} is refused for another reason: {reason}"
            )
