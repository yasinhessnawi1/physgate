"""The ``physgate`` command: decompose refuses what it cannot record; the queue CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from physgate.cli import main
from physgate.orchestrator.queue import ApprovalQueue, escalation_item
from physgate.orchestrator.repair import Finding

PARAMS = {
    "auth": "api_key",
    "gate_mode": "on",
    "models": {
        "decomposition": "claude-sonnet-5",
        "roles": {"electrical": "claude-sonnet-5"},
        "reviewers": {"electrical": "claude-opus-5-5"},
    },
    "bounds": {
        "binary_max_retries": 0,
        "session_wall_clock_s": 120.0,
        "session_max_turns": 20,
        "infra_retry_delays_s": [],
    },
    "token_ceiling": 100000,
}


def fake_binary(tmp_path: Path, version: str) -> Path:
    """A stand-in binary that only answers ``--version``."""
    script = tmp_path / "bin" / "claude"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f'#!/bin/sh\necho "{version} (Claude Code)"\n')
    script.chmod(0o755)
    return script


def test_a_binary_that_is_not_the_pinned_version_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.273")))
    assert main(_decompose_args(tmp_path, PARAMS)) == 2
    assert "2.1.273" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


def _decompose_args(tmp_path: Path, params: dict[str, object]) -> list[str]:
    (tmp_path / "brief.md").write_text("Build a robot.\n")
    (tmp_path / "params.json").write_text(json.dumps(params))
    return [
        "decompose",
        str(tmp_path / "brief.md"),
        "--seed",
        "7",
        "--run-id",
        "run-1",
        "--params",
        str(tmp_path / "params.json"),
        "--target",
        str(Path(__file__).resolve().parents[3]),
        "--run-dir",
        str(tmp_path / "run"),
    ]


OTHER = {"api_key": "CLAUDE_CODE_OAUTH_TOKEN", "subscription": "ANTHROPIC_API_KEY"}
NEEDED = {"api_key": "ANTHROPIC_API_KEY", "subscription": "CLAUDE_CODE_OAUTH_TOKEN"}


@pytest.mark.parametrize("mode", ["api_key", "subscription"])
def test_decompose_refuses_to_start_without_the_secret_its_auth_mode_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str
) -> None:
    monkeypatch.delenv(NEEDED[mode], raising=False)
    monkeypatch.setenv(OTHER[mode], "the-other-mode-s-secret-is-not-a-substitute")
    monkeypatch.setenv("PATH", "/nonexistent")  # refused before the binary is even looked for
    monkeypatch.delenv("PHYSGATE_CLAUDE_BIN", raising=False)
    assert main(_decompose_args(tmp_path, {**PARAMS, "auth": mode})) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == f"{NEEDED[mode]} is not set; a run in auth mode {mode} needs it"
    assert (error["auth"], error["variable"]) == (mode, NEEDED[mode])
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("missing", ["auth", "gate_mode", "models", "bounds", "token_ceiling"])
def test_decompose_refuses_parameters_missing_any_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    params = {k: v for k, v in PARAMS.items() if k != missing}
    assert main(_decompose_args(tmp_path, params)) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["reason"].startswith(missing)
    assert not (tmp_path / "run").exists()


def _queue(run_dir: Path) -> None:
    finding = Finding(source="gate", text="too hot")
    ApprovalQueue(run_dir / "queue.jsonl").add(
        escalation_item(
            item_id="q1",
            run_id="run-1",
            subtask_id="s1",
            findings=(finding, finding, finding),
            artefact_diff="",
            trajectories=("a", "b", "c"),
            ts="2026-09-26T12:00:00.000000Z",
        )
    )


def test_the_queue_is_listed_and_a_decision_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _queue(tmp_path)
    assert main(["queue", "list", "--run-dir", str(tmp_path)]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [item["item_id"] for item in listed["open"]] == ["q1"]
    args = ["queue", "resolve", "q1", "--run-dir", str(tmp_path), "--decision", "split it"]
    assert main([*args, "--by", "yasin"]) == 0
    capsys.readouterr()
    assert main(["queue", "list", "--run-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"open": []}
    assert main([*args, "--by", "yasin"]) == 2
    assert "not an open item" in capsys.readouterr().err


def test_the_hook_layer_is_still_reachable_through_the_one_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    code = main(
        [
            "hooks",
            "install",
            "--profile",
            "role",
            "--role",
            "electrical",
            "--worktree",
            str(worktree),
            "--state-dir",
            str(tmp_path / "state"),
            "--target",
            str(tmp_path / "session"),
            "--claude-config-dir",
            str(tmp_path / "cfg"),
            "--ceiling",
            "1000",
        ]
    )
    assert code == 0
    assert "--setting-sources" in json.loads(capsys.readouterr().out)["spawn_args"]


def _run_args(tmp_path: Path) -> list[str]:
    (tmp_path / "install" / "bin").mkdir(parents=True, exist_ok=True)
    return [
        "run",
        "--run-dir",
        str(tmp_path / "run"),
        "--target",
        str(tmp_path),
        "--install",
        str(tmp_path / "install"),
    ]


@pytest.mark.parametrize("command", ["run", "resume"])
@pytest.mark.parametrize("mode", ["api_key", "subscription"])
def test_a_run_is_refused_without_the_secret_its_recorded_mode_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    command: str,
) -> None:
    from loop_fakes import FakeGate, FakeReviewer
    from orch_helpers import make_config

    from physgate.orchestrator.cli import Registrations
    from physgate.orchestrator.record import RunRecord

    record = RunRecord(make_config(auth=mode), tmp_path / "run")
    record.start([])
    record.close()
    events = (tmp_path / "run" / "events.jsonl").read_bytes()
    monkeypatch.delenv(NEEDED[mode], raising=False)
    monkeypatch.setenv(OTHER[mode], "the-other-mode-s-secret-is-not-a-substitute")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PHYSGATE_CLAUDE_BIN", raising=False)
    registrations = Registrations(gate=FakeGate(), reviewers={"electrical": FakeReviewer()})
    assert main([command, *_run_args(tmp_path)[1:]], registrations) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["variable"] == NEEDED[mode]
    assert (tmp_path / "run" / "events.jsonl").read_bytes() == events
    assert not (tmp_path / "run" / "sessions").exists()


def test_both_example_parameters_files_are_complete_configurations() -> None:
    from physgate.orchestrator.cli import EXAMPLES
    from physgate.orchestrator.run_config import RunConfig

    found = {}
    for path in sorted(EXAMPLES.glob("params.*.json")):
        params = json.loads(path.read_text())
        # As the command reads them: JSON, validated as JSON.
        config = RunConfig.model_validate_json(
            json.dumps(
                {
                    **params,
                    "run_id": "r",
                    "seed": 1,
                    "brief_sha256": "a" * 64,
                    "claude_version": "2.1.272",
                    "target_head": "b" * 40,
                    "endpoint": "default",
                }
            )
        )
        found[config.auth] = config
        text = path.read_text()
        assert "sk-" not in text and "TOKEN" not in text.upper().replace("TOKEN_CEILING", "")
        for role, model in config.models.roles.items():
            assert config.models.reviewers[role] != model  # ARCH-060: another model reviews
    assert set(found) == {"subscription", "api_key"}
    assert found["subscription"].models.reviewers["electrical"] == "claude-opus-5-5"
    assert found["api_key"].models.reviewers["electrical"] == "claude-haiku-4-5-20251001"
    assert {c.models.roles["electrical"] for c in found.values()} == {"claude-sonnet-5"}


def test_run_refuses_a_directory_that_holds_no_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    assert main(_run_args(tmp_path)) == 2
    assert "no run configuration" in capsys.readouterr().err


def test_run_refuses_to_start_with_no_gate_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from orch_helpers import make_config

    from physgate.orchestrator.record import RunRecord

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.delenv("PHYSGATE_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")  # no binary either: the gate is refused first
    record = RunRecord(make_config(), tmp_path / "run")
    record.start([])
    record.close()
    assert main(_run_args(tmp_path)) == 2
    assert "no gate is registered" in capsys.readouterr().err


def test_the_run_command_says_where_its_directory_belongs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["run", "--help"])
    assert "local disk" in capsys.readouterr().out


def test_a_run_whose_record_holds_a_routing_token_fails_at_the_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from loop_fakes import FakeGate, FakeReviewer
    from orch_helpers import make_config

    from physgate.orchestrator.cli import Registrations
    from physgate.orchestrator.events import TokensUsed
    from physgate.orchestrator.protocols import Usage
    from physgate.orchestrator.record import RunRecord

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    record = RunRecord(make_config(), tmp_path / "run")
    record.start([])
    one = Usage(
        input_tokens=1, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    record.emit(
        TokensUsed(**record.envelope(), attribution="routing:loop", message_id="m", usage=one)
    )
    record.close()
    registrations = Registrations(gate=FakeGate(), reviewers={"electrical": FakeReviewer()})
    assert main(_run_args(tmp_path), registrations) == 2
    assert "tokens were spent on routing" in capsys.readouterr().err


def _recorded_run(tmp_path: Path, endpoint: str) -> None:
    from orch_helpers import make_config

    from physgate.orchestrator.record import RunRecord

    record = RunRecord(make_config(endpoint=endpoint), tmp_path / "run")
    record.start([])
    record.close()


@pytest.mark.parametrize("command", ["run", "resume"])
def test_a_run_is_refused_against_another_endpoint_before_any_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    from loop_fakes import FakeGate, FakeReviewer

    from physgate.orchestrator.cli import Registrations

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.delenv("PHYSGATE_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")
    _recorded_run(tmp_path, "http://127.0.0.1:53817")
    registrations = Registrations(gate=FakeGate(), reviewers={"electrical": FakeReviewer()})
    args = [command, *_run_args(tmp_path)[1:]]
    events = (tmp_path / "run" / "events.jsonl").read_bytes()

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    assert main(args, registrations) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "the endpoint differs from the one this run recorded"
    assert (error["recorded"], error["now"]) == (
        "http://127.0.0.1:53817",
        "https://api.anthropic.com",
    )
    monkeypatch.delenv("ANTHROPIC_BASE_URL")
    assert main(args, registrations) == 2
    assert json.loads(capsys.readouterr().err)["now"] == "default"
    assert (tmp_path / "run" / "events.jsonl").read_bytes() == events

    # The recorded endpoint passes this check; what stops the run then is the missing binary.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:53817/")
    assert main(args, registrations) == 2
    assert "no Claude Code binary" in capsys.readouterr().err
