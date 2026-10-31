"""A re-planned run's opening holds every round, is replayed round by round, and holds on the last.

Each round before the last is a review that did not pass, re-planned within the run's budget:
replay takes its line before the plan the run starts from, holding on no item, and its tokens tied
to its own session. Only the last round's line may hold the run. The item it holds on carries every
round's verdict and links the held round's own stream, held to that round's seal: the link the
item's listing checks and the stream a release is checked against are the same.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of
from loop_fakes import plan, usage
from orch_helpers import CLEAN_HARNESS
from plan_hold_rig import (
    INSTALL,
    REVIEW_SESSION,
    SESSION,
    SPEC_COMMIT,
    again,
    decide,
    dispatched,
    kinds,
    layer,
    rig,
)
from plan_hold_rig import verdict as hold_verdict
from replan_rig import Step, decompose, round_dir, verdict

import physgate.orchestrator.record as record
from physgate.orchestrator.events import (
    DesignReviewRan,
    Event,
    RunStarted,
    TokensUsed,
    read_events,
    require_writable,
)
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.queue import read_queue, recorded_seal, statuses_now
from physgate.orchestrator.replay import RunState
from physgate.orchestrator.trajectory import seal


def _replayed(lines: list[Event]) -> Any:  # noqa: ANN401 - None, or the refusal
    return outcome_of(lambda: require_writable(lines, RunState()))


def _repaired(tmp_path: Path) -> list[Event]:
    ran = decompose(tmp_path, "repair:1", [Step(), Step()])
    assert ran.code == 0, ran.code
    return list(read_events(ran.run_dir / "events.jsonl"))


def test_a_re_planned_opening_replays_as_written(tmp_path: Path) -> None:
    log = _repaired(tmp_path)
    assert [e.kind for e in log].count("design_review_ran") == 2
    assert _replayed(log) is None


def _edited(log: list[Event], edit: str) -> list[Event]:
    found = [i for i, e in enumerate(log) if isinstance(e, DesignReviewRan)]
    assert len(found) == 2, [e.kind for e in log]
    first = found[0]
    review = log[first]
    assert isinstance(review, DesignReviewRan)
    changed = list(log)
    if edit == "held_early":
        changed[first] = review.model_copy(update={"held_item": "run-1-plan"})
    elif edit == "passed_early":
        changed[first] = review.model_copy(update={"result": verdict(1, "pass")})
    elif edit == "over_budget":
        opening = log[0]
        assert isinstance(opening, RunStarted)
        changed[0] = opening.model_copy(update={"design_review": "on"})
    elif edit == "tokens_elsewhere":
        spent = log[first - 1]
        assert isinstance(spent, TokensUsed) and spent.attribution == "reviewer:review-1"
        changed[first - 1] = spent.model_copy(update={"attribution": "reviewer:review-2"})
    return changed


@pytest.mark.parametrize("edit", ["held_early", "passed_early", "over_budget", "tokens_elsewhere"])
def test_replay_refuses_an_earlier_round_no_loop_writes(tmp_path: Path, edit: str) -> None:
    log = _repaired(tmp_path)
    assert _replayed(log) is None  # the log as written is taken: the edit alone is refused
    assert isinstance(_replayed(_edited(log, edit)), ValueError)


def test_a_held_round_s_item_links_its_own_stream_and_names_every_round_s_verdict(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "repair:1", [Step(), Step(review="blocked")])
    assert ran.code == 0, ran.code
    listed = read_queue(ran.run_dir).open_items()
    assert len(listed) == 1, listed
    item = listed[0]
    assert item.trajectories == ("decomposition/round-2/stdout.jsonl",)
    found = str(item.triggering_finding)
    assert f"round 1: fail: {verdict(1, 'fail').finding}" in found, found
    assert verdict(2, "blocked").finding in found, found
    assert found.index(verdict(1, "fail").finding) < found.index(verdict(2, "blocked").finding)
    assert statuses_now(ran.run_dir, item.item_id) == ("holds",)
    log = list(read_events(ran.run_dir / "events.jsonl"))
    first = seal((round_dir(ran.run_dir, 1) / "stdout.jsonl").read_bytes())
    assert recorded_seal(log, "decomposition/stdout.jsonl") == first
    (round_dir(ran.run_dir, 2) / "stdout.jsonl").write_text("{}\n")
    assert statuses_now(ran.run_dir, item.item_id) == ("tampered",)


def _stream(path: Path, k: int) -> Any:  # noqa: ANN401 - the stream's seal
    path.parent.mkdir(parents=True, exist_ok=True)
    message = {"id": f"m{k}", "model": "claude-sonnet-5", "content": []}
    path.write_text(json.dumps({"type": "assistant", "message": message, "round": k}) + "\n")
    return seal(path.read_bytes())


def _rig(run_dir: Path) -> Any:  # noqa: ANN401 - the plan hold's rig
    """The plan hold's rig, acting on decisions, over a reportable ``repair:1`` run."""
    the_rig = rig(run_dir, design_review="repair:1")
    the_rig.config_overrides |= {"reportable": True, "harness": CLEAN_HARNESS}
    return the_rig


