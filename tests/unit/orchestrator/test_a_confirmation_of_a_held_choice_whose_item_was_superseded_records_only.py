"""An operator's confirmation of a held choice, after another decision superseded its item.

A choice written while a session ran without the OS layer is held. If a person then rejects the
sign-off of the module it names, that module is reopened for its fix and the item the choice was
taken on no longer says what is true. Confirming it must not stop the run on a refused line: the
confirmation records only, as a sign-off item's lapsed confirmation does, and replay reads it so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, Rig
from test_a_choice_on_a_failed_contract_reopens_the_other_module import (
    ACTS,
    choose,
    mend,
    of,
)
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    ITEM,
    SIGN_OFF,
    escaped,
    lines,
    refusal,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    DRIVE,
    FW,
    hooked,
    node,
    rig_for,
    start,
)
from test_a_queue_decision_acts_at_a_boundary import _layer, decide

from physgate import roles
from physgate.orchestrator.events import read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import _taken_of, queue_listing


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


DECLARED = (BUDGET, DRIVE, FW)


def held_reopen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """The run to the point where a person's choice of the reopen is held, no OS layer present."""
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    rig = rig_for(tmp_path, dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions"))
    rig.config_overrides.update(ACTS)
    rig.diff.writes.update({BUDGET: [node("budget.supply", "sizing", "iface.drive", v=11)]})  # type: ignore[attr-defined]
    mend(rig, {BUDGET: node("budget.supply", "sizing", "iface.drive", v=12)})
    rig.dispatcher.during[3] = lambda: choose(rig.run_dir, "producer")
    loop = rig.open()
    hooked(monkeypatch, loop, declared=DECLARED)
    start(loop, sizing=True)
    _layer(loop, present=False)
    assert escaped(loop.run) is None
    loop.close()
    (held,) = of(lines(rig), "decision_taken")
    assert (held["effect"], held["acts"], held["why_not"]) == ("reopen", False, "held_os_layer_off")
    return rig


def test_a_held_reopen_is_not_listed_as_a_reopen_no_line_follows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A choice held for an operator's confirmation acts on nothing yet, so no reopening is owed on
    # the record: the listing must not say none is on it, as it says of a choice that acted.
    rig = held_reopen(tmp_path, monkeypatch)
    taken = _taken_of(read_events(rig.run_dir / "events.jsonl"))[ITEM]
    assert (taken["effect"], taken["acts"], taken["why_not"]) == (
        "reopen",
        False,
        "held_os_layer_off",
    )
    assert "reopened" not in taken, (
        f"a held choice is not marked as a reopen that never came: {taken!r}"
    )
    decided: list[dict[str, Any]] = queue_listing(rig.run_dir)["decided"]  # type: ignore[assignment]
    listed = {d["item_id"]: d["taken"] for d in decided}
    assert ITEM in listed, f"the held choice is listed with the decisions taken: {sorted(listed)}"
    assert "reopened" not in listed[ITEM], listed[ITEM]


def test_confirming_a_held_choice_after_its_item_was_superseded_records_only_and_the_run_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = held_reopen(tmp_path, monkeypatch)
    declared = DECLARED
    # The person rejects drive's sign-off before anything confirms the held choice.
    decide(rig.run_dir, "reject", "the values are wrong", item_id=SIGN_OFF)
    # A resume without the confirmation takes the rejection: drive is reopened for its fix.
    again = rig.open()
    hooked(monkeypatch, again, declared=declared)
    _layer(again, present=False)
    assert escaped(lambda: again.resume().kind) is None
    again.close()
    assert [r["subtask_id"] for r in of(lines(rig), "subtask_reopened")] == [DRIVE]
    before = lines(rig)
    resumed = rig.open()
    hooked(monkeypatch, resumed, declared=declared)
    _layer(resumed, present=False)
    said = escaped(lambda: resumed.resume(confirm=(ITEM,), confirmed_by="operator").kind)
    resumed.close()
    assert said is None, f"a confirmation of a superseded choice must be taken, not refused: {said}"
    rows = lines(rig)
    assert rows[: len(before)] == before, "no earlier line is rewritten"
    confirmed = [r for r in of(rows, "decision_taken", item_id=ITEM) if r.get("confirmed_by")]
    assert len(confirmed) == 1, "the confirmation is written, once"
    (line,) = confirmed
    assert (line["confirmed_by"], line["effect"], line["acts"], line["why_not"]) == (
        "operator",
        "none",
        False,
        "superseded",
    )
    assert not [r for r in of(rows, "subtask_reopened") if r.get("item_id") == ITEM]
    assert refusal(rows) is None, "replay reads the confirmation as the loop wrote it"
