"""A contract item offers no reopen of a module that cannot take one, and a run never stops on one.

A rejected sign-off orders its module's one fix. If that fix ends unmerged the module is still
``done``, with an earlier merge standing, but its last attempt has no merge to start another from.
A contract item raised after that used to offer "reopen" for it; the loop then found no merge,
raised, and every resume raised the same way. The item now says the choice records only, as it
does for a module that is not merged; a reopen the loop still could not carry out is recorded as
acting on nothing; and a record that already ends at such a choice reads, and the run goes on.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from arbitration_runs import CLOSING as SLICE
from arbitration_runs import PerAttempt, events_of
from loop_fakes import FakeGate, FakeReviewer, Rig
from orch_helpers import make_config
from test_a_choice_on_a_failed_contract_reopens_the_other_module import choose, of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_follow_up_after_the_closing_pass_is_recorded_and_replayed_as_the_record_owes import (
    ended,
    slice_rig,
)
from test_a_queue_decision_acts_at_a_boundary import decide
from test_a_run_records_the_code_it_ran_on import checkout
from wait_cycle_rig import CONTROL, FIRMWARE, Shape, first_run, resumed, resumed_expecting

from physgate import roles
from physgate.cli import main
from physgate.orchestrator import cli as orchestrator_cli
from physgate.orchestrator import decisions as deciding
from physgate.orchestrator import record, replay
from physgate.orchestrator.events import Event, read_events
from physgate.orchestrator.exceptions import OrchestratorError, RunStateError
from physgate.orchestrator.queue import _choice_words, _taken_of, queue_listing, read_queue
from physgate.orchestrator.run_config import harness_state, write_run_config

SIGN_OFF = "run-1-SIGNOFF-drive-0a1b2c"
FIRST, SECOND = "run-1-contract-1", "run-1-contract-1-r2"
INTEGRATION = "integ"
#: What a row that resumes a run, and does not expect it to stop on an error, says it expected.
WENT_ON = "the run goes on after the person's choice"
RECORDED = (
    Path(__file__).parent
    / "records_of_a_reopen_the_loop_could_not_carry_out"
    / "run_ended_at_a_reopen_it_could_not_carry_out.jsonl"
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


@pytest.fixture(params=["release_2", "release", None])
def mark(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str | None:
    """Every mark a run can begin under: the rule is the same under each."""
    monkeypatch.setattr(record, "WAIT_CYCLE", request.param)
    return request.param  # type: ignore[no-any-return]


def recorded_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in RECORDED.read_text().splitlines()]


def after_the_fix_ended(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Rig, Shape]:
    """Control merges and owes a sign-off; firmware merges and the pair fails on control's value.

    A person rejects the sign-off: control's one fix is ordered, its review fails and the fix ends
    unmerged. The pair is tested again and a second item is listed, which the run waits on.
    """
    shape = Shape(order=(CONTROL, FIRMWARE), reads=((FIRMWARE, CONTROL),), design=(), closing=False)
    rig = shape.rig(tmp_path, ("pass", "pass", "fail", "fail", "fail"))
    for made in rig.diff.writes[CONTROL]:  # type: ignore[attr-defined]
        for quantity in made["quantities"].values():
            quantity["value"] = 13
    assert first_run(rig, monkeypatch, shape) == "wait"
    decide(rig.run_dir, "reject", "the values are not the ones", item_id=SIGN_OFF)
    assert resumed(rig, monkeypatch, shape) == "wait"
    rows = lines(rig)
    assert [r["subtask_id"] for r in of(rows, "sign_off_fix_ended")] == [CONTROL]
    assert [r["item_id"] for r in of(rows, "contract_item_raised")] == [FIRST, SECOND]
    return rig, shape


def offered(rig: Rig, item_id: str) -> dict[str, str]:
    item = next(i for i in read_queue(rig.run_dir).items if i.item_id == item_id)
    assert item.consequence is not None and item.consequence.on_choose is not None
    return {str(k): str(v) for k, v in item.consequence.on_choose.items()}


def test_the_item_offers_a_reopen_while_the_module_s_last_attempt_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mark: str | None
) -> None:
    rig, _ = after_the_fix_ended(tmp_path, monkeypatch)
    # The first item was raised before the fix, with control's merge standing on its last attempt.
    assert offered(rig, FIRST) == {"producer": "reopen", "consumer": "record_only"}


def test_the_item_raised_after_the_fix_ended_offers_no_reopen_of_that_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mark: str | None
) -> None:
    rig, _ = after_the_fix_ended(tmp_path, monkeypatch)
    assert offered(rig, SECOND) == {"producer": "record_only", "consumer": "record_only"}
    said = next(i for i in read_queue(rig.run_dir).items if i.item_id == SECOND).decision_required
    # The words are true of a module whose earlier merge stands: not "not merged".
    assert "cannot be reopened now" in said and "its last attempt did not merge" in said
    assert "is not merged now" not in said


def test_choosing_on_it_records_only_and_the_run_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mark: str | None
) -> None:
    rig, shape = after_the_fix_ended(tmp_path, monkeypatch)
    choose(rig.run_dir, "producer", item_id=SECOND)
    step = resumed_expecting(rig, monkeypatch, shape, WENT_ON)
    rows = lines(rig)
    (taken,) = of(rows, "decision_taken", item_id=SECOND)
    assert (taken["effect"], taken["acts"], taken.get("reopens")) == ("none", False, None)
    assert of(rows, "subtask_reopened", subtask_id=CONTROL) == of(
        rows, "subtask_reopened", item_id=SIGN_OFF
    )
    assert step in ("done", "escalated", "unrun")
    assert refusal(rows) is None
    # A fresh process writes nothing a run that had not stopped would not.
    assert resumed_expecting(rig, monkeypatch, shape, WENT_ON) == step


def _as_before(patch: pytest.MonkeyPatch) -> None:
    """The item and the loop as they were: a module that is ``done`` can be reopened."""

    def before(sub: Any) -> bool:  # noqa: ANN401 - the replayed subtask
        return bool(sub.status == "done")

    patch.setattr(deciding, "reopenable", before)
    patch.setattr(replay, "reopenable", before)


def _stale_choices(patch: pytest.MonkeyPatch) -> None:
    """A ``contract_choices`` that offers the reopen of every module the guard is asked about."""
    original = deciding.contract_choices

    def stale(state: Any, tested: Any) -> Any:  # noqa: ANN401 - the replayed state
        return {
            position: dataclasses.replace(choice, why="reopen")
            for position, choice in original(state, tested).items()
        }

    patch.setattr(deciding, "contract_choices", stale)


def test_a_reopen_the_loop_cannot_carry_out_is_recorded_as_acting_on_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mark: str | None
) -> None:
    # An item that offers the reopen all the same (here by a choices function that does): the
    # second guard, so that the loop is never ordered a reopen it cannot write.
    with monkeypatch.context() as stale:
        _stale_choices(stale)
        rig, shape = after_the_fix_ended(tmp_path, stale)
        assert offered(rig, SECOND)["producer"] == "reopen"
        choose(rig.run_dir, "producer", item_id=SECOND)
        failure: Exception | None = None
        step = ""
        try:
            step = resumed(rig, stale, shape)
        except (ValueError, RunStateError) as exc:
            failure = exc
        rows = lines(rig)
        written = of(rows, "decision_taken", item_id=SECOND)
        assert len(written) == 1, (
            "the choice is written once, as a decision that acts on nothing; "
            f"the run raised {failure!r} instead"
        )
        (taken,) = written
        assert (taken["effect"], taken["acts"], taken["why_not"]) == ("none", False, "not_merged")
        assert not of(rows, "subtask_reopened", item_id=SECOND)
        assert failure is None, f"the run goes on after it: {failure!r}"
        assert step in ("done", "escalated", "unrun")
        assert refusal(rows) is None, "replay agrees with the run that wrote the line"


def made_by_the_code_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, choice: bool
) -> tuple[Rig, Shape]:
    """The run as the code before this change made it: the second item offers the reopen.

    With ``choice``, the person chooses it and the loop stops on the reopen it cannot write.
    """
    with monkeypatch.context() as before:
        _as_before(before)
        rig, shape = after_the_fix_ended(tmp_path, before)
        assert offered(rig, SECOND)["producer"] == "reopen"
        if choice:
            choose(rig.run_dir, "producer", item_id=SECOND)
            with pytest.raises(RunStateError, match="a reopen with no decision"):
                resumed(rig, before, shape)
    return rig, shape


def signature(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """What each line says of the run, but for the timestamps and digests of its own directory."""
    fields = ("kind", "subtask_id", "item_id", "verb", "position", "effect", "acts", "why_not")
    return [tuple(row.get(f) for f in (*fields, "reopens")) for row in rows]


def test_a_run_that_ends_at_a_reopen_the_code_before_ordered_resumes_without_rewriting_a_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mark: str | None
) -> None:
    # What replay does with a record that ends at such a line: a property of the replay rule. It is
    # not a way to carry a run over from the code before; the real entry refuses other code (the
    # last row), so no run is resumed on this code from a record that other code made.
    rig, shape = made_by_the_code_before(tmp_path, monkeypatch, choice=True)
    # The record made so is the one the unchanged sources made (the recorded one), line for line.
    rows = lines(rig)
    recorded = recorded_rows()
    assert signature(rows[: len(recorded)]) == signature(recorded)
    # A run left dead had been resumed again and again, each time stopping on the same line.
    with monkeypatch.context() as before:
        _as_before(before)
        for _ in range(2):
            with pytest.raises(RunStateError, match="a reopen with no decision"):
                resumed(rig, before, shape)
    stopped = (rig.run_dir / "events.jsonl").read_bytes()
    trailing = [json.loads(line)["kind"] for line in stopped.splitlines()[len(recorded) :]]
    assert trailing and set(trailing) <= {"os_layer_checked"}, trailing
    last = [r for r in lines(rig) if r["kind"] == "decision_taken"][-1]
    assert (last["effect"], last["acts"], last["item_id"]) == ("reopen", True, SECOND)
    step = resumed_expecting(
        rig, monkeypatch, shape, "a record that ends at a reopen no module could take is resumed"
    )
    after = (rig.run_dir / "events.jsonl").read_bytes()
    assert after.startswith(stopped), "no earlier line is rewritten"
    rows = lines(rig)
    assert not [r for r in rows[len(stopped.splitlines()) :] if r["kind"] == "subtask_reopened"]
    assert step in ("done", "escalated", "unrun")
    assert refusal(rows) is None
    again = resumed_expecting(rig, monkeypatch, shape, "a second resume goes the same way")
    assert again == step, "and a second resume goes the same way"


def test_an_item_the_code_before_listed_with_the_reopen_halts_on_a_choice_of_it_as_a_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mark: str | None
) -> None:
    # An item still open from before: what it says is not what the record gives now. The decision
    # is refused under the cause every such item has, and nothing is reopened or raised. The halt
    # is final: no command resolves it, and it needs a run continued on other code, which the
    # real entry refuses (the last row). The item-against-record comparison is not relaxed.
    rig, shape = made_by_the_code_before(tmp_path, monkeypatch, choice=False)
    choose(rig.run_dir, "producer", item_id=SECOND)
    step = resumed_expecting(
        rig, monkeypatch, shape, "a choice on the item listed before halts the run on an incident"
    )
    assert step == "halted"
    rows = lines(rig)
    assert [r["cause"] for r in of(rows, "incident")] == ["queue_item_mismatch"]
    assert not of(rows, "decision_taken", item_id=SECOND)
    assert refusal(rows) is None


def recorded_events() -> list[Event]:
    """The record the code before made, read as the code reads a run's record."""
    try:
        return list(read_events(RECORDED))
    except (ValueError, OrchestratorError) as exc:
        msg = f"the record the code before made reads as a run; it raised {exc!r}"
        raise AssertionError(msg) from exc


