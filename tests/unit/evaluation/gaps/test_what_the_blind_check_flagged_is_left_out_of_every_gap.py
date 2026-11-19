"""What a version's blind check flagged is left out of every held-out count, rate, gap and interval.

The held-out vector is written from the runs of the tasks the check did not flag: a flagged task's
runs and records are left out with it, and the vector, beneath the role's withheld root, says how
many and which, by digest, with the check record's digest and its source. Every tier's figure is
of the whole tier but what was left out: a run set that leaves a task of it unrun is refused, for
each of the three tiers. A version with no check record is not scored. ``physgate gaps`` holds the
vector to the record as it reads now and carries beside its figures how many were left out, the
record's digest and its source, never which tasks (a task's id may be guessed, and its digest
would then say which was flagged); it says so in words in the held-out rate, both gaps' words and
the notes. The trend line carries the same, and two lines of one version that name different
records are refused; a line written before lines carried it is not read. Every form of a vector
that carries what it left out is held to it.
"""

from __future__ import annotations

import hashlib
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
    write_records,
    write_runs,
)

from physgate.cli import main
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import canonical_json, id_digest

WRITE = "physgate.evaluation.tiers.measure.write_vector"
CENSUS = "physgate.evaluation.tiers.measure.census"
CHECKS = "physgate.evaluation.tiers.checks"
GAPS_ERROR = "physgate.evaluation.gaps.vector.GapsError"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    # Held-out task 0 is flagged: every row runs it, and it is left out.
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


def _said(made: StandInStore, source: str = "check") -> dict[str, Any]:
    """What a person may read of what was left out: never a digest of a task."""
    return {"count": 1, "check_sha256": _record(made).sha256, "source": source}


def _no_flagged_digest(made: StandInStore, text: str) -> None:
    for task in made.tasks["held_out"]:
        assert task.id not in text, "a held-out task is named"
        assert id_digest(task.id) not in text, "a task's digest is said where a person reads"


def test_the_held_out_vector_leaves_out_the_flagged_task_and_says_which(
    tmp_path: Path, made: StandInStore
) -> None:
    held = measured(made, "held_out", tmp_path / "h")
    body = json.loads(_vector(made, "held_out", held).read_text())
    assert len(body["tasks"]) == 7, "a flagged task was counted"
    assert body["left_out"] == {
        "count": 1,
        "digests": [id_digest(made.tasks["held_out"][0].id)],
        "check_sha256": _record(made).sha256,
        "source": "check",
    }
    assert all(t["trials"] == 2 for t in body["tasks"])
    for task in made.tasks["held_out"]:
        assert task.id not in json.dumps(body) and task.brief not in json.dumps(body)


def test_a_flagged_task_with_no_run_leaves_the_tier_covered(
    tmp_path: Path, made: StandInStore
) -> None:
    held = measured(made, "held_out", tmp_path / "h")
    runs = json.loads(held.runs.read_text())["trials"][2:]
    records = [json.loads(line) for line in held.trials.read_text().splitlines()][2:]
    shorter = Measured(
        write_runs(held.runs, [(Path(r["run_dir"]), r["trial"]) for r in runs]),
        write_records(held.trials, records),
        held.run_dirs[2:],
        held.tasks[1:],
    )
    assert len(json.loads(_vector(made, "held_out", shorter).read_text())["tasks"]) == 7


@pytest.mark.parametrize("tier", ["visible", "validation", "held_out"])
def test_a_run_set_that_leaves_a_task_of_the_tier_unrun_is_refused(
    tmp_path: Path, made: StandInStore, tier: str
) -> None:
    # Every task of the tier but its last; held out, the flagged task 0 is among those run.
    short = measured(made, tier, tmp_path / "s", tasks=7)
    before = _registered(made)
    with pytest.raises(api(GAPS_ERROR)) as refused:
        api(CENSUS)(made.store, "control", made.version, tier, short.runs, short.trials)
    assert _reason(refused.value) == "tier_not_covered", "a part of a tier was counted"
    assert "1 task(s)" in str(refused.value)
    _no_flagged_digest(made, str(refused.value))
    if tier != "visible":
        with pytest.raises(api(GAPS_ERROR)):
            _vector(made, tier, short)
        assert _registered(made) == before, "a part of a tier was counted as a measurement"


def test_the_validation_vector_is_counted_whole_and_leaves_nothing_out(
    tmp_path: Path, made: StandInStore
) -> None:
    body = json.loads(
        _vector(made, "validation", measured(made, "validation", tmp_path / "w")).read_text()
    )
    assert len(body["tasks"]) == 8 and body.get("left_out") is None


