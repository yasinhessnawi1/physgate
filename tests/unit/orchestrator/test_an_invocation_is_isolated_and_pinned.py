"""How the binary is invoked: pinned version, isolated argv, environment from nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.invocation import decomposition_argv, isolated_env, require_pinned


def test_only_the_pinned_version_is_accepted() -> None:
    assert require_pinned("2.1.272 (Claude Code)\n") == "2.1.272"
    for other in ("2.1.271 (Claude Code)", "2.2.0", "", "Claude Code 2.1.272"):
        with pytest.raises(InvocationError):
            require_pinned(other)


def test_the_decomposition_call_offers_no_tool_and_one_turn(tmp_path: Path) -> None:
    argv = decomposition_argv(
        "/bin/claude",
        prompt="p",
        schema="{}",
        model="claude-opus-5",
        session_id="abc",
        settings=tmp_path / "settings.json",
    )
    pairs = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--")}
    assert pairs["--setting-sources"] == ""
    assert pairs["--settings"] == str(tmp_path / "settings.json")
    assert pairs["--tools"] == ""
    assert pairs["--max-turns"] == "1"
    assert pairs["--model"] == "claude-opus-5"
    assert pairs["--session-id"] == "abc"
    assert pairs["--json-schema"] == "{}"
    assert "--resume" not in argv


def test_the_environment_is_built_from_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHYSGATE_LEAK_PROBE", "should not travel")
    env = isolated_env(
        home=tmp_path / "h",
        config_dir=tmp_path / "c",
        binary="/opt/bin/claude",
        max_retries=0,
        base_url=None,
        api_key=None,
    )
    assert "PHYSGATE_LEAK_PROBE" not in env
    assert env["CLAUDE_CODE_MAX_RETRIES"] == "0"
    assert env["HOME"] == str(tmp_path / "h") and env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "c")
    assert env["PATH"].startswith("/opt/bin:")
    assert "ANTHROPIC_BASE_URL" not in env and "ANTHROPIC_API_KEY" not in env
    with_endpoint = isolated_env(
        home=tmp_path,
        config_dir=tmp_path,
        binary="claude",
        max_retries=2,
        base_url="http://127.0.0.1:1",
        api_key="k",
    )
    assert with_endpoint["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:1"
    assert with_endpoint["CLAUDE_CODE_MAX_RETRIES"] == "2"
