"""The run list says when each run's log began; the status says when it last wrote, and its bound.

A page names and orders runs by when they started, and tells a run still going from one whose
process is gone. Both are read from the record, never guessed: the run list carries the time of
each log's first line (``None`` for a run with no line yet), so a page need not read every log to
label a run; the status carries the time of the log's last line and the longest a living run goes
without writing one, the run's own session wall clock or its longest retry delay, whichever is
longer. Nothing is written into the run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ui_rig import context_over, fake_ui, run_config, serving, snapshot, write_run

from physgate.orchestrator.events import EventLog, RunStarted, StageEntered, SubtaskPlanned
from physgate.orchestrator.run_config import write_run_config

T0 = datetime(2026, 11, 16, 19, 52, 1, tzinfo=UTC)


def _ticks() -> object:
    moments = iter(T0 + timedelta(minutes=k) for k in range(100))
    return lambda: next(moments)


def _world(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    # A run with three lines a minute apart: started, a subtask planned, its first stage.
    plain = run_config("with-lines")
    bounds = plain.bounds.model_copy(update={"infra_retry_delays_s": (60.0, 300.0)})
    config = plain.model_copy(update={"bounds": bounds})
    (root / "with-lines").mkdir(parents=True)
    write_run_config(root / "with-lines" / "run.json", config)
    log = EventLog(
        root / "with-lines" / "events.jsonl",
        run_id="with-lines",
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
    log.close()
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


def test_the_status_names_the_last_line_and_the_longest_a_living_run_is_silent(
    tmp_path: Path,
) -> None:
    root = _world(tmp_path)
    before = snapshot(root)
    with serving(context_over(root, ui_root=fake_ui(tmp_path / "checkout"))) as server:
        status = server.json("/api/runs/0/with-lines/status")
    assert isinstance(status, dict)
    assert status.get("last_line_at") == "2026-11-16T19:54:01.000000Z"
    # The rig's session wall clock is 120 s; the longest retry delay, 300 s, is longer.
    assert status.get("longest_step_s") == 300.0
    assert snapshot(root) == before
