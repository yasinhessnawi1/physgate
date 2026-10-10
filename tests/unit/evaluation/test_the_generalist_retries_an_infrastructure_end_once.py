"""The generalist's review is retried once for an infrastructure end, and never for a verdict.

As the loop's own review: an API error or a session with no result is retried once, with
a fresh session, after the first delay of the paired run's infrastructure retry schedule.
A refused or invalid verdict (the binary's cap on refused verdicts among them) is final
at once, because a fresh session would repeat it. Every try is on the log, saying
whether it is retried.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.evaluation.observe.generalist import review_retried_once
from physgate.orchestrator.events import (
    EventLog,
    ReviewUnavailable,
    RunStarted,
    SubtaskPlanned,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import ReviewResult, UnavailableCause

RESULT = ReviewResult(
    verdict="pass",
    finding="every item is met",
    reviewer_model="claude-sonnet-5",
    session_id="22222222-2222-4222-8222-222222222222",
    usage=(),
    rubric_kind="generalist",
)


class Tries:
    """A review that ends without a verdict for each cause given, then gives ``RESULT``."""

    def __init__(self, *causes: UnavailableCause) -> None:
        self.causes = list(causes)
        self.calls = 0

    def __call__(self) -> ReviewResult:
        self.calls += 1
        if self.causes:
            cause = self.causes.pop(0)
            raise ReviewUnavailableError(
                f"the session ended: {cause}", cause=cause, session_id=f"s{self.calls}"
            )
        return RESULT


def _run(
    tmp_path: Path, tries: Tries, delays: tuple[float, ...] = (60.0, 300.0)
) -> tuple[ReviewResult | ReviewUnavailableError, list[ReviewUnavailable], list[float]]:
    slept: list[float] = []
    log = EventLog(tmp_path / "events.jsonl", run_id="g", gate_mode="on")
    log.append(RunStarted(**log.envelope(), config_sha256="0" * 64))
    log.append(
        SubtaskPlanned(
            **log.envelope(),
            subtask_id="s1",
            spec_path="-",
            assigned_role="control",
            module_dir="-",
        )
    )
    outcome: ReviewResult | ReviewUnavailableError
    try:
        outcome = review_retried_once(
            tries, log, subtask_id="s1", attempt=1, delays=delays, sleep=slept.append
        )
    except ReviewUnavailableError as exc:
        outcome = exc
    finally:
        log.close()
    lines = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, ReviewUnavailable)]
    return outcome, lines, slept


def test_an_infrastructure_end_is_retried_once_after_the_first_delay(tmp_path: Path) -> None:
    tries = Tries("infrastructure")
    outcome, lines, slept = _run(tmp_path, tries)
    assert outcome is RESULT and tries.calls == 2
    assert [(e.cause, e.retry, e.session_id) for e in lines] == [("infrastructure", True, "s1")]
    assert slept == [60.0]


def test_an_empty_schedule_retries_at_once(tmp_path: Path) -> None:
    tries = Tries("infrastructure")
    outcome, _, slept = _run(tmp_path, tries, delays=())
    assert outcome is RESULT and tries.calls == 2 and slept == [0.0]


def test_a_second_infrastructure_end_is_final(tmp_path: Path) -> None:
    tries = Tries("infrastructure", "infrastructure")
    outcome, lines, slept = _run(tmp_path, tries)
    assert isinstance(outcome, ReviewUnavailableError) and outcome.cause == "infrastructure"
    assert tries.calls == 2
    assert [(e.retry, e.session_id) for e in lines] == [(True, "s1"), (False, "s2")]
    assert slept == [60.0]


@pytest.mark.parametrize(
    "cause",
    ["invalid_verdict", "refused", "no_verdict", "reading_incomplete", "compacted",
     "context_exceeded", "unprepared"],
)  # fmt: skip
def test_every_other_cause_is_final_at_once(tmp_path: Path, cause: UnavailableCause) -> None:
    tries = Tries(cause)
    outcome, lines, slept = _run(tmp_path, tries)
    assert isinstance(outcome, ReviewUnavailableError) and outcome.cause == cause
    assert tries.calls == 1 and slept == []
    assert [(e.cause, e.retry) for e in lines] == [(cause, False)]


def test_a_first_verdict_is_not_retried(tmp_path: Path) -> None:
    tries = Tries()
    outcome, lines, slept = _run(tmp_path, tries)
    assert outcome is RESULT and tries.calls == 1 and lines == [] and slept == []