def recorded_state() -> Any:  # noqa: ANN401 - the replayed state
    events = recorded_events()
    try:
        return replay.replay(events)
    except (ValueError, OrchestratorError) as exc:
        msg = f"the record the code before made replays as a run; it raised {exc!r}"
        raise AssertionError(msg) from exc


def test_a_record_the_code_before_made_ends_at_the_reopen_and_replays_on() -> None:
    # Recorded by the unchanged sources: control's sign-off fix ended unmerged, the second item
    # offered its reopen and the person chose it; the log ends at that decision.
    last = json.loads(RECORDED.read_text().splitlines()[-1])
    assert (last["kind"], last["effect"], last["acts"], last["reopens"]) == (
        "decision_taken",
        "reopen",
        True,
        CONTROL,
    )
    state = recorded_state()
    assert state.pending_reopen is None
    assert state.next_step().kind != "reopen"
    assert state.taken[SECOND].effect == "reopen"
    assert not deciding.reopenable(state.subtasks[CONTROL])
    assert deciding.reopenable(state.subtasks[FIRMWARE])


def test_a_choice_that_reopens_nothing_changes_no_module_s_record() -> None:
    state = recorded_state()
    sub = state.subtasks[CONTROL]
    assert sub.status == "done" and sub.reopens == 1 and sub.sign_off_fixed is not None


