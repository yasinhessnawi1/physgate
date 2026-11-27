"""A spawned session is open until a line of its own end follows its last spawn.

One rule, read by the dispatcher at a resume, by the raw arm's cap, by the trial assembler and by
the harness round: a role session ends by its end line or a leftover's read; a module review by
its verdict, why it has none, or its tokens and the halt or incident the loop writes with them;
the plan's review once its spawn's record beside the decomposition is gone. A spawn nothing ends
is open, whatever it was spawned for, and is named by what the records say of its kind.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from physgate.orchestrator.events import Event
from physgate.orchestrator.session_ends import (
    PLAN_REVIEW_SPAWN,
    OpenSession,
    ended_by,
    open_sessions,
    session_open,
    spawn_kind,
)

T0 = "2026-11-27T10:00:00.000000Z"
EVENT: TypeAdapter[Event] = TypeAdapter(Event)


def _log(*lines: dict[str, Any]) -> list[Event]:
    """The lines as the loop writes them, numbered in order: each read as a line of the log is."""
    return [
        EVENT.validate_json(
            json.dumps({"seq": i, "ts": T0, "run_id": "r", "gate_mode": "on", **line})
        )
        for i, line in enumerate(lines, start=1)
    ]


def _stage(stage: str) -> dict[str, Any]:
    return {"kind": "stage_entered", "subtask_id": "s", "attempt": 1, "stage": stage}


def _spawn(sid: str) -> dict[str, Any]:
    return {"kind": "session_spawned", "session_id": sid, "pid": 7, "started": "x"}


def _session_ended(sid: str) -> dict[str, Any]:
    return {
        "kind": "session_ended",
        "subtask_id": "s",
        "attempt": 1,
        "session_id": sid,
        "outcome": "completed",
        "cause": None,
        "attempt_commit": "a" * 40,
        "trajectory": f"sessions/{sid}/stdout.jsonl",
        "worktree": "worktrees/s",
        "reading_verified": True,
    }


def _tokens(sid: str, message_id: str, kind: str = "reviewer") -> dict[str, Any]:
    usage = {
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    return {
        "kind": "tokens_used",
        "attribution": f"{kind}:{sid}",
        "message_id": message_id,
        "usage": usage,
    }


def _review_ran(sid: str) -> dict[str, Any]:
    result = {
        "verdict": "pass",
        "finding": "sound",
        "reviewer_model": "claude-sonnet-5",
        "session_id": sid,
        "usage": [],
    }
    return {"kind": "review_ran", "subtask_id": "s", "attempt": 1, "result": result}


def _review_unavailable(sid: str) -> dict[str, Any]:
    return {
        "kind": "review_unavailable",
        "subtask_id": "s",
        "attempt": 1,
        "cause": "no_verdict",
        "detail": "no verdict",
        "retry": False,
        "session_id": sid,
        "reviewer_model": "claude-sonnet-5",
    }


def _halted(reason: str = "infrastructure_exhausted") -> dict[str, Any]:
    line: dict[str, Any] = {"kind": "halted", "reason": reason, "detail": "x"}
    if reason == "usage_limit":
        line["usage_limit"] = {"resets": "1:20pm (Europe/Oslo)"}
    return line


def _incident(cause: str) -> dict[str, Any]:
    return {"kind": "incident", "subtask_id": "s", "cause": cause, "detail": "x"}


def _leftover_read(sid: str) -> dict[str, Any]:
    return {
        "kind": "leftover_read",
        "session_id": sid,
        "stopped": True,
        "complete": True,
        "trajectory_seal": None,
    }


def _resumed() -> dict[str, Any]:
    return {"kind": "integration_gate_skipped", "reason": "nothing_planned", "subtasks": []}


REVIEW = [_stage("review"), _spawn("rev")]


@pytest.mark.parametrize(
    ("lines", "kind"),
    [
        (
            [_stage("spawn"), _spawn("rev"), _tokens("rev", "m", "session"), _session_ended("rev")],
            "role session",
        ),
        ([_stage("spawn"), _spawn("rev"), _leftover_read("rev")], "role session"),
        (
            [*REVIEW, _tokens("rev", "m1"), _tokens("rev", "m2"), _review_ran("rev")],
            "module review",
        ),
        ([*REVIEW, _tokens("rev", "m1"), _review_unavailable("rev")], "module review"),
        ([*REVIEW, _review_unavailable("rev")], "module review"),
        ([*REVIEW, _tokens("rev", "m1"), _halted("usage_limit")], "module review"),
        (
            [
                *REVIEW,
                _tokens("rev", "m1"),
                _incident("managed_settings_changed"),
                _halted("incident"),
            ],
            "module review",
        ),
        (
            [*REVIEW, _incident("held_out_read"), _tokens("rev", "m1"), _halted("incident")],
            "module review",
        ),
        ([*REVIEW, _spawn("rev"), _tokens("rev", "m1"), _review_ran("rev")], "module review"),
        (
            [*REVIEW, _halted("credential_refused"), _resumed(), _leftover_read("rev")],
            "module review",
        ),
        ([_spawn("rev"), _review_ran("rev")], "module review"),
    ],
    ids=[
        "a role session by its end line",
        "a role session by a leftover's read",
        "a review by its verdict, after its tokens",
        "a review by why it has no verdict",
        "a review with nothing spent by why it has no verdict",
        "a review whose try met the usage limit, by its tokens and the halt",
        "a review run under changed settings, by its tokens and the incident",
        "a review that showed held-out material, by its tokens and the halt",
        "a review's repair resume, by the verdict after its last spawn",
        "a review a resume read as a leftover",
        "a spawn the log gives no stage for, by a review's verdict",
    ],
)
def test_a_session_ends_by_a_line_of_its_own_end_after_its_last_spawn(
    lines: list[dict[str, Any]], kind: str
) -> None:
    events = _log(*lines)
    assert not session_open("rev", events)
    assert ended_by("rev", events) is not None
    assert spawn_kind("rev", events) == kind
    assert open_sessions(events) == ()


@pytest.mark.parametrize(
    ("lines", "named"),
    [
        ([_stage("spawn"), _spawn("rev"), _tokens("rev", "m", "session")], "role session"),
        (REVIEW, "module review"),
        ([*REVIEW, _tokens("rev", "m1"), _resumed()], "module review"),
        ([*REVIEW, _tokens("rev", "m1")], "module review"),
        ([*REVIEW, _review_ran("rev"), _spawn("rev")], "module review"),
        ([*REVIEW, _halted("credential_refused")], "module review"),
        (
            [_stage("gate"), _spawn("rev")],
            "session of a kind no end rule knows (spawned at the gate stage)",
        ),
        ([_spawn("rev")], "session of a kind no end rule knows (spawned before any stage)"),
        (
            [_stage("spawn"), _spawn("rev"), _review_ran("other"), _session_ended("other")],
            "role session",
        ),
    ],
    ids=[
        "a role session killed before its end line",
        "a review killed before it was back",
        "a review killed between its token lines, then a resume's line",
        "a review whose token lines are the log's last",
        "a review spawned again after its verdict",
        "a review whose try ended the run with nothing spent and no read since",
        "a spawn at a stage no rule spawns at",
        "a spawn before any stage",
        "a session whose id no end names",
    ],
)
def test_a_spawn_nothing_ends_is_open_and_named_by_its_kind(
    lines: list[dict[str, Any]], named: str
) -> None:
    events = _log(*lines)
    assert session_open("rev", events)
    assert ended_by("rev", events) is None
    assert open_sessions(events) == (OpenSession("rev", named),)


def test_a_session_never_spawned_is_not_open() -> None:
    events = _log(_stage("spawn"), _session_ended("rev"))
    assert not session_open("rev", events)
    assert open_sessions(events) == ()


def test_the_plan_s_review_is_open_while_its_spawn_s_record_is_there(tmp_path: Path) -> None:
    events = _log(_stage("spawn"), _spawn("role"), _session_ended("role"))
    assert open_sessions(events, tmp_path) == ()
    record = tmp_path / PLAN_REVIEW_SPAWN
    record.parent.mkdir()
    record.write_text(json.dumps({"session_id": "plan-rev-1", "pid": 7}))
    assert open_sessions(events, tmp_path) == (OpenSession("plan-rev-1", "plan review"),)
    record.write_text("{not json")
    assert open_sessions(events, tmp_path) == (
        OpenSession("(its spawn's record cannot be read)", "plan review"),
    )
