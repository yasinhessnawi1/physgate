"""What a version's blind check flagged is left out of every held-out count, rate, gap and interval.

The held-out vector is written from the runs of the tasks the check did not flag: a flagged task's
runs and records are left out with it, and the vector says how many and which, by digest, with
the check record's digest. A version with no check record is not scored: its held-out vector is
not written, and its gaps are not computed. ``physgate gaps`` holds the vector to the record as it
reads now, carries what was left out beside its figures and says it in words in the held-out rate,
both gaps' words and the notes. The trend line carries it, and two lines of one version that left
out different tasks are refused. The visible and validation tiers are counted whole.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from gap_fixtures import (
    Measured,
    StandInStore,
    api,
    design,
    measured,
    record_check,
    stand_in_store,
)

from physgate.cli import main
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import id_digest

WRITE = "physgate.evaluation.tiers.measure.write_vector"
CHECKS = "physgate.evaluation.tiers.checks"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    # Held-out task 0 is flagged: every row measures it, and it is left out.
    return stand_in_store(tmp_path / "st", flagged=(0,))


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "context", {}).get("refused_because", type(exc).__name__))


def _vector(made: StandInStore, tier: str, m: Measured) -> Path:
    withheld = withheld_root(made.store, "control")
    key = api(WRITE)(withheld, version=made.version, tier=tier, runs=m.runs, trials=m.trials)
    return withheld / "gaps" / f"{key}.json"


def _record(made: StandInStore) -> Any:  # noqa: ANN401
    return api(f"{CHECKS}.read_check")(made.store, "control", made.version)


def _registered(made: StandInStore) -> int:
    lines = api("physgate.evaluation.tiers.exposure.register_lines")(made.store, "control")
    return len(lines)


def test_the_held_out_vector_leaves_out_the_flagged_task_and_says_which(
    tmp_path: Path, made: StandInStore
) -> None:
    held = measured(made, "held_out", tmp_path / "h", tasks=3)
    body = json.loads(_vector(made, "held_out", held).read_text())
    assert len(body["tasks"]) == 2, "a flagged task was counted"
    flagged = id_digest(made.tasks["held_out"][0].id)
    assert body["left_out"] == {
        "count": 1,
        "digests": [flagged],
        "check_sha256": _record(made).sha256,
    }
    assert all(t["trials"] == 2 for t in body["tasks"])
    text = json.dumps(body)
    for task in made.tasks["held_out"]:
        assert task.id not in text and task.brief not in text


def test_the_validation_vector_is_counted_whole_and_leaves_nothing_out(
    tmp_path: Path, made: StandInStore
) -> None:
    body = json.loads(
        _vector(
            made, "validation", measured(made, "validation", tmp_path / "w", tasks=3)
        ).read_text()
    )
    assert len(body["tasks"]) == 3 and body.get("left_out") is None


def test_no_held_out_vector_is_written_for_a_version_with_no_check_record(tmp_path: Path) -> None:
    made = stand_in_store(tmp_path / "u", checked=False)
    held = measured(made, "held_out", tmp_path / "h")
    before = _registered(made)
    with pytest.raises(api("physgate.evaluation.gaps.vector.GapsError")) as refused:
        _vector(made, "held_out", held)
    assert _reason(refused.value) == "held_out_unchecked", "an unchecked tier was scored"
    assert _registered(made) == before, "a measurement was counted of an unchecked tier"
    assert not (withheld_root(made.store, "control") / "gaps").exists()


def test_a_record_that_flags_no_task_of_the_tier_refuses_the_vector(tmp_path: Path) -> None:
    made = stand_in_store(tmp_path / "x", checked=False)
    record_check(made.store, made.version, [made.tasks["visible"][0].id], all_yes=7)
    with pytest.raises(api("physgate.evaluation.gaps.vector.GapsError")) as refused:
        _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    assert _reason(refused.value) == "check_record_not_the_tier"


def _gaps(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    body: dict[str, Any],
    visible: Measured,
    held_out: Path,
    validation: Path | None,
    *extra: str,
) -> tuple[int, dict[str, Any], str]:
    path = tmp_path / "design.json"
    path.write_text(json.dumps(body))
    argv = ["gaps", "--design", str(path), "--runs", str(visible.runs)]
    argv += ["--trials", str(visible.trials), "--held-out", str(held_out)]
    if validation is not None:
        argv += ["--validation", str(validation)]
    code = main([*argv, *extra])
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert lines, "gaps printed nothing"
    return code, json.loads(lines[-1]), out


def _measured_all(tmp_path: Path, made: StandInStore) -> tuple[Measured, Path, Path]:
    visible = measured(made, "visible", tmp_path / "v", tasks=3)
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h", tasks=3))
    valid = _vector(made, "validation", measured(made, "validation", tmp_path / "w", tasks=3))
    return visible, held, valid


def test_the_gaps_count_the_unflagged_tasks_and_say_what_was_left_out_beside_every_figure(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible, held, valid = _measured_all(tmp_path, made)
    body = design(made, visible, held_out_tasks=2, validation_tasks=3)
    code, said, out = _gaps(capsys, tmp_path, body, visible, held, valid)
    assert code == 0, said
    # Hand table (gap_fixtures.PASSES): held out passes task 0, trial 0 only; task 0 is the one
    # flagged, so the two counted tasks pass nothing.
    assert (said["held_out"]["passed"], said["held_out"]["n"]) == (0, 4)
    assert (said["validation"]["n"], said["visible"]["n"]) == (6, 6), "another tier was cut"
    left = said["held_out_left_out"]
    assert left["count"] == 1 and left["digests"] == [id_digest(made.tasks["held_out"][0].id)]
    words = "1 held-out task left out"
    assert words in said["held_out"]["rate"], "the held-out rate is shown without what it left"
    for gap in ("reward_hacking", "optimiser_overfit"):
        assert words in said[gap]["words"], "a gap is shown without what it left out"
    assert any(n.startswith("held out") and words in n for n in said["notes"])
    for task in made.tasks["held_out"]:
        assert task.id not in out


def test_a_version_with_no_check_record_has_no_gap(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible, held, valid = _measured_all(tmp_path, made)
    api(f"{CHECKS}.check_path")(made.store, "control", made.version).unlink()
    body = design(made, visible, held_out_tasks=2, validation_tasks=3)
    code, said, _ = _gaps(capsys, tmp_path, body, visible, held, valid)
    assert (code, said.get("refused_because")) == (1, "held_out_unchecked")


def test_a_vector_that_left_out_other_tasks_than_the_record_flags_is_refused(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible, held, valid = _measured_all(tmp_path, made)
    # The record replaced by another that flags another task: the vector is not its count.
    api(f"{CHECKS}.check_path")(made.store, "control", made.version).unlink()
    record_check(made.store, made.version, [made.tasks["held_out"][1].id])
    body = design(made, visible, held_out_tasks=2, validation_tasks=3)
    code, said, _ = _gaps(capsys, tmp_path, body, visible, held, valid)
    assert (code, said.get("refused_because")) == (1, "left_out_differs")


def test_the_trend_line_carries_what_was_left_out_and_refuses_a_line_that_left_out_other(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    trend = tmp_path / "gaps.jsonl"
    visible, held, valid = _measured_all(tmp_path, made)
    body = design(made, visible, held_out_tasks=2, validation_tasks=3)
    code, said, _ = _gaps(capsys, tmp_path, body, visible, held, valid, "--append", str(trend))
    assert code == 0, said
    (line,) = api("physgate.evaluation.gaps.read_gap_trend")(
        trend, store=made.store, role="control"
    )
    assert line.held_out_left_out.count == 1
    assert line.held_out_left_out.check_sha256 == _record(made).sha256
    found = api("physgate.evaluation.gaps.measure.measure")(
        api("physgate.evaluation.gaps.measure.GapsDesign").model_validate_json(
            json.dumps({**body, "validation_tasks": None})
        ),
        runs=visible.runs,
        trials=visible.trials,
        held_out=held,
        validation=None,
    )
    other = found.held_out_left_out.model_copy(update={"count": 0, "digests": ()})
    shifted = found.model_copy(update={"held_out_left_out": other, "manifest_ids": ("e" * 64,)})
    shifted = shifted.model_copy(update={"keys": {"held_out": "f" * 64}})
    with pytest.raises(api("physgate.evaluation.gaps.vector.GapsError")) as refused:
        api("physgate.evaluation.gaps.measure.append_gap_line")(trend, shifted)
    assert _reason(refused.value) == "left_out_differs"
