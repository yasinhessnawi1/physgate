"""A baseline round says, per tier, how much of the tier it covered; only a whole tier is a figure.

A round may be held to harness runs on part of a tier, and it is not refused for that: it runs
what it was given. But its record says, beside each tier's counts, how many of the tier's tasks
(those its version's check left out not among them) it ran (``covered``), of how many (``of``),
and whether that is all of them (``whole``). Whatever turns a round's record into a tier's figure
takes it through one door (:func:`physgate.evaluation.baseline.record.tier_figure`), which refuses
a tier that is not whole with the reason the harness side's counting rule gives
(``tier_not_covered``): a tier's figure is of every task of it but those its check left out,
never of a part chosen by which runs were made.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    SCORED,
    TIERS,
    StandInArm,
    StandInStore,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline.record import BASELINE_RECORD, BaselineRecord
from physgate.evaluation.baseline.runner import RunSet, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.task import Task

RECORD = "physgate.evaluation.baseline.record"


def _score(task: Task, answer: Path) -> dict[str, object]:
    return dict(SCORED)


def _round(made: StandInStore, runs: RunSet, out: Path) -> BaselineRecord:
    return run_baseline(
        store=made.store,
        role="control",
        version=made.version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=_score,
        prices=load_price_sheet(PRICES),
        arm=StandInArm(),
        sleep=lambda _s: None,
    )


def _runs(tmp_path: Path, made: StandInStore, tasks: list[Task]) -> RunSet:
    return run_set(*((harness_run(tmp_path / "runs", task, made), 0) for task in tasks))


def _coverage(record: BaselineRecord, tier: str) -> tuple[Any, Any, Any]:
    counts = record.counts[tier]  # type: ignore[index]
    return (
        getattr(counts, "covered", None),
        getattr(counts, "of", None),
        getattr(counts, "whole", None),
    )


def _figure(record: BaselineRecord, tier: str) -> tuple[str | None, Any]:  # noqa: ANN401
    """What the one door gives of the tier: ``(None, counts)``, or ``(reason, None)``."""
    door = getattr(importlib.import_module(RECORD), "tier_figure", None)
    assert door is not None, "no door turns a round's record into a tier's figure"
    try:
        return None, door(record, tier)
    except PerRoleError as exc:
        return str(exc.context.get("refused_because")), None


def test_a_round_on_part_of_each_tier_is_run_and_says_how_much_it_covered(
    tmp_path: Path,
) -> None:
    made = stand_in_store(tmp_path / "s", flagged=(0,))
    # One visible task, one validation task, and three held-out ones, the first flagged.
    given = [made.tasks["visible"][0], made.tasks["validation"][0], *made.tasks["held_out"][:3]]
    out = tmp_path / "round"
    record = _round(made, _runs(tmp_path, made, given), out)
    rule = "a round's record says per tier how many of its tasks it covered, of how many"
    assert _coverage(record, "visible") == (1, 8, False), rule
    assert _coverage(record, "validation") == (1, 8, False), rule
    # Of the held-out tier, the task the check flagged is in neither count.
    assert _coverage(record, "held_out") == (2, 7, False), rule
    written = json.loads((out / BASELINE_RECORD).read_text())["counts"]
    assert {
        tier: (c.get("covered"), c.get("of"), c.get("whole")) for tier, c in written.items()
    } == {
        "visible": (1, 8, False),
        "validation": (1, 8, False),
        "held_out": (2, 7, False),
    }, "the written record does not carry what the round covered"
    for tier in TIERS:
        reason, counts = _figure(record, tier)
        assert (reason, counts) == ("tier_not_covered", None), (
            f"the {tier} tier, covered in part, was turned into a figure"
        )


def test_a_round_on_every_task_but_those_left_out_is_whole(tmp_path: Path) -> None:
    made = stand_in_store(tmp_path / "s", flagged=(0,))
    given = [task for tier in TIERS for task in made.tasks[tier]]
    record = _round(made, _runs(tmp_path, made, given), tmp_path / "round")
    assert _coverage(record, "visible") == (8, 8, True)
    assert _coverage(record, "validation") == (8, 8, True)
    assert _coverage(record, "held_out") == (7, 7, True), "the flagged task is counted as unrun"
    for tier in TIERS:
        reason, counts = _figure(record, tier)
        assert reason is None, f"a whole {tier} tier was refused as a figure ({reason})"
        assert counts == record.counts[tier]  # type: ignore[index]


def test_a_record_that_says_nothing_of_what_it_covered_is_no_figure(tmp_path: Path) -> None:
    made = stand_in_store(tmp_path / "s")
    given = [task for tier in TIERS for task in made.tasks[tier]]
    record = _round(made, _runs(tmp_path, made, given), tmp_path / "round")
    # A record written before records said so: its counts alone.
    bare = {
        tier: {k: v for k, v in counts.items() if k not in {"covered", "of", "whole"}}
        for tier, counts in record.model_dump(mode="json")["counts"].items()
    }
    earlier = BaselineRecord.model_validate({**record.model_dump(mode="json"), "counts": bare})
    reason, counts = _figure(earlier, "visible")
    assert (reason, counts) == ("tier_not_covered", None), "coverage unknown was taken as whole"


@pytest.mark.parametrize(("covered", "of", "whole"), [(3, 8, True), (8, 8, False), (9, 8, False)])
def test_a_coverage_that_does_not_hold_together_is_no_record(
    tmp_path: Path, covered: int, of: int, whole: bool
) -> None:
    made = stand_in_store(tmp_path / "s")
    given = [task for tier in TIERS for task in made.tasks[tier]]
    record = _round(made, _runs(tmp_path, made, given), tmp_path / "round")
    shape = record.model_dump(mode="json")
    shape["counts"]["visible"] |= {"covered": covered, "of": of, "whole": whole}
    with pytest.raises(ValueError, match="does not hold together"):
        BaselineRecord.model_validate(shape)
