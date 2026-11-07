"""A decomposition call whose output its schema refused is made once more, and both are recorded.

A live run lost its first step to one malformed answer: the call's structured output was refused
by its schema ("/system_requirements: must be array"), and the run halted ``decomposition_failed``
eight minutes in. A transient output error is no defect of the brief. So such a call is made
exactly once more, inside the same round: the round's number, its review and the budget of
re-plans are the round's as before. Both calls are on the record, each with its own tokens:

- in a run that reviews its plan, each call's proposal line, the first naming the refusal and the
  second marked as the round's second call, and a line in the round journal for the refused call;
- in a run that does not, a line of its own between the two calls' tokens.

The run halts only when the second call is refused too, and no call is made a third time. No
other failure is retried. The replay takes a second call only after its round's refused first,
and a retry line only once, before the plan, in a run that does not review its plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from replan_rig import Step, decompose, events, journal, round_dir

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.replay import replay

REFUSED = "schema_refused"


def _kinds(run_dir: Path) -> list[str]:
    return [one["kind"] for one in events(run_dir)]


def _opening(run_dir: Path) -> list[tuple[str, str]]:
    """The opening's tokens and lines up to the plan or the halt, by kind and session."""
    found = []
    for one in events(run_dir):
        if one["kind"] in ("decomposed", "halted"):
            found.append((one["kind"], one.get("session_id", one.get("reason", ""))))
            break
        if one["kind"] == "tokens_used":
            found.append(("tokens", one["attribution"].removeprefix("decomposition:")))
        elif one["kind"] in ("decomposition_retried", "plan_proposed"):
            found.append((one["kind"], one["session_id"]))
    return found


def _sessions(ran: Any) -> list[str]:  # noqa: ANN401 - the rig's run
    return [call["session_id"] for call in ran.script.calls]


# ── a run that does not review its plan ──────────────────────────────────────


def test_a_refused_call_is_made_once_more_and_the_run_starts_from_the_second(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "off", [Step(call=REFUSED), Step()])
    assert len(ran.script.calls) == 2, "the refused call was not made again"
    assert ran.code == 0, ran.err
    first, second = _sessions(ran)
    assert first != second
    # The second call runs in a directory of its own: the first's stream and settings stay.
    assert ran.script.calls[1]["workdir"] == round_dir(ran.run_dir, 1) / "retry"
    assert _opening(ran.run_dir) == [
        ("tokens", first),
        ("decomposition_retried", first),
        ("tokens", second),
        ("decomposed", second),
    ]
    (retried,) = [e for e in events(ran.run_dir) if e["kind"] == "decomposition_retried"]
    assert retried["cause"] == REFUSED
    log = read_events(ran.run_dir / "events.jsonl")
    assert TokenAccount.from_events(log).decomposition_invocations() == 2
    replay(log)


def test_a_call_refused_twice_halts_the_run_and_none_is_made_a_third_time(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "off", [Step(call=REFUSED), Step(call=REFUSED), Step()])
    assert len(ran.script.calls) == 2
    assert ran.code == 1
    first, second = _sessions(ran)
    assert _opening(ran.run_dir) == [
        ("tokens", first),
        ("decomposition_retried", first),
        ("tokens", second),
        ("halted", "decomposition_failed"),
    ]
    assert events(ran.run_dir)[-1]["detail"].startswith(f"{REFUSED}: ")
    replay(read_events(ran.run_dir / "events.jsonl"))


@pytest.mark.parametrize("cause", ["invalid_plan", "no_structured_output", "wall_clock"])
def test_no_other_failure_is_made_again(tmp_path: Path, cause: str) -> None:
    ran = decompose(tmp_path, "off", [Step(call=cause), Step()])
    assert len(ran.script.calls) == 1
    assert ran.code == 1
    assert "decomposition_retried" not in _kinds(ran.run_dir)


