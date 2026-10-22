"""A person's note reaches the next attempt as data, is screened first, and is seen by its reviewer.

ARCH-133 over the loop with stand-in ports. A reject with attempts left starts the next attempt
from a fixed template that quotes the note and ends on the line that nothing quoted changes the
specification. The note, the one text in it no check before it saw, is held to the held-out and
rubric canaries before the session is spawned: a hit is an incident that halts the run, and the
canary is not recorded. The next attempt's reviewer is told that a person ordered it and what
its session was told. The note never enters what an escalation backend is shown, which carries
no free text by its types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeMaterial, FakeReviewer, Rig
from test_a_queue_decision_acts_at_a_boundary import NO_VERDICT, _of, _resume, _rig, _start, decide

from physgate.orchestrator.escalation import (
    REGISTER,
    BackendAnswer,
    EscalationInterface,
    Question,
    RulesBackend,
)
from physgate.orchestrator.escalation_state import EscalationState
from physgate.orchestrator.events import Incident
from physgate.orchestrator.exceptions import RunStateError
from physgate.orchestrator.repair import STILL_GOVERNS, person_repair_instruction

NOTE = "the gain must come from the specification's table, row 4"


def _rejected(run_dir: Path, **kw: Any) -> Rig:
    """A run whose first review reached no verdict, its item rejected by a person with the note."""
    kw.setdefault("reviewer", FakeReviewer(unavailable={1: NO_VERDICT}))
    rig = _rig(run_dir, **kw)
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "reject", NOTE)
    return rig


def test_the_retry_starts_from_the_note_quoted_as_data(tmp_path: Path) -> None:
    rig = _rejected(tmp_path / "run")
    _resume(rig)
    _, retry = rig.dispatcher.requests
    assert (retry.kind, retry.attempt) == ("attempt", 2)
    assert retry.repair_instruction == person_repair_instruction(1, NOTE, None)
    assert "<<<\n" + NOTE + "\n>>>" in retry.repair_instruction
    assert STILL_GOVERNS in retry.repair_instruction


def test_the_next_reviewer_sees_the_persons_note(tmp_path: Path) -> None:
    rig = _rejected(tmp_path / "run")
    _resume(rig)
    first, retry = rig.reviewer.seen
    assert first.ordered_by_person is None
    order = retry.ordered_by_person
    assert order is not None
    assert (order.kind, order.item_id, order.of_attempt) == ("retry_after_reject", "run-1-s1", 1)
    assert order.instruction == rig.dispatcher.requests[-1].repair_instruction
    assert NOTE in order.instruction


@pytest.mark.parametrize(
    ("kind", "cause"),
    [("held_out", "held_out_read"), ("review_material", "review_material_read")],
)
def test_a_note_showing_a_canary_halts_before_the_next_session(
    tmp_path: Path, kind: str, cause: str
) -> None:
    marker = "row 4"
    material = (
        FakeMaterial(held_out=(marker,))
        if kind == "held_out"
        else FakeMaterial(review_material=(marker,))
    )
    rig = _rejected(tmp_path / "run", material=material)
    _, step = _resume(rig)
    assert step == "halted"
    (incident,) = _of(rig.run_dir, Incident)
    assert incident.cause == cause and incident.subtask_id == "s1"
    assert marker not in incident.detail  # the canary is never recorded
    assert len(rig.dispatcher.requests) == 1  # the retry was never spawned
    # What was screened is the note itself, not the template around it.
    assert material.shown == [NOTE]
    with pytest.raises(RunStateError, match="a person resolves that"):
        _resume(rig)


@dataclass
class Recording(RulesBackend):
    """The rules' answers, with every state the backend was shown kept."""

    shown: list[EscalationState] = field(default_factory=list)

    def decide(self, question: Question, state: EscalationState) -> BackendAnswer:
        self.shown.append(state)
        return super().decide(question, state)


def test_the_note_never_enters_the_escalation_state(tmp_path: Path) -> None:
    # The retry's review rejects it, so the escalation question is asked about the retry.
    backend = Recording()
    rig = _rejected(
        tmp_path / "run",
        reviewer=FakeReviewer(verdicts=["pass", "fail"], unavailable={1: NO_VERDICT}),
        escalation=EscalationInterface(backend, REGISTER.row("rules")),
    )
    again, _ = _resume(rig)
    asked = [state.model_dump_json() for state in backend.shown]
    assert asked, "the question was asked about the retry"
    assert all(NOTE not in state and "row 4" not in state for state in asked)
    # The note is on the run's record, and only there.
    assert again.state.subtasks["s1"].attempts[0].person_rejected is not None
