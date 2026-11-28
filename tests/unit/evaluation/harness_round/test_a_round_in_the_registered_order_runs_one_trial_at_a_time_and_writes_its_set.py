"""A round in the registered order runs one trial at a time, and writes each trial's set.

Given an order seed, a round runs one cell: its (id digest, trial) pairs sorted and shuffled once
by ``random.Random("<seed>:order:<suite>")``, trial ``n`` of a task seeded ``seed base + n``. Told
one place of that order, it takes that trial on until it is assembled and stops there, its
one-entry run set and its sheet written, so the launch script runs the raw trial right after it;
only the first place not yet assembled may be named. Every trial's set is written once it is
assembled, in every mode, so an assembled trial is in a set before the round ends. A whole call
with no word runs as it always did, and each tier's run set names each trial by its number within
its task, from 0.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig

from physgate.cli import main
from physgate.evaluation import harness_round
from physgate.evaluation.baseline.runner import RunSet
from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    ROUND_RECORD,
    RoundError,
    run_round,
)
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import id_digest
from physgate.orchestrator.run_config import load_run_config


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _ledger(rig: Rig) -> list[dict[str, Any]]:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])
    return [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]


def _drawn(rig: Rig, tasks: int, trials: int) -> list[tuple[str, int]]:
    """The registered order, as its own words give it: (id digest, trial), sorted, shuffled once."""
    digests = sorted(id_digest(t.id) for t in rig.made.tasks["visible"])[:tasks]
    pairs = sorted((d, n) for d in digests for n in range(trials))
    random.Random("1124:order:control_visible").shuffle(pairs)
    return pairs


def _id_of(rig: Rig, brief_sha256: str) -> str:
    import hashlib

    task = next(
        t
        for t in rig.made.tasks["visible"]
        if hashlib.sha256(t.brief.encode()).hexdigest() == brief_sha256
    )
    return id_digest(task.id)


def _call(rig: Rig, only: int, **how: Any) -> tuple[str, dict[str, Any]]:  # noqa: ANN401
    status, summary = run_round(
        rig.inputs(trials=2, tasks=2, seed_base=1, order_seed=1124),
        driver=how.pop("driver", None) or rig.driver(),
        scorer=_score,
        sleep=lambda _: None,
        only=only,
        **how,
    )
    return status, summary


def test_the_order_is_the_registered_shuffle_and_each_trial_is_seeded_by_its_number(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _call(rig, 0)
    order = _ledger(rig)[0]["order"]
    assert [(_id_of(rig, p["brief_sha256"]), p["trial"]) for p in order] == _drawn(rig, 2, 2)
    assert [p["seed"] for p in order] == [p["trial"] + 1 for p in order]
    assert [p["index"] for p in order] == list(range(4))
    assert _ledger(rig)[0]["inputs"]["order_seed"] == 1124


def test_one_place_is_taken_on_alone_and_its_one_entry_set_is_written_at_once(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _call(rig, 0)
    assert status == "trial_assembled"
    lines = _ledger(rig)
    assert {x["index"] for x in lines if x["kind"] == "placed"} == {0}
    trials = rig.root / "out" / "trials"
    runs = RunSet.model_validate_json((trials / "0000.runs.json").read_bytes())
    (assembled,) = [x for x in lines if x["kind"] == "assembled"]
    order = lines[0]["order"]
    assert [(e.run_dir, e.trial) for e in runs.trials] == [
        (assembled["run_dir"], order[0]["trial"])
    ]
    sheet = json.loads((trials / "0000.trial.json").read_bytes())
    assert (sheet["index"], sheet["trial"], sheet["seed"]) == (
        0,
        order[0]["trial"],
        order[0]["trial"] + 1,
    )
    assert sheet["raw_pair"] == "now" and sheet["no_figure"] is None
    assert sheet["arm"] == "harness"
    assert "outcome" not in sheet and "score" not in json.dumps(sheet)
    assert summary["trial"] == {
        "arm": "harness",
        "index": 0,
        "runs": sheet["runs"],
        "raw_pair": "now",
    }
    assert not (rig.root / "out" / "visible.runs.json").exists(), "the round has not ended"


def test_only_the_first_place_not_yet_assembled_may_be_named(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    with pytest.raises(RoundError) as fresh:
        _call(rig, 1)
    assert fresh.value.context["refused_because"] == "only_out_of_order"
    assert not (rig.root / "out").exists(), "a refused fresh call makes nothing"
    _call(rig, 0)
    with pytest.raises(RoundError) as ahead:
        _call(rig, 2, resume=True)
    assert ahead.value.context["refused_because"] == "only_out_of_order"
    with pytest.raises(RoundError) as beyond:
        _call(rig, 4, resume=True)
    assert beyond.value.context["refused_because"] == "only_not_in_the_order"
    # A place already assembled is only said again: nothing is run.
    status, summary = _call(rig, 0, resume=True)
    assert status == "trial_assembled" and summary["trial"]["index"] == 0
    assert len([x for x in _ledger(rig) if x["kind"] == "placed"]) == 1


def test_the_call_that_assembles_the_last_place_ends_the_round_in_the_order(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    for place in range(4):
        status, _summary = _call(rig, place, resume=place > 0)
    assert status == "done"
    runs = RunSet.model_validate_json((rig.root / "out" / "visible.runs.json").read_bytes())
    order = _ledger(rig)[0]["order"]
    # The tier's set names each trial by its number within its task, in the round's order.
    assert [e.trial for e in runs.trials] == [p["trial"] for p in order]
    briefs = [load_run_config(Path(e.run_dir) / "run.json").brief_sha256 for e in runs.trials]
    assert briefs == [p["brief_sha256"] for p in order]
    assert sorted((p["brief_sha256"], p["trial"]) for p in order) == sorted(
        (b, n) for b in {p["brief_sha256"] for p in order} for n in (0, 1)
    )


def test_a_trial_with_no_figure_says_its_raw_pair_waits_for_the_cell_s_end(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _call(rig, 0, driver=rig.driver(fails={1: "invalid_plan"}))
    assert status == "trial_assembled"
    assert summary["trial"]["raw_pair"] == "at_cell_end"
    sheet = json.loads((rig.root / "out" / "trials" / "0000.trial.json").read_bytes())
    assert sheet["harness_total"] is None
    assert sheet["no_figure"]["because"] == "no_role_session"


def test_the_registered_order_runs_one_cell(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    with pytest.raises(RoundError) as raised:
        run_round(
            rig.inputs(tiers=("visible", "validation"), order_seed=1124),
            driver=rig.driver(),
            scorer=_score,
        )
    assert raised.value.context["refused_because"] == "order_one_cell"


def test_a_whole_call_with_no_word_runs_as_before_and_numbers_each_trial_from_0(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, _summary = run_round(
        rig.inputs(trials=2, tasks=2), driver=rig.driver(), scorer=_score, sleep=lambda _: None
    )
    assert status == "done"
    header = _ledger(rig)[0]
    assert "order_seed" not in header["inputs"]
    order = header["order"]
    # The driver's own order: tasks by their brief's digest, a task's trials back to back, the
    # seed the base and the place.
    assert [p["brief_sha256"] for p in order] == sorted(p["brief_sha256"] for p in order)
    assert [p["seed"] for p in order] == [100 + p["index"] for p in order]
    runs = RunSet.model_validate_json((rig.root / "out" / "visible.runs.json").read_bytes())
    assert [e.trial for e in runs.trials] == [0, 1, 0, 1]
    # Each trial's set was written as it was assembled.
    sets = sorted(p.name for p in (rig.root / "out" / "trials").glob("*.runs.json"))
    assert sets == [f"{n:04d}.runs.json" for n in range(4)]


@pytest.mark.parametrize(("fails", "code"), [({}, 0), ({1: "invalid_plan"}, 3)])
def test_the_command_takes_the_order_and_the_place_and_exits_by_the_raw_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fails: dict[int, str],
    code: int,
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver(fails=fails)
    monkeypatch.setattr(harness_round, "CommandDriver", lambda: driver)
    monkeypatch.setattr("physgate.evaluation.harness_round_cli._score", _score)
    argv = [
        "harness-round",
        *("--store", str(rig.made.store), "--role", "control", "--version", rig.made.version),
        *("--tier", "visible", "--trials", "2", "--seed-base", "1", "--tasks", "2"),
        *("--order-seed", "1124", "--only", "0"),
        *("--params", str(rig.params), "--run-root", str(rig.run_root)),
        *("--target-from", str(rig.target), "--install", str(rig.root / "install")),
        *("--prices", "2026-10-16", "--out", str(rig.root / "out")),
    ]
    assert main(argv) == code
    (line,) = capsys.readouterr().out.strip().splitlines()
    said = json.loads(line)
    assert said["status"] == "trial_assembled"
    assert said["trial"]["raw_pair"] == ("now" if code == 0 else "at_cell_end")


def test_a_held_out_cell_with_a_flagged_task_is_ordered_as_the_shuffle_of_its_other_tasks(
    tmp_path: Path,
) -> None:
    import hashlib

    # One held-out task is flagged by the version's blind check: it is no trial of the cell, so
    # the registered order is the shuffle of the other tasks' pairs, never one with it in.
    rig = make_rig(tmp_path, store={"flagged": (0,)})
    flagged = id_digest(rig.made.tasks["held_out"][0].id)
    inputs = rig.inputs(tiers=("held_out",), trials=3, tasks=None, order_seed=1124, seed_base=1)
    status, _summary = run_round(
        inputs, driver=rig.driver(), scorer=_score, sleep=lambda _: None, only=0
    )
    assert status == "trial_assembled"
    order = _ledger(rig)[0]["order"]
    by_brief = {
        hashlib.sha256(t.brief.encode()).hexdigest(): id_digest(t.id)
        for t in rig.made.tasks["held_out"]
    }
    got = [(by_brief[p["brief_sha256"]], p["trial"]) for p in order]
    others = sorted(d for d in by_brief.values() if d != flagged)
    pairs = sorted((d, n) for d in others for n in range(3))
    random.Random("1124:order:control_held_out").shuffle(pairs)
    assert got == pairs
    assert len(order) == 3 * (len(rig.made.tasks["held_out"]) - 1)
    assert flagged not in {d for d, _n in got}
    assert all(p["seed"] == p["trial"] + 1 for p in order)