def test_the_line_the_code_before_wrote_is_read_only_for_a_module_that_cannot_be_reopened() -> None:
    rows = recorded_rows()
    assert refusal(rows) is None
    # The same line naming firmware, whose last attempt merged: the record gives no such reopen
    # (the item offered none for it), so a line that orders one is not the line the code wrote.
    forged = [*rows[:-1], rows[-1] | {"reopens": FIRMWARE}]
    assert "other than the record allows" in (refusal(forged) or "")
    # Nor is a line that names a module outside the item's pair: one the run has and cannot
    # reopen (integration's own subtask is planned), or one it does not have at all.
    state = recorded_state()
    assert INTEGRATION in state.subtasks and not deciding.reopenable(state.subtasks[INTEGRATION])
    outside = refusal([*rows[:-1], rows[-1] | {"reopens": INTEGRATION}])
    assert "other than the record allows" in (outside or ""), outside
    assert refusal([*rows[:-1], rows[-1] | {"reopens": "sz-6a7b8c"}]) is not None
    # Nor is a line of another verb.
    assert refusal([*rows[:-1], rows[-1] | {"verb": "approve", "position": None}]) is not None


def test_a_module_is_reopenable_only_while_it_is_done_and_its_last_attempt_merged() -> None:
    state = recorded_state()
    tested = state.contract_items[SECOND]
    control = state.subtasks[CONTROL]
    assert not deciding.reopenable(control) and control.attempts[-1].merged is None
    assert deciding.contract_choices(state, tested)["producer"].why == "closed"
    # Give its last attempt the merge its first one made: the choice now reopens it ...
    control.attempts[-1].merged = control.attempts[0].merged
    assert deciding.reopenable(control)
    assert deciding.contract_choices(state, tested)["producer"].why == "reopen"
    # ... unless it is not done (reopened already, its next attempt not yet made) ...
    control.status = "active"
    assert not deciding.reopenable(control)
    assert deciding.contract_choices(state, tested)["producer"].why == "closed"
    # ... or has no attempt at all.
    control.status, control.attempts = "done", []
    assert not deciding.reopenable(control)


