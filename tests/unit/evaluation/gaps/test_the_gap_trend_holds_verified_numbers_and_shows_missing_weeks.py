"""The gap trend: one writer (``gaps --append``), one reader (``read_gap_trend``), missing weeks.

``--append`` writes one line per run set, naming the vectors' keys and the version's measurement
count; it writes no register line of its own, since each vector's writing was the look. The
reader checks every line, refuses a cut line, a run set already in the file and a line whose
vectors were measured on another version, verifies each key against the register and gives a
line's numbers only when every key is there. What it returns holds no register line, no path
beneath a withheld root, no name and no reason. ``gap_weeks`` shows a week with no line as
missing, never filled in. The counting rule's per-task fields are the census of ``DRIFT``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from gap_fixtures import Measured, StandInStore, api, design, measured, stand_in_store

from physgate.cli import main
from physgate.evaluation.observe.compare import DRIFT
from physgate.evaluation.tiers.store import withheld_root

WRITE = "physgate.evaluation.tiers.measure.write_vector"
READ = "physgate.evaluation.gaps.read_gap_trend"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "st")


def _vector(made: StandInStore, tier: str, m: Measured) -> Path:
    withheld = withheld_root(made.store, "control")
    key = api(WRITE)(withheld, version=made.version, tier=tier, runs=m.runs, trials=m.trials)
    return withheld / "gaps" / f"{key}.json"


def _append(
    tmp_path: Path, made: StandInStore, trend: Path, name: str = "a"
) -> tuple[int, dict[str, Any]]:
    visible = measured(made, "visible", tmp_path / f"v{name}")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / f"h{name}"))
    valid = _vector(made, "validation", measured(made, "validation", tmp_path / f"w{name}"))
    path = tmp_path / f"design-{name}.json"
    path.write_text(json.dumps(design(made, visible)))
    argv = ["gaps", "--design", str(path), "--runs", str(visible.runs), "--trials"]
    argv += [str(visible.trials), "--held-out", str(held), "--validation", str(valid)]
    code = main([*argv, "--append", str(trend)])
    return code, {"argv": argv, "keys": {held.stem, valid.stem}}


def _registered(made: StandInStore) -> int:
    lines = api("physgate.evaluation.tiers.exposure.register_lines")(made.store, "control")
    return len(lines)


def test_append_writes_one_line_naming_its_keys_and_no_register_line(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    valid = _vector(made, "validation", measured(made, "validation", tmp_path / "w"))
    before = _registered(made)
    path = tmp_path / "design.json"
    path.write_text(json.dumps(design(made, visible)))
    argv = ["gaps", "--design", str(path), "--runs", str(visible.runs), "--trials"]
    argv += [str(visible.trials), "--held-out", str(held), "--validation", str(valid)]
    assert main([*argv, "--append", str(trend)]) == 0
    assert _registered(made) == before, "--append wrote a register line of its own"
    written = trend.read_text().splitlines()
    assert len(written) == 1
    line = json.loads(written[0])
    assert set(line["keys"].values()) == {held.stem, valid.stem}
    assert line["measurements"] == 2, "the line does not carry the version's count"
    (got,) = api(READ)(trend)
    assert got.numbers is not None and got.measurements == 2
    assert got.numbers.reward_hacking.gap == pytest.approx(line["numbers"]["reward_hacking"]["gap"])


def test_the_same_run_set_is_refused_a_second_time(tmp_path: Path, made: StandInStore) -> None:
    trend = tmp_path / "gaps.jsonl"
    code, first = _append(tmp_path, made, trend)
    assert code == 0
    assert main([*first["argv"], "--append", str(trend)]) == 1, "a run set was appended twice"
    assert len(trend.read_text().splitlines()) == 1
    doubled = tmp_path / "doubled.jsonl"
    doubled.write_text(trend.read_text() * 2)
    with pytest.raises(Exception) as caught:
        api(READ)(doubled)
    assert "again" in str(caught.value) or "twice" in str(caught.value)


def test_a_cut_line_is_refused(tmp_path: Path, made: StandInStore) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    trend.write_text(trend.read_text()[:-20])
    with pytest.raises(Exception) as caught:
        api(READ)(trend)
    assert "line" in str(caught.value)


def test_a_line_whose_keys_the_register_lacks_carries_no_number(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    line = json.loads(trend.read_text())
    line["keys"]["held_out"] = "f" * 64
    trend.write_text(json.dumps(line) + "\n")
    (got,) = api(READ)(trend)
    assert got.numbers is None, "a line with no measurement behind it was shown as a number"
    assert got.unverified


def test_a_line_whose_vectors_were_measured_on_another_version_is_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    line = json.loads(trend.read_text())
    line["version"] = "a" * 64
    trend.write_text(json.dumps(line) + "\n")
    with pytest.raises(Exception) as caught:
        api(READ)(trend)
    assert "version" in str(caught.value)


def test_what_the_reader_returns_holds_no_register_line_path_name_or_reason(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    (got,) = api(READ)(trend)
    dumped = got.model_dump_json()
    for word in ("withheld", str(made.store), '"by"', '"reason"', '"prev"', '"kind"'):
        assert word not in dumped, f"the reader returns {word}"
    fields = set(type(got).model_fields)
    assert fields.isdisjoint({"by", "reason", "store", "path", "register"}), fields


def _week_line(line: dict[str, Any], week: str, n: int) -> str:
    line = dict(line, week=week, manifest_ids=[f"{n:064x}"])
    line["keys"] = {k: f"{n + 1:064x}" for k in line["keys"]}
    return json.dumps(line) + "\n"


def test_a_week_with_no_line_is_shown_missing(tmp_path: Path, made: StandInStore) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    line = json.loads(trend.read_text())
    trend.write_text(_week_line(line, "2026-W45", 1) + _week_line(line, "2026-W47", 3))
    lines = api(READ)(trend)
    weeks = api("physgate.evaluation.gaps.gap_weeks")(lines)
    assert [w.week for w in weeks] == ["2026-W45", "2026-W46", "2026-W47"]
    assert [w.missing for w in weeks] == [False, True, False]
    assert weeks[1].lines == ()
    later = api("physgate.evaluation.gaps.gap_weeks")(lines, through=date(2026, 12, 2))
    assert [w.week for w in later][-2:] == ["2026-W48", "2026-W49"] and later[-1].missing


def test_the_per_task_fields_are_the_census_of_drift() -> None:
    per_task = api("physgate.evaluation.tiers.measure.PER_TASK")
    held = api("physgate.evaluation.tiers.measure.HELD_EQUAL")
    assert set(per_task) == {"brief_sha256", "target_head"} and set(per_task) <= set(DRIFT)
    assert tuple(held) == tuple(f for f in DRIFT if f not in per_task)
