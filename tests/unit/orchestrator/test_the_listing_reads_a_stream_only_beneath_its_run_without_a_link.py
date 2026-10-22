"""The listing and the command read a trajectory beneath the run, never through a link.

``physgate queue list`` and the command's bound decision read each open item's trajectory
statuses. A trajectory is read by the session id its link names, never by the link as recorded,
and beneath the run directory without following a link at any step: a session directory or a
stream replaced by a link, even one to a copy of the sealed bytes, reads as tampered, never as
the bytes it points at, exactly as the decision function reads it under its lock. An item id is
made only of plain identifiers, so no run or plan name can make one read as a path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, FakeGate, Rig, plan

from physgate.cli import main
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    item_id_for,
    queue_listing,
    read_queue,
    statuses_now,
    trajectory_statuses,
)

ITEM = "run-1-s1"


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "runs" / "run"
    run.mkdir(parents=True)
    rig = Rig(run, dispatcher=FakeDispatcher(trajectories=run / "sessions"))
    rig.gate = FakeGate(verdicts=["fail"] * 3)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    return run


def _first_stream(run: Path) -> Path:
    return Path(read_queue(run).items[0].trajectories[0])


def _statuses(run: Path) -> list[str]:
    listed = queue_listing(run)["open"]
    assert isinstance(listed, list)
    found: list[str] = listed[0]["trajectory_statuses"]
    return found


def test_a_stream_replaced_by_a_link_to_its_own_bytes_reads_as_tampered(
    run_dir: Path, tmp_path: Path
) -> None:
    stream = _first_stream(run_dir)
    copy = tmp_path / "outside" / "stdout.jsonl"
    copy.parent.mkdir()
    copy.write_bytes(stream.read_bytes())  # the sealed bytes: a reader that follows says "holds"
    stream.unlink()
    stream.symlink_to(copy)
    assert _statuses(run_dir)[0] == "tampered"
    assert statuses_now(run_dir, ITEM)[0] == "tampered"


def test_a_session_directory_replaced_by_a_link_reads_as_tampered(
    run_dir: Path, tmp_path: Path
) -> None:
    session_dir = _first_stream(run_dir).parent
    away = tmp_path / "away" / session_dir.name
    away.parent.mkdir()
    os.rename(session_dir, away)
    session_dir.symlink_to(away, target_is_directory=True)
    assert _statuses(run_dir)[0] == "tampered"
    assert statuses_now(run_dir, ITEM)[0] == "tampered"


def test_the_sessions_directory_replaced_by_a_link_reads_as_tampered(
    run_dir: Path, tmp_path: Path
) -> None:
    sessions = run_dir / "sessions"
    away = tmp_path / "away-sessions"
    os.rename(sessions, away)
    sessions.symlink_to(away, target_is_directory=True)
    assert set(_statuses(run_dir)) == {"tampered"}


def test_a_stream_with_a_second_name_reads_as_tampered(run_dir: Path, tmp_path: Path) -> None:
    stream = _first_stream(run_dir)
    os.link(stream, tmp_path / "second-name")
    assert _statuses(run_dir)[0] == "tampered"


def test_a_link_recorded_as_a_parent_step_is_never_opened(run_dir: Path, tmp_path: Path) -> None:
    item = read_queue(run_dir).items[0]
    for link in ("../../outside/stdout.jsonl", "sessions/../../x/stdout.jsonl", "/etc/passwd"):
        forged = item.model_copy(update={"trajectories": (link,)})

        def refuse(session_id: str) -> bytes | None:
            raise AssertionError(f"read {session_id!r}")

        assert trajectory_statuses(forged, [], refuse) == ("not_in_this_run",)


def test_the_command_binds_to_what_it_reads_beneath_the_run(
    run_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stream = _first_stream(run_dir)
    copy = tmp_path / "copy.jsonl"
    copy.write_bytes(stream.read_bytes())
    stream.unlink()
    stream.symlink_to(copy)
    digest = read_queue(run_dir).digests[ITEM]
    before = (run_dir / DECISIONS_NAME).read_bytes()
    code = main(["queue", "resolve", ITEM, "--run-dir", str(run_dir), "--approve",
                 "--sha256", digest, "--by", "yasin"])  # fmt: skip
    assert code == 2
    assert "every trajectory" in json.loads(capsys.readouterr().err)["error"]
    assert (run_dir / DECISIONS_NAME).read_bytes() == before


@pytest.mark.parametrize(
    ("run_id", "subtask_id"),
    [
        ("run-1", "s1/../x"),
        ("run-1", "../s1"),
        ("run-1", "s1\n"),
        ("run/1", "s1"),
        ("run-1", "s1.r2"),
        ("run-1", ""),
        ("run-1", "ｓ1"),
    ],
    ids=["parent step", "leading parent", "trailing newline", "separator", "dot", "empty", "wide"],
)
def test_an_item_id_is_made_of_plain_identifiers_only(run_id: str, subtask_id: str) -> None:
    for round_ in (1, 2):
        with pytest.raises(QueueError, match="plain identifiers"):
            item_id_for(run_id, subtask_id, round_)
