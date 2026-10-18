from __future__ import annotations

import json
from pathlib import Path

import pytest
from control_fixtures import GOOD_PID, control_task, controller

from physgate.evaluation.per_role.validate import id_digest, validate


def _write(
    root: Path,
    task_id: str,
    brief: str,
    good: dict,  # type: ignore[type-arg]
    bad: dict,  # type: ignore[type-arg]
    *,
    held_out: bool = False,
) -> None:
    task = json.loads(control_task().model_dump_json())
    task.update(id=task_id, brief=brief)
    if held_out:
        task.update(tier="held_out", canary="0" * 32)
    d = root / task_id
    (d / "references" / "good").mkdir(parents=True)
    (d / "references" / "bad_unstable").mkdir(parents=True)
    (d / "task.json").write_text(json.dumps(task))
    (d / "references" / "good" / "answer.json").write_text(json.dumps(good))
    (d / "references" / "bad_unstable" / "answer.json").write_text(json.dumps(bad))
    (d / "references" / "bad_unstable" / "expect.json").write_text('{"fails": "stable"}')


def test_counts_ids_and_a_digest_are_all_it_reports(tmp_path: Path) -> None:
    unstable = controller([1.0], [1.0], gain=0.1)
    _write(tmp_path, "control.a", "Hold the plant 10/(s^2-2s+3).", GOOD_PID, unstable)
    _write(
        tmp_path,
        "control.b",
        "Hold it; try 1.02 s^2 + 2.04 s + 4 over 0.01 s^2 + s.",
        GOOD_PID,
        unstable,
    )
    _write(tmp_path, "control.c", "Hold the plant.", unstable, unstable)
    report = validate(tmp_path, show_ids=True)
    assert report["tasks"] == 3 and report["references_held"] == 2
    assert report["refused"] == ["control.c"]
    assert report["brief_gives_the_answer"] == ["control.b"]
    assert set(report) == {
        "tasks",
        "references_held",
        "refused",
        "brief_gives_the_answer",
        "ids",
        "ids_shown",
        "sha256",
    }
    assert validate(tmp_path)["refused"] == [id_digest("control.c")]


def test_a_held_out_tier_s_ids_are_reported_only_as_digests_even_when_asked_for(
    tmp_path: Path,
) -> None:
    unstable = controller([1.0], [1.0], gain=0.1)
    _write(tmp_path, "control.cartpole", "Hold the plant.", GOOD_PID, unstable, held_out=True)
    _write(tmp_path, "control.balance", "Hold the plant.", unstable, unstable, held_out=True)
    report = validate(tmp_path, show_ids=True)
    assert report["ids_shown"] is False
    assert report["ids"] == sorted([id_digest("control.cartpole"), id_digest("control.balance")])
    assert report["refused"] == [id_digest("control.balance")]
    assert "cartpole" not in json.dumps(report) and "balance" not in json.dumps(report)


def test_a_task_that_does_not_load_keeps_a_visible_tier_s_ids_hidden(tmp_path: Path) -> None:
    unstable = controller([1.0], [1.0], gain=0.1)
    _write(tmp_path, "control.a", "Hold the plant.", GOOD_PID, unstable)
    (tmp_path / "control.unreadable").mkdir()
    report = validate(tmp_path, show_ids=True)
    assert report["ids_shown"] is False
    assert report["refused"] == [id_digest("control.unreadable")]


def _command(argv: list[str]) -> int:
    import argparse

    from physgate.evaluation.per_role import cli

    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    args = parser.parse_args(["per-role", "validate", *argv])
    result: int = args.func(args)
    return result


def test_the_command_prints_only_counts_ids_and_a_digest_and_fails_a_tier_short_of_whole(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unstable = controller([1.0], [1.0], gain=0.1)
    for name in ("control.a", "control.b"):
        _write(tmp_path, name, "Hold the plant 10/(s^2-2s+3).", GOOD_PID, unstable)
    assert _command(["--tier", str(tmp_path), "--tasks", "2"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["ids"] == sorted(map(id_digest, ["control.a", "control.b"]))
    assert printed["refused"] == []
    assert "Hold the plant" not in json.dumps(printed)
    assert _command(["--tier", str(tmp_path), "--tasks", "2", "--show-ids"]) == 0
    assert json.loads(capsys.readouterr().out)["ids"] == ["control.a", "control.b"]
    assert _command(["--tier", str(tmp_path), "--tasks", "3"]) == 1
    _write(tmp_path, "control.c", "Hold the plant.", unstable, unstable)
    assert _command(["--tier", str(tmp_path), "--tasks", "3"]) == 1


def test_the_command_fails_a_whole_tier_beside_a_directory_that_holds_no_task(
    tmp_path: Path,
) -> None:
    unstable = controller([1.0], [1.0], gain=0.1)
    for name in ("control.a", "control.b"):
        _write(tmp_path, name, "Hold the plant.", GOOD_PID, unstable)
    (tmp_path / "control.empty").mkdir()
    assert _command(["--tier", str(tmp_path), "--tasks", "2"]) == 1


def test_the_command_fails_a_whole_tier_whose_brief_gives_its_answer_away(
    tmp_path: Path,
) -> None:
    unstable = controller([1.0], [1.0], gain=0.1)
    _write(tmp_path, "control.a", "Hold the plant.", GOOD_PID, unstable)
    leaking = "Try 1.02 s^2 + 2.04 s + 4 over 0.01 s^2 + s."
    _write(tmp_path, "control.b", leaking, GOOD_PID, unstable)
    assert _command(["--tier", str(tmp_path), "--tasks", "2"]) == 1