def _held_at_round_two(run_dir: Path) -> Path:
    """A run under ``on`` rules held on round 2's review, round 1 re-planned before it."""
    the_rig = _rig(run_dir)
    loop = the_rig.open()
    earlier = getattr(record, "EarlierRound", None)
    assert earlier is not None, "the record has no earlier round"
    first = _stream(run_dir / "decomposition" / "stdout.jsonl", 1)
    second = _stream(run_dir / "decomposition" / "round-2" / "stdout.jsonl", 2)

    def reviewed(sealed: Any, session: str, message: str) -> Any:  # noqa: ANN401
        result = hold_verdict("fail").model_copy(update={"session_id": session})
        return record.PlanReviewed.model_validate(
            {
                "install": INSTALL,
                "stream_seal": sealed,
                "session_id": session,
                "usage": (MessageUsage(message_id=message, usage=usage(5)),),
                "result": result,
            }
        )

    call = record.DecompositionCall
    from journal_helper import plan_digest, rounds

    first_review = reviewed(first, REVIEW_SESSION, "r1")
    second_review = reviewed(second, f"{REVIEW_SESSION}-2", "r2")
    first_call = (MessageUsage(message_id="d1", usage=usage(10)),)
    second_call = (MessageUsage(message_id="d2", usage=usage(9)),)
    proposals = rounds(
        run_dir,
        [
            (SESSION, b"round 1's plan", first_review, first_call),
            (f"{SESSION}-2", b"round 2's plan", second_review, second_call),
        ],
        design_review="repair:1",
    )
    loop.record.start(
        plan("s1", "s2"),
        proposals=proposals,
        call=call(session_id=f"{SESSION}-2", usage=second_call),
        decomposed=record.DecompositionSummary(
            session_id=f"{SESSION}-2",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=2,
            interface_nodes=("iface.bus",),
            spec_commit=SPEC_COMMIT,
            head_revision=1,
            plan_sha256=plan_digest(b"round 2's plan"),
        ),
        reviewed=second_review,
        earlier=(
            earlier(
                call=call(session_id=SESSION, usage=first_call),
                reviewed=first_review,
                plan_sha256=plan_digest(b"round 1's plan"),
            ),
        ),
    )
    layer(loop)
    loop.close()
    assert again(the_rig) == "wait"
    return run_dir


@pytest.mark.parametrize("changed", [None, "round-2"])
def test_a_release_of_a_held_later_round_is_checked_against_that_round_s_stream(
    tmp_path: Path, changed: str | None
) -> None:
    run_dir = _held_at_round_two(tmp_path / "run")
    decide(run_dir, "approve")
    if changed is not None:
        (run_dir / "decomposition" / changed / "stdout.jsonl").write_text("{}\n")
    again(_rig(run_dir))
    if changed is None:
        assert "stage_entered" in dispatched(run_dir), kinds(run_dir)
        assert "incident" not in kinds(run_dir)
    else:
        assert dispatched(run_dir) == [], kinds(run_dir)
        assert "incident" in kinds(run_dir)


def test_an_opening_cut_after_an_earlier_round_and_before_the_plan_is_refused(
    tmp_path: Path,
) -> None:
    from physgate.orchestrator.exceptions import RunStateError
    from physgate.orchestrator.record import RunRecord
    from physgate.orchestrator.run_config import load_run_config

    ran = decompose(tmp_path, "repair:1", [Step(), Step()])
    assert ran.code == 0, ran.code
    raw = (ran.run_dir / "events.jsonl").read_text().splitlines(keepends=True)
    first = next(i for i, one in enumerate(raw) if '"design_review_ran"' in one)
    # Killed after round 1's review line, before round 2's tokens and the plan the run starts from.
    (ran.run_dir / "events.jsonl").write_text("".join(raw[: first + 1]))
    for later in ("ledger.jsonl", "queue.jsonl"):  # written after the plan, so not yet there
        (ran.run_dir / later).unlink()
    config = load_run_config(ran.run_dir / "run.json")
    found = outcome_of(lambda: RunRecord(config, ran.run_dir))
    assert isinstance(found, RunStateError), found
    assert "cut before its review" in str(found), str(found)
