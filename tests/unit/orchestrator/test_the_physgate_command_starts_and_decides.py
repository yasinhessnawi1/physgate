"""The ``physgate`` command: decompose refuses what it cannot record; the queue CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from physgate.cli import main
from physgate.orchestrator.queue import ApprovalQueue, escalation_item
from physgate.orchestrator.repair import Finding

PARAMS = {
    "gate_mode": "on",
    "models": {
        "decomposition": "claude-opus-5",
        "roles": {"electrical": "claude-sonnet-4-5"},
        "reviewers": {"electrical": "claude-opus-5"},
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


def test_decompose_refuses_to_start_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(_decompose_args(tmp_path, PARAMS)) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("missing", ["gate_mode", "models", "bounds", "token_ceiling"])
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


def test_run_refuses_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(_run_args(tmp_path)) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


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
