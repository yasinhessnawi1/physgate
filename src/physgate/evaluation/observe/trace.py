"""A run's traces: per step, per session, per gate check, read from its event log.

ARCH-145 asks for per-step traces, per-check results and tokens and wall clock per
session. All of it is already in the run-event log the orchestrator wrote, every
line timestamped to the microsecond, so a trace is derived from the log and never
written beside it: a copy would be a second record that could disagree with the
first.

Durations are differences between recorded timestamps, and they say exactly that:

- **a stage** lasts from its line to the next stage line of the same attempt; an
  attempt's last stage lasts to the attempt's last line;
- **a session's wall clock** runs from the attempt's ``spawn`` stage line to its
  end line. It includes the orchestrator's own setup for the session (the
  worktree, the hooks' settings, the credential file), not only the model's time.

**The steps are in the log's order**, by the sequence number of the line each
stage came from, never by its timestamp. A timestamp is what the clock said when
the line was written, and nothing makes the clock move forwards: a clock that is
set back would otherwise show a run's stages in reverse.

The per-check gate results come from the one reader of the gate's records,
``gate_events``, so their fields are named in one place.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from physgate.evaluation.observe.manifest import manifest_id_of, read_run_events
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.common import Timestamp
from physgate.orchestrator.events import (
    Event,
    LeftoverRead,
    SessionEnded,
    Stage,
    StageEntered,
    TokensUsed,
)
from physgate.orchestrator.gate_events import GateEvent, gate_events
from physgate.orchestrator.protocols import Usage

_ZERO = Usage(
    input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class StageTiming(_Frozen):
    """How long one stage of one attempt took, by the log's own timestamps."""

    #: The sequence number of the stage's line: the trace's order, and its tie to the log.
    seq: Annotated[int, Field(ge=0)]
    subtask_id: str
    attempt: Annotated[int, Field(ge=1)]
    stage: Stage
    entered: Timestamp
    seconds: Annotated[float, Field(ge=0)]


class SessionTrace(_Frozen):
    """One role session: when it ran, how it ended, and what it spent."""

    session_id: str
    #: ``None`` for a session a previous orchestrator left behind: the log names its
    #: session but not its subtask, because nothing recorded its end.
    subtask_id: str | None
    attempt: Annotated[int, Field(ge=1)] | None
    outcome: Literal["completed", "infrastructure", "left_over"]
    cause: str | None
    #: From the spawn stage line to the session's end line, including the
    #: orchestrator's setup for the session; ``None`` when either line is missing.
    wall_clock_s: Annotated[float, Field(ge=0)] | None
    tokens: Usage
    #: Some of its usage was read from a stream with no result: it may be cut short.
    partial: bool


class RunTrace(_Frozen):
    """Everything a run's log says about where the time and the tokens went."""

    manifest_id: str
    run_id: str
    started: Timestamp
    last: Timestamp
    steps: tuple[StageTiming, ...]
    sessions: tuple[SessionTrace, ...]
    decomposition_tokens: Usage
    reviewer_tokens: dict[str, Usage]
    routing_tokens: Usage
    gate_checks: tuple[GateEvent, ...]


def _at(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _seconds(start: str, end: str) -> float:
    return max((_at(end) - _at(start)).total_seconds(), 0.0)


def _steps(events: list[Event]) -> tuple[StageTiming, ...]:
    by_attempt: dict[tuple[str, int], list[Event]] = defaultdict(list)
    for event in events:
        subtask, attempt = getattr(event, "subtask_id", None), getattr(event, "attempt", None)
        if subtask is not None and isinstance(attempt, int):
            by_attempt[(subtask, attempt)].append(event)
    timings = []
    for (subtask, attempt), lines in by_attempt.items():
        stages = [e for e in lines if isinstance(e, StageEntered)]
        for here, after in zip(stages, [*stages[1:], None], strict=True):
            end = after.ts if after is not None else lines[-1].ts
            timings.append(
                StageTiming(
                    seq=here.seq,
                    subtask_id=subtask,
                    attempt=attempt,
                    stage=here.stage,
                    entered=here.ts,
                    seconds=_seconds(here.ts, end),
                )
            )
    return tuple(sorted(timings, key=lambda t: t.seq))


def _sessions(events: list[Event], account: TokenAccount) -> tuple[SessionTrace, ...]:
    tokens = account.by_attribution()
    partial = {e.attribution for e in events if isinstance(e, TokensUsed) and e.partial}
    spawned: dict[tuple[str, int], str] = {}
    sessions = []
    for event in events:
        if isinstance(event, StageEntered) and event.stage == "spawn":
            spawned[(event.subtask_id, event.attempt)] = event.ts
        elif isinstance(event, SessionEnded | LeftoverRead):
            key = f"session:{event.session_id}"
            if isinstance(event, SessionEnded):
                start = spawned.pop((event.subtask_id, event.attempt), None)
                subtask, attempt = event.subtask_id, event.attempt
                outcome: Literal["completed", "infrastructure", "left_over"] = event.outcome
                cause: str | None = event.cause
            else:
                start, subtask, attempt, outcome, cause = None, None, None, "left_over", None
            sessions.append(
                SessionTrace(
                    session_id=event.session_id,
                    subtask_id=subtask,
                    attempt=attempt,
                    outcome=outcome,
                    cause=cause,
                    wall_clock_s=_seconds(start, event.ts) if start else None,
                    tokens=tokens.get(key, _ZERO),
                    partial=key in partial,
                )
            )
    return tuple(sessions)


def read_traces(run_dir: Path) -> RunTrace:
    """The run's traces, derived from its event log; the one reader of the format.

    Raises:
        ManifestError: the log or the configuration is missing, or they disagree.
    """
    events = read_run_events(run_dir)
    manifest_id = manifest_id_of(run_dir, events)
    account = TokenAccount.from_events(events)
    by_attribution = account.by_attribution()
    kinds = account.by_kind()
    return RunTrace(
        manifest_id=manifest_id,
        run_id=events[0].run_id,
        started=events[0].ts,
        last=events[-1].ts,
        steps=_steps(events),
        sessions=_sessions(events, account),
        decomposition_tokens=kinds["decomposition"],
        reviewer_tokens={
            a.split(":", 1)[1]: u for a, u in by_attribution.items() if a.startswith("reviewer:")
        },
        routing_tokens=kinds["routing"],
        gate_checks=tuple(gate_events(events, manifest_id)),
    )