# ── a run that reviews its plan ──────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["observe", "on"])
def test_a_round_s_refused_call_is_made_once_more_inside_the_round(
    tmp_path: Path, mode: str
) -> None:
    ran = decompose(tmp_path, mode, [Step(call=REFUSED), Step(review="pass")])
    assert len(ran.script.calls) == 2, "the refused call was not made again"
    assert ran.code == 0, ran.err
    first, second = _sessions(ran)
    assert ran.script.calls[1]["workdir"] == round_dir(ran.run_dir, 1) / "retry"
    proposed = [e for e in events(ran.run_dir) if e["kind"] == "plan_proposed"]
    assert [(p["round"], p["session_id"], p.get("call"), p.get("cause")) for p in proposed] == [
        (1, first, None, REFUSED),
        (1, second, 2, None),
    ]
    assert _opening(ran.run_dir)[:4] == [
        ("tokens", first),
        ("plan_proposed", first),
        ("tokens", second),
        ("plan_proposed", second),
    ]
    lines = [(one["kind"], one.get("session_id")) for one in journal(ran.run_dir)]
    assert lines[:3] == [("round_started", first), ("call_refused", first), ("round_ended", second)]
    (refused,) = [one for one in journal(ran.run_dir) if one["kind"] == "call_refused"]
    assert refused["retry_session_id"] == second
    replay(read_events(ran.run_dir / "events.jsonl"))


def test_a_round_refused_twice_fails_the_decomposition_with_both_calls_proposed(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "on", [Step(call=REFUSED), Step(call=REFUSED), Step()])
    assert len(ran.script.calls) == 2
    assert ran.code == 1
    proposed = [e for e in events(ran.run_dir) if e["kind"] == "plan_proposed"]
    assert [(p.get("call"), p.get("cause")) for p in proposed] == [(None, REFUSED), (2, REFUSED)]
    assert events(ran.run_dir)[-1]["reason"] == "decomposition_failed"
    replay(read_events(ran.run_dir / "events.jsonl"))


def test_a_later_round_s_refused_call_is_made_again_without_spending_a_re_plan(
    tmp_path: Path,
) -> None:
    # Round 1 is not passed and re-planned; round 2's first call is refused and made again, and
    # its second call's plan is reviewed as round 2's.
    ran = decompose(tmp_path, "repair:1", [Step(), Step(call=REFUSED), Step(review="pass", said=2)])
    assert len(ran.script.calls) == 3
    assert ran.code == 0, ran.err
    proposed = [e for e in events(ran.run_dir) if e["kind"] == "plan_proposed"]
    assert [(p["round"], p.get("call")) for p in proposed] == [(1, None), (2, None), (2, 2)]
    assert ran.script.calls[2]["workdir"] == round_dir(ran.run_dir, 2) / "retry"
    replay(read_events(ran.run_dir / "events.jsonl"))


# ── the replay ───────────────────────────────────────────────────────────────


def test_the_replay_refuses_a_retry_line_the_record_does_not_support(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "off", [Step(call=REFUSED), Step()])
    log = read_events(ran.run_dir / "events.jsonl")
    at = [i for i, e in enumerate(log) if e.kind == "decomposition_retried"]
    assert len(at) == 1, "no retry line"
    line = log[at[0]]
    planned = next(i for i, e in enumerate(log) if e.kind == "decomposed")
    for forged in (
        [*log[: at[0] + 1], line.model_copy(update={"seq": line.seq + 1}), *log[at[0] + 1 :]],
        [*log[: planned + 1], line, *log[planned + 1 :]],
    ):
        with pytest.raises(CorruptEventLogError):
            replay(forged)
    # And in a run that reviews its plan, where the proposal lines say it.
    reviewed = decompose(tmp_path / "reviewed", "on", [Step(review="pass")])
    shown = read_events(reviewed.run_dir / "events.jsonl")
    started = next(i for i, e in enumerate(shown) if e.kind == "plan_proposed")
    with pytest.raises(CorruptEventLogError):
        replay([*shown[:started], line, *shown[started:]])


def test_the_replay_refuses_a_second_call_after_no_refused_first(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "on", [Step(call=REFUSED), Step(review="pass")])
    log = read_events(ran.run_dir / "events.jsonl")
    at = [i for i, e in enumerate(log) if e.kind == "plan_proposed"]
    assert len(at) == 2, "the round did not propose twice"
    first, second = (log[i] for i in at)
    for forged in (
        # The first call's own failure was not a refusal by its schema.
        [*log[: at[0]], first.model_copy(update={"cause": "invalid_plan"}), *log[at[0] + 1 :]],
        # A second call with no first before it.
        [*log[: at[0]], *log[at[0] + 1 :]],
        # A third call.
        [*log[: at[1] + 1], second.model_copy(update={"session_id": "again"}), *log[at[1] + 1 :]],
    ):
        with pytest.raises(CorruptEventLogError):
            replay(forged)
