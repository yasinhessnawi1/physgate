"""A run's traces come from its event log: stages, sessions, tokens and gate checks.

Per-step traces, per-check results, and tokens and wall clock per session
(ARCH-145) are read from the lines the orchestrator wrote, never from a file
beside them. Under a clock that moves one millisecond per line, every duration
is exact, so the rules for where a stage and a session begin and end are checked
by the numbers themselves.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from observe_rig import config, drive, fake_run, start, target_repo

from physgate.evaluation.observe.exceptions import ManifestError
from physgate.evaluation.observe.manifest import read_manifest
from physgate.evaluation.observe.trace import read_traces
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import (
    LeftoverRead,
    SessionEnded,
    StageEntered,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.protocols import Usage
from physgate.orchestrator.record import RunRecord


def ticking() -> Callable[[], datetime]:
    base = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    counter: Iterator[int] = itertools.count()
    return lambda: base + timedelta(milliseconds=next(counter))


@pytest.fixture
def run(tmp_path: Path) -> Path:
    repo = target_repo(tmp_path)
    cfg = start(tmp_path, "run-a", repo)
    drive(tmp_path, cfg, repo, clock=ticking())
    return tmp_path / "run-a"


def test_a_stage_lasts_to_the_next_stage_line_of_its_attempt(run: Path) -> None:
    events = read_events(run / "events.jsonl")
    seq = {e.ts: e.seq for e in events}
    trace = read_traces(run)
    assert trace.steps and trace.manifest_id == read_manifest(run).manifest_id
    for step in trace.steps:
        mine = [
            e
            for e in events
            if getattr(e, "subtask_id", None) == step.subtask_id
            and getattr(e, "attempt", None) == step.attempt
        ]
        stages = [e for e in mine if isinstance(e, StageEntered)]
        at = next(i for i, e in enumerate(stages) if e.ts == step.entered)
        end = stages[at + 1] if at + 1 < len(stages) else mine[-1]
        # One millisecond per line: the duration counts the lines in between.
        assert step.seconds == pytest.approx((end.seq - seq[step.entered]) / 1000)


def stepping_back() -> Callable[[], datetime]:
    """A clock that moves one millisecond backwards per line, as a wall clock can when it is set."""
    base = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    counter: Iterator[int] = itertools.count()
    return lambda: base - timedelta(milliseconds=next(counter))


def _stage_lines(run: Path) -> list[tuple[int, str, int, str]]:
    return [
        (e.seq, e.subtask_id, e.attempt, e.stage)
        for e in read_events(run / "events.jsonl")
        if isinstance(e, StageEntered)
    ]


def test_the_steps_are_in_the_log_s_order_and_name_their_line(run: Path) -> None:
    steps = [(s.seq, s.subtask_id, s.attempt, s.stage) for s in read_traces(run).steps]
    assert len(steps) > 10, "a trace this short says nothing about order"
    assert steps == _stage_lines(run)


def test_a_clock_that_steps_back_does_not_reorder_the_steps(tmp_path: Path) -> None:
    """The log's order is its sequence numbers; a timestamp is what the clock said then.

    Ordered by timestamp, a clock that was set back would show the run's stages
    backwards. Ordered by the line each stage came from, the trace says what the log
    says, whatever the clock did.
    """
    repo = target_repo(tmp_path)
    cfg = start(tmp_path, "run-b", repo)
    drive(tmp_path, cfg, repo, clock=stepping_back())
    run = tmp_path / "run-b"
    timestamps = [e.ts for e in read_events(run / "events.jsonl") if isinstance(e, StageEntered)]
    assert timestamps == sorted(timestamps, reverse=True), "the clock did not step back"
    steps = [(s.seq, s.subtask_id, s.attempt, s.stage) for s in read_traces(run).steps]
    assert steps == _stage_lines(run)


def test_stages_of_two_attempts_that_interleave_stay_interleaved(run: Path) -> None:
    """The trace follows the log line by line, not attempt by attempt.

    Serial dispatch never interleaves two attempts, so grouping by attempt would give
    the same order today. The log reader does not require serial dispatch, though, and
    the trace is a statement about the log: here the second subtask's first stage line
    is moved in before the first subtask's last one, and the trace shows it there.
    """
    path = run / "events.jsonl"
    lines = [json.loads(raw) for raw in path.read_text().splitlines()]
    stages = [i for i, line in enumerate(lines) if line["kind"] == "stage_entered"]
    first = lines[stages[0]]["subtask_id"]
    last_of_first = max(i for i in stages if lines[i]["subtask_id"] == first)
    first_of_second = min(i for i in stages if lines[i]["subtask_id"] != first)
    moved = lines.pop(first_of_second)
    lines.insert(last_of_first, moved)
    for seq, line in enumerate(lines):
        line["seq"] = seq
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    steps = [(s.seq, s.subtask_id, s.attempt, s.stage) for s in read_traces(run).steps]
    subtasks = [step[1] for step in steps]
    second_starts = next(i for i, s in enumerate(subtasks) if s != first)
    assert first in subtasks[second_starts:], "the attempts do not interleave"
    assert steps == _stage_lines(run)


def test_a_session_s_wall_clock_runs_from_its_spawn_line_to_its_end_line(run: Path) -> None:
    events = read_events(run / "events.jsonl")
    trace = read_traces(run)
    assert len(trace.sessions) == 2
    for session in trace.sessions:
        ended = next(
            e for e in events if isinstance(e, SessionEnded) and e.session_id == session.session_id
        )
        spawn = next(
            e
            for e in events
            if isinstance(e, StageEntered)
            and e.stage == "spawn"
            and (e.subtask_id, e.attempt) == (ended.subtask_id, ended.attempt)
        )
        assert session.wall_clock_s == pytest.approx((ended.seq - spawn.seq) / 1000)
        assert session.outcome == "completed" and not session.partial


def test_each_session_s_tokens_are_the_account_s_for_that_session(tmp_path: Path) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    account = TokenAccount.from_events(read_events(run / "events.jsonl")).by_attribution()
    trace = read_traces(run)
    spent = {s.session_id: s.tokens for s in trace.sessions}
    assert spent == {a.split(":", 1)[1]: u for a, u in account.items() if a.startswith("session:")}
    assert len({u.input_tokens for u in spent.values()}) == 2  # two sessions, two amounts
    assert sum(u.total() for u in trace.reviewer_tokens.values()) == 2 * 49
    assert trace.routing_tokens.total() == 0


def test_the_account_s_total_is_the_trace_s_parts_together(tmp_path: Path) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    trace = read_traces(run)
    total = TokenAccount.from_events(read_events(run / "events.jsonl")).total()
    parts = [
        trace.decomposition_tokens,
        trace.routing_tokens,
        *(s.tokens for s in trace.sessions),
        *trace.reviewer_tokens.values(),
    ]
    assert total.total() > 0
    for field in Usage.model_fields:
        assert getattr(total, field) == sum(getattr(part, field) for part in parts)


def test_a_session_left_behind_is_traced_with_its_partial_usage(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    run = fake_run(tmp_path, "run-a", repo)
    record = RunRecord(config("run-a", repo), run)
    usage = Usage(
        input_tokens=7, output_tokens=2, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    record.emit(
        LeftoverRead(
            **record.envelope(),
            session_id="left-1",
            stopped=True,
            complete=False,
            trajectory_seal=None,
        )
    )
    record.emit(
        TokensUsed(
            **record.envelope(),
            attribution="session:left-1",
            message_id="m",
            usage=usage,
            partial=True,
        )
    )
    record.close()
    (left,) = [s for s in read_traces(run).sessions if s.session_id == "left-1"]
    assert (left.outcome, left.subtask_id, left.wall_clock_s) == ("left_over", None, None)
    assert left.partial and left.tokens == usage


def test_every_gate_check_is_in_the_trace_through_the_gate_s_own_reader(run: Path) -> None:
    trace = read_traces(run)
    events = gate_events(read_events(run / "events.jsonl"), trace.manifest_id)
    assert trace.gate_checks == tuple(events)
    assert [c.subtask_id for c in trace.gate_checks][-1] == "integration"
    assert len(trace.gate_checks) == 3  # one per subtask, one at integration
    assert all(c.manifest_id == trace.manifest_id for c in trace.gate_checks)


def test_a_directory_with_no_run_is_a_domain_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        read_traces(tmp_path)