def test_a_module_whose_follow_up_ended_unmerged_is_not_offered_a_reopen_either() -> None:
    # The follow-up the closing pass owes is the other way a module is left ``done`` with an
    # earlier merge standing and none on its last attempt. Built by hand on the recorded state:
    # control's last attempt, which ended unmerged, is read as the follow-up it ended instead of
    # the sign-off fix, and the item is read again. Built by hand because no run reaches an open
    # contract item for such a module (the closing pass, and so its follow-up, waits while an item
    # is open); the row after this one has the run write the follow-up's end and replay it.
    state = recorded_state()
    tested = state.contract_items[SECOND]
    control = state.subtasks[CONTROL]
    assert control.sign_off_fixed is not None
    control.followed_up = control.sign_off_fixed.model_copy(
        update={"item_id": None, "shown_sha256": None, "cause": "follow_up"}
    )
    control.sign_off_fixed = None
    assert replay.following_up(control) and not replay.sign_off_fixing(control)
    assert control.status == "done" and control.attempts[0].merged is not None
    assert not deciding.reopenable(control)
    assert deciding.contract_choices(state, tested)["producer"].why == "closed"
    # Its follow-up merged instead: the reopen is offered again.
    control.attempts[-1].merged = control.attempts[0].merged
    assert deciding.contract_choices(state, tested)["producer"].why == "reopen"


