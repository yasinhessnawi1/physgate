"""A subtask the escalation decision sends to a person with attempts left reaches the queue.

ARCH-131: a confidence below 0.8 goes to the approval queue whatever the answer, and any
backend may send an attempt there by answering yes. Where no rule forced it (a rejection
with attempts left), the item is one of its own: it says which backend sent it and why,
names the finding and links the trajectory of every attempt made so far, and no further
attempt is dispatched. The rules binding never does this, so these runs ask a stand-in
backend registered for the length of the test; the rules' runs are held to the queue as
it was by the recording of every escalation path.
"""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest
from escalation_states import register_stand_in, stand_in
from loop_fakes import FakeGate, FakeReviewer, Rig, plan

from physgate.orchestrator.escalation import TO_THE_QUEUE, Decision
from physgate.orchestrator.events import AttemptRejected, Escalated, EscalationDecided, read_events
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.queue import QueueSource, decided_item, read_queue
from physgate.orchestrator.repair import Finding
from physgate.orchestrator.replay import replay

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _stand_in_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    register_stand_in(monkeypatch)


def run(tmp_path: Path, answer: str, confidence: float, **rig: object) -> Rig:
    built = Rig(
        tmp_path,
        escalation=stand_in(answer, confidence),
        config_overrides={"escalation_backend": "stand_in"},
        **rig,  # type: ignore[arg-type]
    )
    loop = built.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    return built


def test_a_confidence_below_the_floor_sends_the_first_rejection_to_the_queue(
    tmp_path: Path,
) -> None:
    rig = run(tmp_path, "no", 0.5, reviewer=FakeReviewer(verdicts=["fail", "pass"]))
    events = read_events(tmp_path / "events.jsonl")
    (decided,) = [e for e in events if isinstance(e, EscalationDecided)]
    assert (decided.attempt, decided.decision.basis) == (1, "floor")
    (item,) = read_queue(tmp_path).items
    assert item.source == "escalation_decision"
    assert item.subtask_id == "s1" and item.item_id == "run-1-s1"
    assert "stand_in" in item.decision_required
    assert "confidence, 0.5, is below 0.8" in item.decision_required
    assert "attempt 1 of 3" in item.decision_required
    (rejected,) = [e for e in events if isinstance(e, AttemptRejected)]
    assert item.triggering_finding == rejected.finding.text
    assert len(item.trajectories) == 1
    assert len(rig.dispatcher.requests) == 1  # no second attempt was dispatched
    (escalated,) = [e for e in events if isinstance(e, Escalated)]
    assert escalated.item_id == item.item_id
    assert replay(events).subtasks["s1"].status == "escalated"


def test_a_yes_on_the_second_rejection_sends_both_attempts_to_the_queue(tmp_path: Path) -> None:
    # Answer yes, but only from the second ask: the first decision lets the run go on.
    class YesOnSecond:
        def __init__(self) -> None:
            self.asked = 0

        def decide(self, question: object, state: object) -> object:
            from physgate.orchestrator.escalation import BackendAnswer  # noqa: PLC0415

            self.asked += 1
            return BackendAnswer(answer="yes" if self.asked == 2 else "no", confidence=1.0)

    from escalation_states import STAND_IN  # noqa: PLC0415

    from physgate.orchestrator.escalation import EscalationInterface  # noqa: PLC0415

    rig = Rig(
        tmp_path,
        gate=FakeGate(verdicts=["fail", "fail"]),
        escalation=EscalationInterface(YesOnSecond(), STAND_IN),  # type: ignore[arg-type]
        config_overrides={"escalation_backend": "stand_in"},
    )
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    bases = [e.decision.basis for e in events if isinstance(e, EscalationDecided)]
    assert bases == [None, "answer"]
    (item,) = read_queue(tmp_path).items
    assert item.source == "escalation_decision"
    assert (
        "it answered yes" in item.decision_required and "attempt 2 of 3" in item.decision_required
    )
    assert len(item.trajectories) == 2
    assert item.quantities  # the gate's finding carries its quantities
    assert len(rig.dispatcher.requests) == 2


def test_a_confident_no_lets_the_subtask_go_on_to_its_next_attempt(tmp_path: Path) -> None:
    rig = run(tmp_path, "no", 0.9, reviewer=FakeReviewer(verdicts=["fail", "pass"]))
    events = read_events(tmp_path / "events.jsonl")
    assert [e.decision.basis for e in events if isinstance(e, EscalationDecided)] == [None]
    assert not read_queue(tmp_path).items
    assert len(rig.dispatcher.requests) == 2
    assert replay(events).subtasks["s1"].status == "done"


def test_the_third_rejection_is_still_the_exhausted_budget_s_item(tmp_path: Path) -> None:
    run(tmp_path, "no", 0.9, reviewer=FakeReviewer(verdicts=["fail"] * 3))
    (item,) = read_queue(tmp_path).items
    assert item.source == "repair_budget_exhausted"


def _decision(**changes: object) -> Decision:
    fields: dict[str, object] = {
        "question": TO_THE_QUEUE,
        "answer": "no",
        "confidence": 0.5,
        "backend_id": "stand_in",
        "backend_version": "s/1",
        "latency_ms": 0.0,
        "forced": False,
        "basis": "floor",
    }
    return Decision.model_validate(fields | changes)


def _item(decision: Decision, attempts: int = 1) -> object:
    return decided_item(
        item_id="r-s1",
        run_id="r",
        subtask_id="s1",
        decision=decision,
        findings=tuple(Finding(source="review", text=f"f{i}") for i in range(attempts)),
        artefact_diff="",
        trajectories=tuple(f"t{i}" for i in range(attempts)),
        ts="2026-10-11T00:00:00.000000Z",
    )


def test_the_item_is_made_only_for_a_decision_that_was_not_forced() -> None:
    assert _item(_decision())
    assert _item(_decision(answer="yes", confidence=1.0, basis="answer"), attempts=2)
    with pytest.raises(QueueError):
        _item(_decision(answer="yes", confidence=1.0, forced=True, basis="forced"))
    with pytest.raises(QueueError):
        _item(_decision(confidence=0.9, basis=None))


@pytest.mark.parametrize("attempts", [0, 3])
def test_the_item_holds_the_attempts_made_so_far_and_never_an_exhausted_budget(
    attempts: int,
) -> None:
    with pytest.raises(QueueError):
        _item(_decision(), attempts=attempts)


def test_the_operator_interface_knows_every_queue_source() -> None:
    # The interface refuses a source its list does not hold, and must name each in words.
    text = (ROOT / "ui" / "src" / "api" / "queue.ts").read_text()
    listed = re.search(r"export const SOURCES = \[(.*?)\] as const;", text, re.DOTALL)
    assert listed is not None
    assert re.findall(r'"([a-z_]+)"', listed.group(1)) == list(typing.get_args(QueueSource))
    labels = (ROOT / "ui" / "src" / "words" / "queue.ts").read_text()
    entry = r"{source}: {{\n    kind: \"[^\"]+\",\n    why: \"[^\"]+\","
    for source in typing.get_args(QueueSource):
        assert re.search("\n  " + entry.format(source=source), labels), source