def test_no_held_out_vector_is_written_for_a_version_with_no_check_record(tmp_path: Path) -> None:
    made = stand_in_store(tmp_path / "u", checked=False)
    held = measured(made, "held_out", tmp_path / "h")
    before = _registered(made)
    with pytest.raises(api(GAPS_ERROR)) as refused:
        _vector(made, "held_out", held)
    assert _reason(refused.value) == "held_out_unchecked", "an unchecked tier was scored"
    assert _registered(made) == before, "a measurement was counted of an unchecked tier"
    assert not (withheld_root(made.store, "control") / "gaps").exists()


def test_a_tier_whose_every_task_was_flagged_counts_nothing(tmp_path: Path) -> None:
    made = stand_in_store(tmp_path / "all", flagged=range(8))
    held = measured(made, "held_out", tmp_path / "h")
    before = _registered(made)
    with pytest.raises(api(GAPS_ERROR)) as refused:
        _vector(made, "held_out", held)
    assert _reason(refused.value) == "nothing_counted", "a tier of flagged tasks was counted"
    assert _registered(made) == before


def test_a_record_that_flags_no_task_of_the_tier_refuses_the_vector(tmp_path: Path) -> None:
    made = stand_in_store(tmp_path / "x", checked=False)
    record_check(made.store, made.version, [made.tasks["visible"][0].id], all_yes=7)
    with pytest.raises(api(GAPS_ERROR)) as refused:
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
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    valid = _vector(made, "validation", measured(made, "validation", tmp_path / "w"))
    return visible, held, valid


