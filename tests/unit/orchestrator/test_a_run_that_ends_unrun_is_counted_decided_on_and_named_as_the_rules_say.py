"""A run that ends ``unrun`` is an ended run: counted, decided on at its end, and named exactly.

Control is reopened by a person's choice on a failed contract, which supersedes the other item on
the contract of control with electrical; drive2, whose design firmware2 builds, is rejected with
no attempt left, so firmware2 is held for good. The run ends ``unrun`` naming firmware2 alone: not
integration's own subtask, which the integration call's skip leaves planned, and only in a run
that acts and began under ``release_2``. The token total of the run is given as for any ended
run, and a decision a person writes on the superseded item after the end is taken at that end,
where nothing else is owed, without ending the run another way.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from loop_fakes import Rig
from test_a_choice_on_a_failed_contract_reopens_the_other_module import choose, of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_queue_decision_acts_at_a_boundary import decide
from wait_cycle_rig import (
    CONTROL,
    CONTROL2,
    ELECTRICAL,
    FIRMWARE,
    FIRMWARE2,
    Shape,
    first_run,
    resumed,
)

from physgate import roles
from physgate.evaluation.per_role.arms.compare import ENDED_STEPS, harness_total
from physgate.orchestrator import record
from physgate.orchestrator.events import read_events
from physgate.orchestrator.queue import read_queue
from physgate.orchestrator.replay import RunState, replay
from physgate.orchestrator.wait_cycle import never_ran, never_ran_at
from physgate.orchestrator.waiting import printed_step

#: The sign-off rule table a run starts under, as the code holds it (a row below owes a sign-off).
SIGN_OFF_RULES = record.SIGN_OFF_RULES
FIRST, SECOND = "run-1-contract-1", "run-1-contract-2"
DESIGNER_ITEM = "run-1-drive2-1a2b3c"
SIGN_OFF = "run-1-SIGNOFF-drive-0a1b2c"
SECOND_ROUND = "run-1-contract-1-r2"
INTEGRATION = "integ"


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    monkeypatch.setattr(record, "SIGN_OFF_RULES", None)  # a row about the end, not a sign-off


def ended(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Rig, Shape, str]:
    """The run described above, until it stops with the superseded item still open to decide."""
    shape = Shape(
        order=(CONTROL, FIRMWARE, ELECTRICAL, CONTROL2, FIRMWARE2),
        reads=((FIRMWARE, CONTROL), (ELECTRICAL, CONTROL)),
        design=((CONTROL2, FIRMWARE2),),
        closing=False,
    )
    # control, firmware and electrical pass review; drive2's three attempts fail; the rest pass.
    rig = shape.rig(tmp_path, ("pass", "pass", "pass", "fail", "fail", "fail", "pass", "pass"))
    for made in rig.diff.writes[CONTROL]:  # type: ignore[attr-defined]
        for quantity in made["quantities"].values():
            quantity["value"] = 13
    assert first_run(rig, monkeypatch, shape) == "wait"
    choose(rig.run_dir, "producer", item_id=FIRST)  # reopens control: the second item lapses
    decide(rig.run_dir, "reject", "no attempt is left", item_id=DESIGNER_ITEM)
    assert resumed(rig, monkeypatch, shape) == "wait"
    decide(rig.run_dir, "approve", "it is fine", item_id="run-1-contract-1-r2")
    decide(rig.run_dir, "approve", "it is fine", item_id="run-1-contract-2-r2")
    step = resumed(rig, monkeypatch, shape)
    return rig, shape, step


def state_of(rig: Rig) -> RunState:
    return replay(read_events(rig.run_dir / "events.jsonl"))


def state_before(rig: Rig, kind: str, **match: Any) -> RunState:  # noqa: ANN401 - a line's fields
    """The state replayed from the lines before the first one of ``kind`` that matches."""
    rows = lines(rig)
    at = next(
        i
        for i, r in enumerate(rows)
        if r["kind"] == kind and all(r.get(k) == v for k, v in match.items())
    )
    path = rig.run_dir / "prefix.jsonl"
    path.write_bytes(b"".join(json.dumps(r).encode() + b"\n" for r in rows[:at]))
    return replay(read_events(path))


def test_the_end_a_held_for_good_builder_gives_a_run_is_an_ended_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "unrun" in ENDED_STEPS
    rig, _, step = ended(tmp_path, monkeypatch)
    assert step == "unrun"
    # The token total of a run that ended is given, as for a run that ended done.
    assert harness_total(rig.run_dir) > 0


def test_a_decision_written_after_the_end_is_taken_at_the_unrun_step_and_the_run_stays_unrun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, shape, step = ended(tmp_path, monkeypatch)
    assert step == "unrun"
    assert [i.item_id for i in read_queue(rig.run_dir).open_items()] == [SECOND]
    decide(rig.run_dir, "approve", "it is fine", item_id=SECOND)
    before = len(lines(rig))
    assert resumed(rig, monkeypatch, shape) == "unrun"
    rows = lines(rig)
    (taken,) = of(rows, "decision_taken", item_id=SECOND)
    # It was taken where the run had nothing else owed, and it acts on nothing: the item lapsed.
    assert rows.index(taken) >= before
    assert state_before(rig, "decision_taken", item_id=SECOND).next_step().kind == "unrun"
    assert (taken["effect"], taken["acts"], taken["why_not"]) == ("none", False, "superseded")
    assert refusal(rows) is None
    # A process that takes the run over again writes nothing a finished run would not.
    assert resumed(rig, monkeypatch, shape) == "unrun"
    assert {r["kind"] for r in lines(rig)[len(rows) :]} <= {"os_layer_checked"}


def test_a_run_that_acts_under_release_2_names_the_builder_and_never_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _, step = ended(tmp_path, monkeypatch)
    assert step == "unrun"
    state = state_of(rig)
    # Integration's own subtask is left planned with no attempt, as the builder is; no module.
    integration = state.subtasks[INTEGRATION]
    assert integration.status == "planned" and not integration.attempts
    assert [n["subtask_id"] for n in never_ran(state)] == [FIRMWARE2]


def test_a_run_that_only_records_decisions_names_nothing_even_under_the_mark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _, step = ended(tmp_path, monkeypatch)
    assert step == "unrun"
    state = state_of(rig)
    assert state.acts and state.producer_waits.narrow and never_ran(state)
    # The same record, read as one whose run did not act: what names a subtask is acting.
    state.acts = False
    assert never_ran(state) == []


def test_a_run_started_under_release_ends_done_and_names_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record, "WAIT_CYCLE", "release")
    rig, _, step = ended(tmp_path, monkeypatch)
    assert step == "done"
    state = state_of(rig)
    assert state.subtasks[FIRMWARE2].status == "planned"
    assert never_ran(state) == []


def escalated_with_a_builder_never_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Rig, RunState]:
    """Control's sign-off is rejected and its fix ends unmerged; electrical's design ends rejected.

    The run ends ``escalated``, owing control's sign-off, with firmware2 held for good: it would
    end ``unrun`` but for the sign-off, which comes first.
    """
    monkeypatch.setattr(record, "SIGN_OFF_RULES", SIGN_OFF_RULES)
    shape = Shape(
        order=(CONTROL, FIRMWARE, ELECTRICAL, FIRMWARE2),
        reads=((FIRMWARE, CONTROL),),
        design=((ELECTRICAL, FIRMWARE2),),
        closing=False,
    )
    rig = shape.rig(tmp_path, ("pass", "pass", "fail", "fail", "fail", "fail", "pass", "pass"))
    for made in rig.diff.writes[CONTROL]:  # type: ignore[attr-defined]
        for quantity in made["quantities"].values():
            quantity["value"] = 13
    assert first_run(rig, monkeypatch, shape) == "wait"
    decide(rig.run_dir, "reject", "the values are not the ones", item_id=SIGN_OFF)
    decide(rig.run_dir, "reject", "no attempt is left", item_id="run-1-el-4a5b6c")
    assert resumed(rig, monkeypatch, shape) == "wait"
    decide(rig.run_dir, "approve", "it is fine", item_id=SECOND_ROUND)
    assert resumed(rig, monkeypatch, shape) == "escalated"
    return rig, state_of(rig)


def test_an_escalated_end_that_owes_a_sign_off_names_the_module_that_never_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, state = escalated_with_a_builder_never_run(tmp_path, monkeypatch)
    assert state.sign_offs_open() == [CONTROL]
    named = never_ran_at(state, "escalated")
    assert [n["subtask_id"] for n in named] == [FIRMWARE2]
    printed, status = printed_step("escalated", state)
    assert status == 1
    assert [n["subtask_id"] for n in printed["never_ran"]] == [FIRMWARE2]  # type: ignore[attr-defined]
    assert "sign_offs_owed" in printed
    # No other step names them: a run still going, or a done end, is as it was.
    assert never_ran_at(state, "wait") == [] and never_ran_at(state, "done") == []


def test_an_escalated_end_for_another_reason_than_a_sign_off_names_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, state = escalated_with_a_builder_never_run(tmp_path, monkeypatch)
    monkeypatch.setattr(state, "sign_offs_open", list)  # the same record, with no sign-off owed
    assert state.sign_offs_open() == []
    assert never_ran_at(state, "escalated") == []
    assert "never_ran" not in printed_step("escalated", state)[0]
