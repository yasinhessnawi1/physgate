"""Where a decision's record cannot vouch for it, the decision is refused, never let through.

Each test here is a path that let a decision through when the record did not support it:

- the indicator rule read the history from what an attempt still remembers, and a resumed
  attempt forgets its review, so an indicator a review confirmed before a kill was lost;
- a ``decision_taken`` line that did not act was not checked at all, so a held line could
  claim a merge the record forbids, and free text could claim an effect;
- a reject that acts was not held to the attempt and commit it names;
- a decision with a verb could name no digest;
- the effect function took a decision on one item together with another item, and an
  integration item the run never escalated;
- whether a decision was held, and what the scan found, defaulted to "not held" and "nothing"
  when a caller left them out.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from decision_rig import CONFIRMED, DIGEST, TS, decide, escalated, review
from loop_fakes import FakeDispatcher, FakeReviewer, KilledError, Rig, failing_gate_result, plan

from physgate.orchestrator.decisions import (
    decision_effect,
    item_consequence,
    source_of,
)
from physgate.orchestrator.exceptions import QueueItemMismatchError, ReviewUnavailableError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import QueueResolution, integration_item, unavailable_item


def test_an_indicator_confirmed_before_a_kill_stays_in_the_history_after_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    rig = Rig(
        run,
        dispatcher=FakeDispatcher(trajectories=run / "sessions"),
        reviewer=FakeReviewer(results={1: review("fail", 1, indicators=CONFIRMED)}),
    )
    loop = rig.open()
    loop.start(plan("s1"))
    real_reject = Loop._reject

    def killed(self: Loop, subtask_id: str, attempt: int, finding: object) -> None:
        raise KilledError

    # Killed after the review that confirmed the indicator was written, before its rejection.
    monkeypatch.setattr(Loop, "_reject", killed)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    monkeypatch.setattr(Loop, "_reject", real_reject)
    rig.reviewer = FakeReviewer(
        unavailable={1: ReviewUnavailableError("no verdict", cause="invalid_verdict")}
    )
    again = rig.open()
    again.resume()
    sub = again.state.subtasks["s1"]
    assert sub.status == "escalated" and sub.attempts[-1].review is None
    consequence = item_consequence(again.state, "s1", source=source_of(sub), scan_hits=())
    assert consequence.why_record_only == "indicator_in_history"
    assert [(c.attempt, c.kind) for c in consequence.confirmed_indicators] == [
        (1, "disabled_checks")
    ]


@pytest.mark.parametrize(
    ("scenario", "verb", "override"),
    [
        # Held, so not acting yet, but claiming the merge the gate failure forbids.
        (
            "gate_exhausted",
            "approve",
            {"effect": "merge", "acts": False, "why_not": "held_os_layer_off"},
        ),
        # Not acting, giving a reason the record does not give.
        ("gate_exhausted", "approve", {"why_not": "indicator_in_history"}),
        # Free text claiming an effect.
        ("unavailable", None, {"effect": "merge", "acts": False, "why_not": "not_bound"}),
        # Free text claiming to be held, so a confirmation could later make it act.
        ("unavailable", None, {"effect": "none", "acts": False, "why_not": "held_os_layer_off"}),
        # A verb with no digest shown.
        ("unavailable", "approve", {"shown_sha256": None}),
        # A reject that acts, on another attempt than the one waiting.
        ("unavailable", "reject", {"attempt": 2}),
        # A scan hit claimed where the record alone forbids the merge anyway.
        ("gate_exhausted", "approve", {"effect": "none", "acts": False, "why_not": "scan_hit"}),
    ],
    ids=[
        "held line claiming a forbidden merge",
        "a reason the record does not give",
        "free text claiming an effect",
        "free text claiming to be held",
        "a verb with no digest",
        "a reject naming another attempt",
        "a scan hit where nothing could merge",
    ],
)
def test_a_line_the_record_cannot_vouch_for_is_refused(
    tmp_path: Path, scenario: str, verb: str | None, override: dict[str, object]
) -> None:
    loop = escalated(tmp_path, scenario)
    size = (loop.run_dir / "events.jsonl").stat().st_size
    with pytest.raises(ValueError):
        decide(loop, verb, **override)  # type: ignore[arg-type]
    assert (loop.run_dir / "events.jsonl").stat().st_size == size


def test_a_held_decision_the_record_allows_is_taken_and_its_confirmation_acts(
    tmp_path: Path,
) -> None:
    loop = escalated(tmp_path, "unavailable")
    held = decide(loop, "approve", note=None, acts=False, why_not="held_os_layer_off")
    assert loop.state.subtasks["s1"].status == "escalated"
    decide(loop, "approve", note=None, confirmed_by="operator", decision_offset=0)
    assert held.effect == "merge"
    assert loop.state.subtasks["s1"].attempts[-1].approved is not None


def _resolution(item_id: str) -> QueueResolution:
    return QueueResolution(
        item_id=item_id,
        ts=TS,
        decision="approve",
        resolved_by="yasin",
        verb="approve",
        note=None,
        shown_sha256=DIGEST,
    )


def test_the_effect_of_a_decision_on_another_item_is_a_mismatch(tmp_path: Path) -> None:
    loop = escalated(tmp_path, "unavailable")
    sub = loop.state.subtasks["s1"]
    item = unavailable_item(
        item_id=str(sub.queue_item),
        run_id="run-1",
        subtask_id="s1",
        attempt=1,
        source="review_unavailable",
        cause="invalid_verdict",
        detail="no verdict",
        spec_defects=(),
        artefact_diff="diff",
        trajectory="sessions/sess-1/stdout.jsonl",
        ts=TS,
        consequence=item_consequence(loop.state, "s1", source=source_of(sub), scan_hits=()),
    )
    with pytest.raises(QueueItemMismatchError, match="another item"):
        decision_effect(
            loop.state, item, _resolution("run-1-s9"), line_sha256=DIGEST, scan_hits=(), held=False
        )


def test_an_integration_item_the_run_never_escalated_is_a_mismatch(tmp_path: Path) -> None:
    loop = escalated(tmp_path, "unavailable")
    item = integration_item(
        item_id="run-1-integration",
        run_id="run-1",
        result=failing_gate_result("on"),
        run_span=("0" * 40, "1" * 40),
        trajectories=("sessions/sess-1/stdout.jsonl",),
        ts=TS,
        consequence=item_consequence(
            loop.state, "integration", source="gate_escalation", scan_hits=()
        ),
    )
    with pytest.raises(QueueItemMismatchError, match="no such integration item"):
        decision_effect(
            loop.state,
            item,
            _resolution("run-1-integration"),
            line_sha256=DIGEST,
            scan_hits=(),
            held=False,
        )


@pytest.mark.parametrize(
    ("function", "names"),
    [(decision_effect, ("scan_hits", "held")), (item_consequence, ("scan_hits",))],
    ids=["decision_effect", "item_consequence"],
)
def test_whether_a_decision_is_held_and_what_the_scan_found_are_never_defaulted(
    function: object, names: tuple[str, ...]
) -> None:
    parameters = inspect.signature(function).parameters  # type: ignore[arg-type]
    for name in names:
        assert parameters[name].default is inspect.Parameter.empty, name
