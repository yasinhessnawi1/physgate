"""The run-event log: append-only, synced, and refused when it could not be ours."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from orch_helpers import ticking_clock

from physgate.orchestrator import events as events_module
from physgate.orchestrator.events import (
    EventLog,
    Halted,
    RunStarted,
    StageEntered,
    SubtaskPlanned,
    SubtaskRemoved,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError, RunConfigError

DIGEST = "c" * 64


class _OsWithFsync:
    """The real ``os`` module with ``fsync`` replaced, so the sync can be counted."""

    def __init__(self, fsync: object) -> None:
        self.fsync = fsync

    def __getattr__(self, name: str) -> object:
        return getattr(os, name)


def _log(path: Path) -> EventLog:
    return EventLog(path, run_id="run-1", gate_mode="on", clock=ticking_clock())


def _started(path: Path) -> EventLog:
    log = _log(path)
    log.emit(RunStarted, config_sha256=DIGEST)
    log.emit(
        SubtaskPlanned,
        subtask_id="s1",
        spec_path="specs/s1.md",
        assigned_role="electrical",
        module_dir="modules/power",
    )
    return log


def test_every_stage_transition_is_a_timestamped_line_a_fresh_process_reads_back(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    log = _started(path)
    for stage in ("resolve", "spawn", "verify_reading", "implement", "gate"):
        log.emit(StageEntered, subtask_id="s1", attempt=1, stage=stage)
    # Read by another process while the writer is still open: a line only this
    # handle's memory holds would be missing there.
    code = (
        "import json,sys; from physgate.orchestrator.events import read_events; "
        "print(json.dumps([e.model_dump() for e in read_events(sys.argv[1])]))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(path)], capture_output=True, text=True, check=True
    ).stdout
    seen = json.loads(out)
    log.close()
    assert [e["seq"] for e in seen] == list(range(7))
    stages = [e["stage"] for e in seen if e["kind"] == "stage_entered"]
    assert stages == ["resolve", "spawn", "verify_reading", "implement", "gate"]
    stamps = [datetime.strptime(e["ts"], "%Y-%m-%dT%H:%M:%S.%fZ") for e in seen]
    assert stamps == sorted(stamps)
    assert all(e["gate_mode"] == "on" and e["run_id"] == "run-1" for e in seen)


def test_every_append_is_synced_before_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    real = os.fsync

    def counting_fsync(fd: int) -> None:
        synced.append(fd)
        real(fd)

    monkeypatch.setattr(events_module, "os", _OsWithFsync(counting_fsync))
    log = _started(tmp_path / "events.jsonl")
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="resolve")
    log.close()
    assert len(synced) == 3


def test_an_unterminated_final_line_is_dropped_and_counted(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    _started(path).close()
    whole = path.read_bytes()
    path.write_bytes(whole + b'{"seq": 2, "ts": "2026')
    log = _log(path)
    assert log.torn_tail_bytes == len(b'{"seq": 2, "ts": "2026')
    assert path.read_bytes() == whole
    assert len(log.events) == 2
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="resolve")
    log.close()
    assert [e.seq for e in read_events(path)] == [0, 1, 2]


def _line(**fields: object) -> bytes:
    base: dict[str, object] = {"ts": "2026-09-26T12:00:00.000000Z", "run_id": "run-1"}
    base["gate_mode"] = "on"
    base.update(fields)
    return json.dumps(base).encode() + b"\n"


START = _line(seq=0, kind="run_started", config_sha256=DIGEST)
PLAN = _line(
    seq=1,
    kind="subtask_planned",
    subtask_id="s1",
    spec_path="p",
    assigned_role="electrical",
    module_dir="m",
)

BAD_LOGS = {
    "not utf-8": START + b"\xff\xfe\n",
    "not json": START + b"{not json}\n",
    "wrong shape": START + _line(seq=1, kind="stage_entered", subtask_id="s1"),
    "unknown kind": START + _line(seq=1, kind="made_up"),
    "extra field": START + PLAN[:-2] + b', "extra": 1}\n',
    "a gap in the sequence": START + PLAN.replace(b'"seq": 1', b'"seq": 2'),
    "no start line": PLAN.replace(b'"seq": 1', b'"seq": 0'),
    "a second start": START + _line(seq=1, kind="run_started", config_sha256=DIGEST),
    "another run": START + PLAN.replace(b'"run-1"', b'"run-2"'),
    "another gate mode": START + PLAN.replace(b'"on"', b'"off"'),
    "an unplanned subtask": START
    + _line(seq=1, kind="stage_entered", subtask_id="s9", attempt=1, stage="resolve"),
    "a subtask planned twice": START + PLAN + PLAN.replace(b'"seq": 1', b'"seq": 2'),
    "a bad timestamp": START + PLAN.replace(b"12:00:00.000000Z", b"12:00:00Z"),
    "attempt zero": START
    + PLAN
    + _line(seq=2, kind="stage_entered", subtask_id="s1", attempt=0, stage="resolve"),
}


@pytest.mark.parametrize("case", sorted(BAD_LOGS))
def test_a_complete_line_that_could_not_be_ours_refuses_every_reader(
    tmp_path: Path, case: str
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(BAD_LOGS[case])
    before = path.read_bytes()
    with pytest.raises(CorruptEventLogError) as fresh:
        read_events(path)
    with pytest.raises(CorruptEventLogError) as writer:
        _log(path)
    assert fresh.value.context["offset"] == writer.value.context["offset"]
    assert path.read_bytes() == before, "a refused log is never truncated"


def test_the_writer_refuses_a_line_the_replay_would_refuse_and_writes_nothing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    log = _started(path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="never planned"):
        log.emit(StageEntered, subtask_id="s9", attempt=1, stage="resolve")
    with pytest.raises(ValueError, match="second start"):
        log.emit(RunStarted, config_sha256=DIGEST)
    assert path.read_bytes() == before
    log.emit(SubtaskRemoved, subtask_id="s1", reason="taken out of the plan")
    log.emit(Halted, reason="incident", detail="a foreign journal line")
    log.close()
    assert [type(e) for e in read_events(path)][-2:] == [SubtaskRemoved, Halted]


def test_a_log_is_opened_only_by_its_own_run(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    _started(path).close()
    with pytest.raises(RunConfigError):
        EventLog(path, run_id="run-2", gate_mode="on")
    with pytest.raises(RunConfigError):
        EventLog(path, run_id="run-1", gate_mode="off")


def test_a_timestamp_that_is_not_utc_is_refused(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.jsonl", run_id="run-1", gate_mode="on", clock=datetime.now)
    with pytest.raises(ValueError, match="UTC"):
        log.emit(RunStarted, config_sha256=DIGEST)
    log.close()