def test_the_gaps_count_the_unflagged_tasks_and_say_how_many_were_left_out_beside_every_figure(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible, held, valid = _measured_all(tmp_path, made)
    code, said, out = _gaps(capsys, tmp_path, design(made, visible), visible, held, valid)
    assert code == 0, said
    # Hand table (gap_fixtures.PASSES): held out passes task 0, trial 0 only; task 0 is the one
    # flagged, so the seven counted tasks pass nothing.
    assert (said["held_out"]["passed"], said["held_out"]["n"]) == (0, 14)
    assert (said["validation"]["n"], said["visible"]["n"]) == (16, 16), "another tier was cut"
    assert said["held_out_left_out"] == _said(made), "what was left out is not said, or is named"
    words = "1 held-out task left out as the blind check flagged (its check's own record)"
    assert words in said["held_out"]["rate"], "the held-out rate is shown without what it left"
    for gap in ("reward_hacking", "optimiser_overfit"):
        assert words in said[gap]["words"], "a gap is shown without what it left out"
    assert any(n.startswith("held out") and words in n for n in said["notes"])
    _no_flagged_digest(made, out)


def test_a_check_that_flagged_none_is_said_beside_the_figures_all_the_same(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    made = stand_in_store(tmp_path / "none")
    visible, held, valid = _measured_all(tmp_path, made)
    code, said, _ = _gaps(capsys, tmp_path, design(made, visible), visible, held, valid)
    assert code == 0, said
    assert said["held_out_left_out"]["count"] == 0 and said["held_out"]["n"] == 16
    assert "0 held-out tasks left out" in said["held_out"]["rate"]


def test_an_imported_record_is_said_as_imported_wherever_what_it_left_out_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    made = stand_in_store(tmp_path / "imp", checked=False)
    record_check(
        made.store,
        made.version,
        [made.tasks["held_out"][0].id],
        source="imported",
        pins={"model": "claude-sonnet-5", "claude_version": "2.1.322", "implementer_model": "m"},
        kept={"session_id": "s-1", "stream_sha256": "a" * 64, "bound_by": "tasks_read"},
    )
    trend = tmp_path / "gaps.jsonl"
    visible, held, valid = _measured_all(tmp_path, made)
    assert json.loads(held.read_text())["left_out"]["source"] == "imported"
    code, said, _ = _gaps(
        capsys, tmp_path, design(made, visible), visible, held, valid, "--append", str(trend)
    )
    assert code == 0, said
    assert said["held_out_left_out"] == _said(made, "imported")
    assert "(a record imported from it)" in said["reward_hacking"]["words"]
    (line,) = api("physgate.evaluation.gaps.read_gap_trend")(
        trend, store=made.store, role="control"
    )
    assert line.held_out_left_out.source == "imported"


def test_a_version_with_no_check_record_has_no_gap(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible, held, valid = _measured_all(tmp_path, made)
    api(f"{CHECKS}.check_path")(made.store, "control", made.version).unlink()
    code, said, _ = _gaps(capsys, tmp_path, design(made, visible), visible, held, valid)
    assert (code, said.get("refused_because")) == (1, "held_out_unchecked")


def test_a_vector_that_left_out_other_tasks_than_the_record_flags_is_refused(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible, held, valid = _measured_all(tmp_path, made)
    # The record replaced by another that flags another task: the vector is not its count.
    api(f"{CHECKS}.check_path")(made.store, "control", made.version).unlink()
    record_check(made.store, made.version, [made.tasks["held_out"][1].id])
    code, said, _ = _gaps(capsys, tmp_path, design(made, visible), visible, held, valid)
    assert (code, said.get("refused_because")) == (1, "left_out_differs")


def test_the_trend_line_says_how_many_were_left_out_and_refuses_a_line_of_another_record(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    trend = tmp_path / "gaps.jsonl"
    visible, held, valid = _measured_all(tmp_path, made)
    body = design(made, visible)
    code, said, _ = _gaps(capsys, tmp_path, body, visible, held, valid, "--append", str(trend))
    assert code == 0, said
    _no_flagged_digest(made, trend.read_text())
    (line,) = api("physgate.evaluation.gaps.read_gap_trend")(
        trend, store=made.store, role="control"
    )
    assert line.held_out_left_out.model_dump() == _said(made)
    found = api("physgate.evaluation.gaps.measure.measure")(
        api("physgate.evaluation.gaps.measure.GapsDesign").model_validate_json(
            json.dumps({**body, "validation_tasks": None})
        ),
        runs=visible.runs,
        trials=visible.trials,
        held_out=held,
        validation=None,
    )
    # The same count, another record: one left-out set is one record, compared by its digest.
    other = found.held_out_left_out.model_copy(update={"check_sha256": "d" * 64})
    shifted = found.model_copy(update={"held_out_left_out": other, "manifest_ids": ("e" * 64,)})
    shifted = shifted.model_copy(update={"keys": {"held_out": "f" * 64}})
    with pytest.raises(api(GAPS_ERROR)) as refused:
        api("physgate.evaluation.gaps.measure.append_gap_line")(trend, shifted)
    assert _reason(refused.value) == "left_out_differs"


def test_a_trend_line_written_before_lines_said_what_was_left_out_is_not_read(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    trend = tmp_path / "gaps.jsonl"
    visible, held, valid = _measured_all(tmp_path, made)
    body = design(made, visible)
    code, said, _ = _gaps(capsys, tmp_path, body, visible, held, valid, "--append", str(trend))
    assert code == 0, said
    earlier = json.loads(trend.read_text())
    del earlier["held_out_left_out"]
    trend.write_text(json.dumps(earlier) + "\n")
    with pytest.raises(api(GAPS_ERROR)) as refused:
        api("physgate.evaluation.gaps.read_gap_trend")(trend, store=made.store, role="control")
    assert _reason(refused.value) == "trend_unreadable", "an earlier line was read as this one's"


def _rewritten(path: Path, **changes: Any) -> Path:  # noqa: ANN401
    body = json.loads(path.read_text()) | changes
    body = {k: v for k, v in body.items() if v is not None}
    raw = canonical_json(body)
    out = path.with_name(f"{hashlib.sha256(raw).hexdigest()}.json")
    out.write_bytes(raw)
    return out


@pytest.mark.parametrize(
    ("tier", "changes"),
    [
        ("held_out", {"format": 2}),
        ("held_out", {"format": 1}),
        ("held_out", {"left_out": None}),
        ("validation", {"left_out": "held"}),
    ],
    ids=[
        "an earlier form that carries it",
        "the first form that carries it",
        "a held-out vector of this form that does not",
        "a validation vector that carries it",
    ],
)
def test_every_form_of_a_vector_that_carries_what_it_left_out_is_held_to_it(
    tmp_path: Path, made: StandInStore, tier: str, changes: dict[str, Any]
) -> None:
    from physgate.evaluation.gaps.vector import read_vector

    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    path = held if tier == "held_out" else _vector(made, tier, measured(made, tier, tmp_path / "w"))
    if changes.get("left_out") == "held":
        changes = {"left_out": json.loads(held.read_text())["left_out"]}
    with pytest.raises(api(GAPS_ERROR)) as refused:
        read_vector(_rewritten(path, **changes))
    assert _reason(refused.value) == "vector_unreadable", "a vector not held to what it left out"
