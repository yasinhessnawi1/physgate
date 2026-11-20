"""The run list says when each run's log began; the status says when it last wrote, and its bound.

A page names and orders runs by when they started, and tells a run still going from one whose
process is gone. Both are read from the record, never guessed: the run list carries the time of
each log's first line (``None`` for a run with no line yet), so a page need not read every log to
label a run. The status carries the time of the log's last line, the server's own clock (so a
page measures the silence on it, and a browser whose clock differs judges nothing), and the
longest a living run goes without a line after that one: after a session's spawn, the run's
session wall clock (the session is stopped there and its end written); after a retry's schedule,
the delay it recorded. After any other line the work that follows may be one with no bound of its
own (the physics gate, the OS layer's start, a contract test), so no bound is sent and a page
claims nothing. Nothing is written into the run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ui_rig import context_over, fake_ui, run_config, serving, snapshot, write_run

from physgate.orchestrator.events import (
    EventLog,
    InfraRetryScheduled,
    ProposalsChecked,
    RunStarted,
    SessionEnded,
    SessionSpawned,
    StageEntered,
    SubtaskPlanned,
)
from physgate.orchestrator.run_config import write_run_config

T0 = datetime(2026, 11, 16, 19, 52, 1, tzinfo=UTC)


def _ticks() -> object:
    moments = iter(T0 + timedelta(minutes=k) for k in range(100))
    return lambda: next(moments)


def _run(root: Path, name: str, last: Callable[[EventLog], None] | None) -> None:
    """A run whose log is started, plans s1, enters its first stage, then writes ``last``."""
    plain = run_config(name)
    bounds = plain.bounds.model_copy(update={"infra_retry_delays_s": (60.0, 300.0)})
    config = plain.model_copy(update={"bounds": bounds})
    (root / name).mkdir(parents=True)
    write_run_config(root / name / "run.json", config)
    log = EventLog(
        root / name / "events.jsonl",
        run_id=name,
        gate_mode=config.gate_mode,
        clock=_ticks(),  # type: ignore[arg-type]
    )
    log.emit(RunStarted, config_sha256=config.sha256())
    log.emit(
        SubtaskPlanned,
        subtask_id="s1",
        spec_path="specs/s1.md",
        assigned_role="drivetrain",
        module_dir="modules/drivetrain",
    )
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="resolve")
    if last is not None:
        last(log)
    log.close()


def _spawned(log: EventLog) -> None:
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="spawn")
    log.emit(SessionSpawned, session_id="sess-1", pid=4242, started="Mon Nov 16 19:55:01 2026")


def _ended(log: EventLog, outcome: str, commit: str | None) -> None:
    log.emit(
        SessionEnded,
        subtask_id="s1",
        attempt=1,
        session_id="sess-1",
        outcome=outcome,
        cause=None if outcome == "completed" else "api_error",
        attempt_commit=commit,
        trajectory=None if commit is None else "sessions/sess-1/stdout.jsonl",
        decisions_bytes=0,
        worktree="worktrees/s1",
        reading_verified=commit is not None,
    )


def _gate(log: EventLog) -> None:
    _spawned(log)
    _ended(log, "completed", "f" * 40)
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="verify_reading")
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="implement")
    log.emit(
        ProposalsChecked,
        subtask_id="s1",
        attempt=1,
        checked_commit="f" * 40,
        refused_by=None,
        reason=None,
        subject=None,
        graph_root="scratch/graph",
    )
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="gate")


def _retry(log: EventLog) -> None:
    _spawned(log)
    _ended(log, "infrastructure", None)
    log.emit(InfraRetryScheduled, subtask_id="s1", attempt=1, retries_done=0, delay_s=45.0)


RUNS = ("with-lines", "in-a-session", "at-the-gate", "retrying")


def _world(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    _run(root, "with-lines", None)
    _run(root, "in-a-session", _spawned)
    _run(root, "at-the-gate", _gate)
    _run(root, "retrying", _retry)
    # A run decomposed but not started: its configuration and no log.
    write_run(root / "no-lines", "no-lines")
    return root


def test_the_run_list_names_when_each_log_began(tmp_path: Path) -> None:
    root = _world(tmp_path)
    before = snapshot(root)
    with serving(context_over(root, ui_root=fake_ui(tmp_path / "checkout"))) as server:
        runs = {r["name"]: r for r in json.loads(server.request("GET", "/api/runs")[2])["runs"]}
    assert runs["with-lines"].get("started") == "2026-11-16T19:52:01.000000Z"
    assert "started" in runs["no-lines"]
    assert runs["no-lines"]["started"] is None
    assert snapshot(root) == before


def _statuses(tmp_path: Path) -> tuple[dict[str, dict[str, object]], datetime, datetime]:
    root = _world(tmp_path)
    before = snapshot(root)
    found: dict[str, dict[str, object]] = {}
    with serving(context_over(root, ui_root=fake_ui(tmp_path / "checkout"))) as server:
        asked = datetime.now(UTC)
        for name in RUNS:
            status = server.json(f"/api/runs/0/{name}/status")
            assert isinstance(status, dict)
            found[name] = status
        answered = datetime.now(UTC)
    assert snapshot(root) == before
    return found, asked, answered


def test_the_status_names_the_last_line_and_the_server_s_clock(tmp_path: Path) -> None:
    found, asked, answered = _statuses(tmp_path)
    status = found["with-lines"]
    assert status.get("last_line_at") == "2026-11-16T19:54:01.000000Z"
    now = status.get("server_now")
    assert isinstance(now, str)
    told = datetime.strptime(now, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    assert asked - timedelta(seconds=1) <= told <= answered + timedelta(seconds=1)
    # Fixed width, as the log writes a time: a GET and a HEAD a moment apart answer one length.
    assert len(now) == len("2026-11-16T19:54:01.000000Z")


def test_a_session_s_spawn_is_bounded_by_the_session_wall_clock(tmp_path: Path) -> None:
    found, _, _ = _statuses(tmp_path)
    # The rig's session wall clock is 120 s; the retry delays (60 s, 300 s) are not this step's.
    assert found["in-a-session"].get("silence_bound_s") == 120.0
    assert "longest_step_s" not in found["in-a-session"]


def test_a_retry_s_schedule_is_bounded_by_its_own_recorded_delay(tmp_path: Path) -> None:
    found, _, _ = _statuses(tmp_path)
    assert found["retrying"].get("silence_bound_s") == 45.0


def test_no_bound_is_sent_where_a_stage_with_none_of_its_own_may_be_running(
    tmp_path: Path,
) -> None:
    found, _, _ = _statuses(tmp_path)
    # The physics gate runs after its stage line and writes nothing until it has run; the
    # OS layer's start and a contract test likewise follow lines that are not a spawn's.
    for name in ("at-the-gate", "with-lines"):
        assert "silence_bound_s" in found[name], name
        assert found[name]["silence_bound_s"] is None, name
