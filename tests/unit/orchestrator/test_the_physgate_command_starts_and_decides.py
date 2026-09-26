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
