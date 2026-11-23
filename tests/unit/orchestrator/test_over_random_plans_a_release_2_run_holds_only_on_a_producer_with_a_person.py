"""Over random plans under ``release_2`` no wait forms a cycle: the property the narrowing rests on.

The plans, decisions and seeds are those of the row for the earlier rule (and its thirteen seeds
that deadlock without any cycle rule). Under ``release_2`` every ``dispatch_held`` names the item
of its producer's own escalation; neither cycle release is ever written; no run ends in a wait
with no item open, loops, or dispatches a builder before its designer merged; a run ends ``unrun``
exactly when a subtask never ran; and the record replays.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import refusal
from test_a_run_never_waits_on_nothing_whatever_its_waits_form import (
    SEEDS,
    _sizing_registered,  # noqa: F401 - the fixture, by name
    check_order,
    play,
)

CYCLE_OUTCOMES = ("producer_waits_for_reader", "producer_held_for_good")


@pytest.mark.parametrize("seed", SEEDS)
def test_a_random_plan_under_release_2_holds_only_on_a_producer_with_a_person(
    seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    played = play(seed, tmp_path, monkeypatch)
    rows = played.rows
    assert of(rows, "run_started")[0]["wait_cycle"] == "release_2"
    assert played.stalled is None, played.stalled
    assert played.step in ("done", "escalated", "unrun"), f"{played.said}: {played.step!r}"
    assert refusal(rows) is None, played.said
    check_order(rows, played.shape, played.said)
    own = {r["subtask_id"]: r["item_id"] for r in of(rows, "escalated")}
    for hold in of(rows, "dispatch_held"):
        escalated = [r["item_id"] for r in of(rows, "escalated", subtask_id=hold["producer"])]
        assert hold["item_id"] in escalated, f"{played.said}: a hold names another item"
        assert hold["producer"] in own
    assert not [r for r in of(rows, "dispatch_released") if r["outcome"] in CYCLE_OUTCOMES]
    never_ran = [
        s
        for s in played.shape.order
        if s not in {r["subtask_id"] for r in of(rows, "stage_entered")}
    ]
    never_held = set(never_ran) & {r["subtask_id"] for r in of(rows, "builder_held")}
    if played.step == "unrun":
        assert never_held, f"{played.said}: ended unrun with nothing that never ran"
    if played.step == "done":
        assert not never_held, f"{played.said}: ended done with {sorted(never_held)} never run"
