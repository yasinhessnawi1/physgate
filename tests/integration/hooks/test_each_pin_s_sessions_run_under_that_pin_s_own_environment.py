"""Each pin's sessions run under that pin's own environment, and no session moves the binary.

On 2.1.322, by the owner's choice, the four switches that stop the feature-flag fetch are left
unset, and the auto-updater, error reports, the bug command, background tasks, the model fallback
and the plugin-directory watch are switched off. On 2.1.301 nothing changes. The rows that prove
the hooks on each pin are worth what the environment they ran under is worth, so this harness
spawns each pin's sessions with that pin's switches, and a session's own shell shows exactly
those. The binary's bytes are the same after a session as before: with the umbrella traffic
switch gone, only the auto-updater switch stops a pinned binary replacing itself.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import (
    RIG_SWITCHES_2_1_301,
    claude_binary,
    pinned_version,
    run_session,
    session_switches,
)

from physgate.orchestrator.invocation import TRAFFIC_ALLOWED_VERSIONS, session_env_settings

pytestmark = pytest.mark.integration

#: The switches whose presence stops the feature-flag fetch: never set on a pin with traffic.
FLAG_STOPPING = (
    "CLAUDE_CODE_DISABLE_FEATURE_FLAGS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "DISABLE_GROWTHBOOK",
    "DISABLE_TELEMETRY",
    "DO_NOT_TRACK",
)


def test_on_the_new_pin_the_harness_spawns_the_harness_s_own_switches() -> None:
    assert session_switches("2.1.322") == session_env_settings("2.1.322")


def test_on_2_1_301_the_harness_spawns_what_every_earlier_result_was_measured_under() -> None:
    assert session_switches("2.1.301") == RIG_SWITCHES_2_1_301


def _environment(tmp_path: Path) -> dict[str, str]:
    run = run_session(
        tmp_path,
        Script(main=[tool("Bash", command="env | sort", description="x"), text("end")]),
    )
    assert run.exit_code == 0, run.stderr
    told = run.told_after(1)
    names = dict(line.split("=", 1) for line in told.split("\n") if "=" in line)
    assert "PATH" in names, f"the shell's environment was not shown: {told[:300]}"
    return names


def test_a_session_s_own_shell_sees_exactly_its_pin_s_switches(tmp_path: Path) -> None:
    version = pinned_version()
    seen = _environment(tmp_path)
    for name, value in session_switches(version).items():
        assert seen.get(name) == value, (version, name, seen.get(name))
    if version in TRAFFIC_ALLOWED_VERSIONS:
        assert [n for n in FLAG_STOPPING if n in seen] == []


def test_the_binary_s_bytes_are_the_same_after_a_session_as_before(tmp_path: Path) -> None:
    binary = Path(claude_binary()).resolve()
    before = hashlib.sha256(binary.read_bytes()).hexdigest()
    run = run_session(tmp_path, Script(main=[text("end")]))
    assert run.exit_code == 0, run.stderr
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == before