def closed_choice_words() -> str:
    """The words of the item whose producer's module is closed to a reopen, as the code words it."""
    state = recorded_state()
    choices = deciding.contract_choices(state, state.contract_items[SECOND])
    assert choices["producer"].why == "closed", "the module's last attempt did not merge"
    return _choice_words(choices)


def test_the_words_of_a_closed_choice_name_the_sign_off_fix_and_the_follow_up_alike() -> None:
    said = closed_choice_words()
    # Either way a module is left done, with an earlier merge standing, and none to start from.
    assert "a sign-off's fix" in said and "a follow-up" in said, said
    assert "ended without one" in said, said


def test_the_words_of_a_closed_choice_name_the_integration_call_having_run() -> None:
    said = closed_choice_words()
    # A module is also closed to a reopen once integration ran, whatever its last attempt did.
    assert "or integration ran." in said, said


def test_a_follow_up_the_run_wrote_as_ended_replays_as_a_module_with_no_merge_to_reopen_from(
    tmp_path: Path,
) -> None:
    # s1 merges on its third attempt; its one follow-up is not accepted, and the run writes that
    # as ``follow_up_ended``. Replay reads the line: the module is done again on its earlier merge.
    rig = slice_rig(tmp_path)
    rig.gate = PerAttempt(verdicts=["fail", "fail"])
    rig.reviewer = FakeReviewer(verdicts=["pass", "pass", "pass", "fail"])
    assert ended(rig, plan=SLICE) == "done"
    events = events_of(rig)
    assert [e.kind for e in events if e.kind == "follow_up_ended"] == ["follow_up_ended"]
    sub = replay.replay(events).subtasks["s1"]
    assert sub.status == "done" and replay.following_up(sub)
    assert sub.attempts[-1].merged is None, "the follow-up's attempt is not merged"
    assert any(a.merged is not None for a in sub.attempts), "an earlier merge stands"
    assert not deciding.reopenable(sub), "no merge on the last attempt: nothing to reopen from"


def test_a_decision_that_acts_as_a_reopen_no_line_follows_is_listed_as_not_reopened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mark: str | None
) -> None:
    # The record the code before made ends at the choice: no reopening is on it, and the listing
    # says so, so that the page does not say a module was reopened.
    taken = _taken_of(recorded_events())[SECOND]
    assert (taken["effect"], taken["acts"]) == ("reopen", True)
    assert "reopened" in taken, f"the listing marks a reopen no line follows: {taken!r}"
    assert taken["reopened"] is False
    # A reopen that was written is not marked, and every other decision keeps its shape.
    rig, _ = after_the_fix_ended(tmp_path, monkeypatch)
    decided: list[dict[str, Any]] = queue_listing(rig.run_dir)["decided"]  # type: ignore[assignment]
    listed = {d["item_id"]: d["taken"] for d in decided}
    assert listed[SIGN_OFF]["effect"] == "reopen" and "reopened" not in listed[SIGN_OFF]


def test_a_record_made_by_other_code_is_not_continued_by_the_real_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An item the code before listed with the reopen, and the halt on any decision on it, are
    # states of that code's own runs. A run is continued only on the code it began on, so the
    # real entry refuses one made by other code, before it reads or writes a line of its record.
    harness = checkout(tmp_path / "harness")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run_config(run_dir / "run.json", make_config(harness=harness_state(harness)))
    made = RECORDED.read_bytes()
    (run_dir / "events.jsonl").write_bytes(made)
    (harness / "b.py").write_text(
        "x = 2\n"
    )  # this change: the code is no longer the one it began on
    for args in (["add", "-A"], ["commit", "-q", "-m", "this change"]):
        subprocess.run(["git", *args], cwd=harness, check=True)
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    registrations = orchestrator_cli.Registrations(
        gate=FakeGate(), reviewers={"electrical": FakeReviewer()}
    )
    args = ["--run-dir", str(run_dir), "--target", str(tmp_path / "t")]
    install = ["--install", str(tmp_path / "install"), "--review-root", str(tmp_path / "rs")]
    assert main(["resume", *args, *install], registrations) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "the harness checkout differs from the one this run recorded"
    assert error["changed"] == "commit"
    assert (run_dir / "events.jsonl").read_bytes() == made, "the record is not touched"
