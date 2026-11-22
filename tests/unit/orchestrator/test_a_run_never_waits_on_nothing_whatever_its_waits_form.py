"""Over small random plans the run never ends in a wait with no item a person can decide.

Each seed makes a plan of three to five subtasks (sizing and its closing pass among them, or not):
a random plan order, random reads between modules, random designs of one module by another that
the plan orders designer first, random review verdicts that send subtasks to a person, and a
person who approves or rejects each item at random, signing what a module owes. The run is taken
over after each decision. At every stop the run is not waiting on nothing while a subtask is still
planned; no builder is dispatched before its designer merged; the record replays; and the run ends.
A failure names its seed, and the seed alone remakes the plan. Some of the seeds are plans that
end in the wait with no item when the rule is not in force (the last row runs them so): without
them the row would hold the rule only by the mark on the first line.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from sign_off_rig import sign_every_open_item
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_queue_decision_acts_at_a_boundary import decide
from wait_cycle_rig import (
    CONTROL,
    ELECTRICAL,
    FIRMWARE,
    SIZING,
    Shape,
    first_run,
    resumed,
)

from physgate import roles
from physgate.orchestrator import record
from physgate.orchestrator.queue import read_queue

#: Seeds whose plan ends in a wait with no item open when the run is not started under the
#: ``wait_cycle`` rule: the defect itself. Found by running seeds 0 to 329 with the mark off (13
#: of the 330), and held honest by the last row below, which runs each with the mark off. Of the
#: first 36 seeds only two (9 and 16) are among them; the rest fail the row on its closing check
#: that the mark is there, and would pass a change that took the rule out of effect.
DEADLOCKS_WITHOUT_THE_RULE = (9, 16, 70, 90, 106, 172, 212, 256, 274, 282, 288, 317, 325)
SEEDS = sorted({*range(36), *DEADLOCKS_WITHOUT_THE_RULE})
ROUNDS = 20
POOL = (SIZING, CONTROL, FIRMWARE, ELECTRICAL)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def plan_of(rng: random.Random) -> Shape:
    """A plan of three or four modules (and sizing's closing pass if sizing is one)."""
    modules = rng.sample(POOL, rng.choice((3, 4, 4)))
    reads = tuple((p, c) for p in modules for c in modules if p != c and rng.random() < 0.5)
    design = tuple(
        (d, b)
        for i, d in enumerate(modules)
        for b in modules[i + 1 :]
        if SIZING not in (d, b) and rng.random() < 0.5
    )
    return Shape(order=tuple(modules), reads=reads, design=design)


def decisions(rng: random.Random, run_dir: Path) -> int:
    """A person decides every open item at random; how many were decided."""
    decided = len(sign_every_open_item(run_dir))
    for item in read_queue(run_dir).open_items():
        verb = rng.choice(("approve", "approve", "reject"))
        decide(run_dir, verb, "not this one" if verb == "reject" else None, item_id=item.item_id)
        decided += 1
    return decided


def check_order(rows: list[dict[str, Any]], shape: Shape, said: str) -> None:
    """No builder was dispatched before its designer merged."""
    for designer, builder in shape.design:
        starts = [
            i
            for i, r in enumerate(rows)
            if r.get("subtask_id") == builder and r["kind"] == "stage_entered"
        ]
        merges = [
            i
            for i, r in enumerate(rows)
            if r.get("subtask_id") == designer and r["kind"] == "merged"
        ]
        if starts:
            assert merges
            assert merges[0] < starts[0], f"{said}: {builder} dispatched before {designer} merged"


@dataclass
class Played:
    """One seed's run: its plan, its record, where it ended, and the first stall it showed."""

    said: str
    shape: Shape
    rows: list[dict[str, Any]]
    step: str
    #: Set to the first wait with no item open, where the run stopped in one.
    stalled: str | None


def play(seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Played:
    """The run of ``seed``'s plan, a person deciding at random after each stop."""
    rng = random.Random(seed)
    shape = plan_of(rng)
    said = f"seed {seed}: order={shape.order} reads={shape.reads} design={shape.design}"
    signs = rng.random() < 0.5
    if not signs:
        monkeypatch.setattr(record, "SIGN_OFF_RULES", None)
    # The first subtask reviewed is sent to a person more often than not; later ones at random.
    verdicts = ["fail"] * 3 * rng.choice((0, 1, 1)) + [
        "fail" if rng.random() < 0.3 else "pass" for _ in range(40)
    ]
    rig = shape.rig(tmp_path, verdicts)
    step = first_run(rig, monkeypatch, shape)
    stalled: str | None = None
    for _ in range(ROUNDS):
        rows = lines(rig)
        if step == "wait" and not read_queue(rig.run_dir).open_items():
            stalled = f"{said}: a wait with no item open, after {len(rows)} lines"
            break
        if step != "wait":
            break
        decisions(rng, rig.run_dir)
        step = resumed(rig, monkeypatch, shape)
    return Played(said, shape, lines(rig), step, stalled)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_random_plan_never_ends_in_a_wait_with_no_item_open(
    seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    played = play(seed, tmp_path, monkeypatch)
    assert played.stalled is None, played.stalled
    assert played.step in ("done", "escalated"), f"{played.said}: ended as {played.step!r}"
    assert refusal(played.rows) is None, played.said
    check_order(played.rows, played.shape, played.said)
    assert of(played.rows, "run_started")[0]["wait_cycle"] == "release"


@pytest.mark.parametrize("seed", DEADLOCKS_WITHOUT_THE_RULE)
def test_each_seed_that_is_meant_to_catch_the_old_ending_ends_in_it_with_the_mark_off(
    seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seeds the row above is held to are honest: each stalls where the rule is not in force."""
    monkeypatch.setattr(record, "WAIT_CYCLE", None)
    played = play(seed, tmp_path, monkeypatch)
    assert played.stalled is not None, played.said
    assert "wait_cycle" not in of(played.rows, "run_started")[0]
