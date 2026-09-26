"""How the binary is invoked: pinned version, isolated argv, environment from nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.orchestrator.credentials import Credential
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
        model="claude-sonnet-5",
        session_id="abc",
        settings=tmp_path / "settings.json",
    )
    pairs = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--")}
    assert pairs["--setting-sources"] == ""
    assert pairs["--settings"] == str(tmp_path / "settings.json")
    assert pairs["--tools"] == ""
    assert pairs["--max-turns"] == "1"
    assert pairs["--model"] == "claude-sonnet-5"
    assert pairs["--session-id"] == "abc"
    assert pairs["--json-schema"] == "{}"
    assert "--include-partial-messages" in argv  # each message's final usage
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


def _binary(tmp_path: Path, version: str) -> Path:
    script = tmp_path / "claude"
    script.write_text(f'#!/bin/sh\necho "{version} (Claude Code)"\n')
    script.chmod(0o755)
    return script


def test_the_reported_version_is_read_from_the_binary_itself(tmp_path: Path) -> None:
    from physgate.orchestrator.decompose import binary_version

    assert binary_version(str(_binary(tmp_path, "2.1.272"))) == "2.1.272"
    with pytest.raises(InvocationError):
        binary_version(str(_binary(tmp_path, "2.1.280")))


def test_a_binary_that_changed_since_the_run_recorded_it_is_refused_before_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orch_helpers import make_config

    from physgate.orchestrator.decompose import call

    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(_binary(tmp_path, "2.1.272")))
    recorded_elsewhere = make_config(claude_version="2.1.271")
    with pytest.raises(InvocationError, match="not the version this run recorded"):
        call(
            "brief",
            config=recorded_elsewhere,
            workdir=tmp_path / "w",
            base_url=None,
            credential=Credential("api_key", "k"),
            override=tmp_path / "unused-override.json",
        )
    assert not (tmp_path / "w").exists()


def test_the_decomposition_call_is_spawned_with_the_run_s_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orch_helpers import make_config

    from physgate.orchestrator.decompose import call
    from physgate.orchestrator.managed import write_override

    seen = tmp_path / "env.txt"
    script = tmp_path / "claude"
    script.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "2.1.272 (Claude Code)"; exit 0; fi\n'
        f"env > '{seen}'\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(script))
    override = write_override(tmp_path / "run")
    outcome = call(
        "brief",
        config=make_config(),
        workdir=tmp_path / "run" / "decomposition",
        base_url=None,
        credential=Credential("api_key", "k"),
        override=override,
    )
    assert not outcome.ok  # the stand-in answers nothing
    assert f"CLAUDE_CODE_REMOTE_SETTINGS_PATH={override}" in seen.read_text().splitlines()
