"""A session no model answered is an infrastructure failure, never a change of policy limits.

Every session starts from a fresh configuration directory, and the binary fetches the
account's policy limits into it. A connection that drops before that fetch leaves no file,
and the session ends ``api_error`` with only the binary's own error message in its stream.
No model answered it, so no tool ran under any limits: its missing file is recorded, not
held to the run's first, and the session is retried and counted like any other
infrastructure failure. The binary writes its ``init`` line before any request, so that
line is no sign the session reached the API; a model's answer is.

Limits that appear, limits that change, and limits missing after a session a model did
answer stay incidents, as before.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator import managed
from physgate.orchestrator.budget import classify_session_end
from physgate.orchestrator.decompose import read_stream
from physgate.orchestrator.events import (
    RESUMABLE_HALTS,
    Halted,
    Incident,
    InfraRetryScheduled,
    SessionEnded,
    read_events,
)
from physgate.orchestrator.ports import SessionReport
from physgate.orchestrator.record import DecompositionSummary

LIMITS = hashlib.sha256(b'{"restrictions": {}}').hexdigest()
OTHER = hashlib.sha256(b'{"restrictions": {"x": {"allowed": false}}}').hexdigest()
PINNED = "claude-opus-5-5"


def _require_the_marker() -> None:
    if "model_answered" not in SessionReport.model_fields:
        pytest.fail("a session's report does not say whether a model answered it")
    if "policy_limits_unjudged" not in SessionEnded.model_fields:
        pytest.fail("a session's end line does not record limits that were not judged")


def _start_with_limits(rig: Rig, limits: str | None) -> None:
    loop = rig.open()
    loop.record.start(
        plan("s1"),
        decomposed=DecompositionSummary(
            session_id="d1",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=1,
            interface_nodes=("iface.bus",),
            spec_commit="a" * 40,
            head_revision=1,
            policy_limits_sha256=limits,
        ),
    )
    loop.close()


def test_a_drop_before_any_answer_is_retried_then_exhausted_and_resumable_never_an_incident(
    tmp_path: Path,
) -> None:
    # The sequence the run met: an attempt's session a model answered ends ``api_error``
    # with the run's limits; its retry drops before any answer and leaves none; so does the
    # next. Two retries, then the schedule is spent.
    _require_the_marker()
    dispatcher = FakeDispatcher(
        infra={1: "api_error", 2: "api_error", 3: "api_error"},
        policy={1: LIMITS, 4: LIMITS},  # the resume's session receives the run's limits
        unanswered={2, 3},
    )
    rig = Rig(tmp_path, dispatcher=dispatcher, delays=(60.0, 60.0))
    _start_with_limits(rig, LIMITS)
    loop = rig.open()
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert not any(isinstance(e, Incident) for e in events)
    assert [e.retries_done for e in events if isinstance(e, InfraRetryScheduled)] == [0, 1]
    (halt,) = [e for e in events if isinstance(e, Halted)]
    assert halt.reason == "infrastructure_exhausted"
    assert halt.reason in RESUMABLE_HALTS
    ended = [e for e in events if isinstance(e, SessionEnded)]
    assert [(e.outcome, e.cause) for e in ended] == [("infrastructure", "api_error")] * 3
    assert [e.policy_limits_sha256 for e in ended] == [LIMITS, None, None]
    # The answered session's limits were judged; the missing ones are on the record as unjudged.
    assert ended[0].policy_limits_unjudged is None
    for e in ended[1:]:
        assert e.policy_limits_unjudged is not None
        assert "api_error" in e.policy_limits_unjudged
    # The same attempt throughout: nothing spent from the repair budget.
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1, 1]
    again = rig.open()
    assert again.resume().kind == "done"
    again.close()
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1, 1, 1]


def test_a_retry_no_model_answered_goes_on_to_a_session_that_merges(tmp_path: Path) -> None:
    _require_the_marker()
    dispatcher = FakeDispatcher(infra={1: "api_error"}, unanswered={1}, policy={2: LIMITS})
    rig = Rig(tmp_path, dispatcher=dispatcher, delays=(60.0,))
    _start_with_limits(rig, LIMITS)
    loop = rig.open()
    assert loop.run().kind == "done"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert not any(isinstance(e, Incident) for e in events)
    assert rig.slept == [60.0]


@pytest.mark.parametrize(
    ("baseline", "session", "infra", "unanswered"),
    [
        (None, LIMITS, True, True),
        (LIMITS, OTHER, True, True),
        (LIMITS, None, True, False),
        (LIMITS, None, False, True),
        (LIMITS, OTHER, False, False),
        (LIMITS, None, False, False),
        (None, LIMITS, False, False),
    ],
    ids=[
        "appeared-unanswered",
        "changed-unanswered",
        "missing-after-an-answered-api-error",
        "missing-after-a-completed-session-the-report-calls-unanswered",
        "changed-completed",
        "missing-completed",
        "appeared-completed",
    ],
)
def test_limits_that_appear_change_or_go_missing_after_an_answer_stay_an_incident(
    tmp_path: Path, baseline: str | None, session: str | None, infra: bool, unanswered: bool
) -> None:
    _require_the_marker()
    dispatcher = FakeDispatcher(
        infra={1: "api_error"} if infra else {},
        policy={1: session} if session is not None else {},
        unanswered={1} if unanswered else set(),
    )
    rig = Rig(tmp_path, dispatcher=dispatcher, delays=(60.0,))
    _start_with_limits(rig, baseline)
    loop = rig.open()
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed" and "policy limits" in incident.detail
    assert [e.reason for e in events if isinstance(e, Halted)] == ["incident"]
    (ended,) = [e for e in events if isinstance(e, SessionEnded)]
    assert ended.policy_limits_unjudged is None
    assert len(rig.dispatcher.requests) == 1  # no retry after an incident


def test_a_session_no_model_answered_under_no_limits_at_all_is_recorded_unjudged(
    tmp_path: Path,
) -> None:
    _require_the_marker()
    dispatcher = FakeDispatcher(infra={1: "api_error"}, unanswered={1})
    rig = Rig(tmp_path, dispatcher=dispatcher, delays=(60.0,))
    _start_with_limits(rig, None)
    loop = rig.open()
    assert loop.run().kind == "done"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert not any(isinstance(e, Incident) for e in events)
    first = next(e for e in events if isinstance(e, SessionEnded))
    assert first.policy_limits_unjudged is not None


# The marker, read from streams shaped as the binary writes them. The init line comes
# before any request, so a stream holding it and no model's answer never reached the API.
def _line(**fields: Any) -> str:  # noqa: ANN401 - the binary's own untyped events
    return json.dumps(fields)


INIT = _line(type="system", subtype="init", model=PINNED, session_id="s")
STATUS = _line(type="system", subtype="status", status="requesting", session_id="s")
DROPPED = _line(
    type="assistant",
    error="server_error",
    message={
        "id": "d2ae0ea7-0000-4000-8000-000000000000",
        "model": "<synthetic>",
        "role": "assistant",
        "content": [{"type": "text", "text": "API Error: Connection dropped (ECONNRESET)"}],
        "usage": {"input_tokens": 0, "output_tokens": 0},
    },
)
RESULT = _line(
    type="result",
    subtype="success",
    is_error=True,
    terminal_reason="api_error",
    num_turns=1,
    result="API Error: Connection dropped (ECONNRESET)",
    usage={"input_tokens": 0, "output_tokens": 0},
)
ANSWER = "\n".join(
    [
        _line(
            type="stream_event",
            event={
                "type": "message_start",
                "message": {"id": "msg_01", "model": PINNED, "usage": {"input_tokens": 2}},
            },
        ),
        _line(
            type="assistant",
            message={
                "id": "msg_01",
                "model": PINNED,
                "role": "assistant",
                "content": [{"type": "text", "text": "Reading the specification."}],
                "usage": {"input_tokens": 2, "output_tokens": 8},
            },
        ),
    ]
)


def _answered(stream: str) -> bool:
    marker = getattr(managed, "model_answered", None)
    if marker is None:
        pytest.fail("there is no reading of whether a model answered a session")
    _result, _usage, models = read_stream(stream)
    return bool(marker(models))


def test_a_stream_with_its_init_and_only_the_binary_s_own_error_was_answered_by_no_model() -> None:
    stream = "\n".join([INIT, STATUS, DROPPED, DROPPED, RESULT])
    assert not _answered(stream)
    result, _usage, _models = read_stream(stream)
    end = classify_session_end(result, exit_code=1, stopped_at_wall_clock=False)
    assert (end.outcome, end.cause) == ("infrastructure", "api_error")


def test_a_stream_a_model_answered_before_the_drop_was_answered() -> None:
    assert _answered("\n".join([INIT, STATUS, ANSWER, DROPPED, RESULT]))
    assert _answered("\n".join([INIT, ANSWER]))


@pytest.mark.parametrize(
    ("models", "answered"),
    [
        (frozenset(), False),
        (frozenset({"<synthetic>"}), False),
        (frozenset({PINNED}), True),
        (frozenset({"<synthetic>", PINNED}), True),
        (frozenset({"claude-sonnet-5"}), True),
    ],
    ids=["none", "only-the-binary-s-own", "the-pin", "both", "another-model"],
)
def test_only_a_model_s_own_message_counts_as_an_answer(
    models: frozenset[str], answered: bool
) -> None:
    marker = getattr(managed, "model_answered", None)
    if marker is None:
        pytest.fail("there is no reading of whether a model answered a session")
    assert marker(models) is answered


def test_an_end_line_may_name_unjudged_limits_only_for_an_infrastructure_end_with_none() -> None:
    _require_the_marker()
    base: dict[str, Any] = {
        "seq": 3,
        "ts": "2026-11-05T16:33:55.000000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "subtask_id": "s1",
        "attempt": 1,
        "session_id": "sess-2",
        "outcome": "infrastructure",
        "cause": "api_error",
        "attempt_commit": None,
        "trajectory": None,
        "worktree": None,
        "reading_verified": False,
        "policy_limits_unjudged": "no model answered the session",
    }
    assert SessionEnded.model_validate(base).policy_limits_unjudged is not None
    with pytest.raises(ValueError, match="unjudged"):
        SessionEnded.model_validate({**base, "policy_limits_sha256": LIMITS})
    completed = {
        **base,
        "outcome": "completed",
        "cause": None,
        "attempt_commit": "a" * 40,
        "trajectory": "t",
        "worktree": "w",
        "reading_verified": True,
    }
    with pytest.raises(ValueError, match="unjudged"):
        SessionEnded.model_validate(completed)
    # A line written before the field existed reads as judged.
    old = {k: v for k, v in base.items() if k != "policy_limits_unjudged"}
    assert SessionEnded.model_validate(old).policy_limits_unjudged is None
