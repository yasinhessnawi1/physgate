"""A reviewed run's log, in the shape a real one has, leaves no session open.

The log is written by hand with made-up ids and numbers, in the order and of the kinds a real
reviewed run's log holds them: the plan's review spent before the first subtask, with no spawn
on the log; then per attempt the resolve and spawn stages, the role session's spawn, its tokens
and its end line, the stages up to the review, the review's spawn, its tokens and its verdict.
The lines no end rule reads (the decomposition's, the gate's, the escalation's) are left out.
Taking every spawn for a role session finds each review open; the rule finds none.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import Event, LeftoverRead, SessionEnded, SessionSpawned
from physgate.orchestrator.session_ends import open_sessions, spawn_kind

LOG = Path(__file__).with_name("a_reviewed_run_s_log.jsonl")
EVENT: TypeAdapter[Event] = TypeAdapter(Event)


def _events() -> list[Event]:
    return [EVENT.validate_json(line) for line in LOG.read_text().splitlines()]


def test_every_session_of_a_reviewed_run_s_log_has_ended() -> None:
    events = _events()
    spawned = list(dict.fromkeys(e.session_id for e in events if isinstance(e, SessionSpawned)))
    kinds = [spawn_kind(s, events) for s in spawned]
    assert kinds == ["role session", "module review"] * 3
    assert open_sessions(events) == ()


def test_taking_every_spawn_for_a_role_session_finds_each_review_open() -> None:
    events = _events()
    spawned = {e.session_id for e in events if isinstance(e, SessionSpawned)}
    ended = {e.session_id for e in events if isinstance(e, SessionEnded | LeftoverRead)}
    assert {spawn_kind(s, events) for s in spawned - ended} == {"module review"}
    assert len(spawned - ended) == 3


def test_its_total_counts_the_plan_s_review_and_every_module_review_once() -> None:
    account = TokenAccount.from_events(_events())
    by_kind = {k: u.total() for k, u in account.by_kind().items()}
    reviewers = [a for a in account.by_attribution() if a.startswith("reviewer:")]
    assert len(reviewers) == 4, "the plan's review and the three module reviews"
    assert account.total().total() == sum(by_kind.values())
