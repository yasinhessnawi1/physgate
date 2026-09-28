"""A run's traces come from its event log: stages, sessions, tokens and gate checks.

Per-step traces, per-check results, and tokens and wall clock per session
(ARCH-145) are read from the lines the orchestrator wrote, never from a file
beside them. Under a clock that moves one millisecond per line, every duration
is exact, so the rules for where a stage and a session begin and end are checked
by the numbers themselves.
"""

from __future__ import annotations

import itertools
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
    assert trace.gate_checks == tuple(gate_events(read_events(run / "events.jsonl")))
    assert [c.subtask_id for c in trace.gate_checks][-1] == "integration"
    assert len(trace.gate_checks) == 3  # one per subtask, one at integration


def test_a_directory_with_no_run_is_a_domain_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        read_traces(tmp_path)
