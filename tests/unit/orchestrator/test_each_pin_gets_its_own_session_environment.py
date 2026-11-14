"""Each pinned Claude Code version gets its own session environment, and 2.1.301's never moves.

Runs on 2.1.301 are measured and frozen experiments read them, so its environment is pinned here
byte for byte as it was before a second pin existed. On 2.1.322, by the owner's choice, the traffic
the advisor needs is allowed: every variable the provider documents as stopping feature-flag
fetching is left unset, the older name among them. Everything else a pinned binary must not do
stays off: updating itself, sending error and bug reports, moving work into the background where
no hook sees it, handing a flagged request to another model, and reloading a mod a session wrote.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.orchestrator.invocation import isolated_env, session_env_settings

#: What every session on 2.1.301 received before the second pin, byte for byte.
ENV_2_1_301 = {
    "HOME": "/h",
    "PATH": "/opt/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    "TERM": "dumb",
    "CLAUDE_CONFIG_DIR": "/c",
    "CLAUDE_CODE_MAX_RETRIES": "0",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_GROWTHBOOK": "1",
    # The one variable the tool layer adds on every pin: the bound on one tool server's
    # answer, at the binary's own default, so that a remote flag cannot move it.
    "MAX_MCP_OUTPUT_TOKENS": "25000",
}

#: The variables the provider documents as turning feature-flag fetching off (read 11.11.2026).
FLAG_STOPPING = (
    "CLAUDE_CODE_DISABLE_FEATURE_FLAGS",
    "DISABLE_TELEMETRY",
    "DO_NOT_TRACK",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "DISABLE_GROWTHBOOK",
)

#: What stays off on the new pin, and the value that keeps it off.
KEPT_OFF_2_1_322 = {
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_BUG_COMMAND": "1",
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
    "CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK": "1",
    "CLAUDE_CODE_PLUGIN_DIR_WATCH": "0",
}


def _env(version: str) -> dict[str, str]:
    return isolated_env(
        home=Path("/h"),
        config_dir=Path("/c"),
        binary="/opt/bin/claude",
        claude_version=version,
        max_retries=0,
        max_output_tokens=64000,
        base_url=None,
        api_key=None,
    )


def test_a_2_1_301_session_receives_exactly_what_it_received_before_a_second_pin() -> None:
    env = _env("2.1.301")
    assert env == ENV_2_1_301
    assert list(env) == list(ENV_2_1_301)  # the order the variables are written in, too


@pytest.mark.parametrize("name", FLAG_STOPPING)
def test_on_the_new_pin_no_variable_stops_the_flag_fetch(name: str) -> None:
    assert name not in _env("2.1.322")


@pytest.mark.parametrize(("name", "value"), sorted(KEPT_OFF_2_1_322.items()))
def test_on_the_new_pin_what_a_pinned_binary_must_not_do_stays_off(name: str, value: str) -> None:
    assert _env("2.1.322").get(name) == value


def test_the_new_pin_s_switches_never_reach_an_older_pin() -> None:
    for version in ("2.1.272", "2.1.283", "2.1.301"):
        env = _env(version)
        for name in KEPT_OFF_2_1_322.keys() - {"DISABLE_AUTOUPDATER", "DISABLE_ERROR_REPORTING"}:
            assert name not in env, (version, name)


def test_a_run_records_which_switches_its_sessions_carried_per_pin() -> None:
    old = session_env_settings("2.1.301")
    new = session_env_settings("2.1.322")
    assert old.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "1"
    assert old.get("DISABLE_GROWTHBOOK") == "1"
    assert all(name not in new for name in FLAG_STOPPING)
    assert {k: new.get(k) for k in KEPT_OFF_2_1_322} == KEPT_OFF_2_1_322
    # Only switches: nothing machine- or session-specific is in the record.
    for settings in (old, new):
        assert not settings.keys() & {"HOME", "PATH", "CLAUDE_CONFIG_DIR", "ANTHROPIC_API_KEY"}
