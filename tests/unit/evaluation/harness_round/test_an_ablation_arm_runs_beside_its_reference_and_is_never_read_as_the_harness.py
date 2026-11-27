"""An ablation arm runs beside its reference in one order, and is never read as the harness.

A round of the visible cell in the registered order may be given an ablation arm: a name and its
own parameters, an ablation run's that differ from the round's in what they take away alone. Each
(task, trial) of the cell is a unit of two places, the harness trial and the arm's trial of the
same task and seed: the units keep the cell's order (the same shuffle as a round without the arm),
and the same generator then orders each unit's two places by one shuffle, unit by unit. Either
arm's place is taken on by ``--only``. The arm's trials are held to the harness's rules; they go
into the arm's own files alone, never into a tier's set, the combined set or the cap rule's
figures, no raw trial is paired with one, and the round's record and line count the arm apart.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig

from physgate.cli import main
from physgate.evaluation import harness_round
from physgate.evaluation.baseline.runner import BaselineError, RunSet, plan
from physgate.evaluation.harness_round import (
    COMBINED,
    HARNESS_ROUNDS,
    ROUND_RECORD,
    Ablation,
    run_round,
)
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.measure import census
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import id_digest
from physgate.orchestrator.run_config import load_run_config

ARM = "reviewers_off"


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (_place(rig) / "ledger.jsonl").read_text().splitlines()]


def _inputs(rig: Rig, *, arm: bool = True, **changes: Any) -> Any:  # noqa: ANN401
    fields: dict[str, Any] = {"trials": 2, "tasks": 2, "seed_base": 1, "order_seed": 1124}
    if arm:
        fields["ablation"] = Ablation(ARM, rig.arm_params())
    fields.update(changes)
    return rig.inputs(**fields)


def _call(rig: Rig, only: int | None, **how: Any) -> tuple[str, dict[str, Any]]:  # noqa: ANN401
    arm = how.pop("arm", True)
    status, summary = run_round(
        _inputs(rig, arm=arm),
        driver=how.pop("driver", None) or rig.driver(),
        scorer=_score,
        sleep=lambda _: None,
        only=only,
        **how,
    )
    return status, summary


def _id_of(rig: Rig, brief_sha256: str) -> str:
    task = next(
        t
        for t in rig.made.tasks["visible"]
        if hashlib.sha256(t.brief.encode()).hexdigest() == brief_sha256
    )
    return id_digest(task.id)


def _drawn(rig: Rig, tasks: int, trials: int) -> tuple[list[tuple[str, int]], list[Any]]:
    """The cell's units and the places, as the registered rule's own words give them."""
    digests = sorted(id_digest(t.id) for t in rig.made.tasks["visible"])[:tasks]
    units = sorted((d, n) for d in digests for n in range(trials))
    drawn = random.Random("1124:order:control_visible")
    drawn.shuffle(units)
    places = []
    for digest, trial in units:
        parts = ["harness", ARM]
        drawn.shuffle(parts)
        places += [(digest, trial, part) for part in parts]
    return list(units), places


def _whole(rig: Rig, **how: Any) -> tuple[str, dict[str, Any]]:  # noqa: ANN401
    """Every place of the order, one call each, as a launch script takes them."""
    driver = how.pop("driver", None) or rig.driver()
    status, summary = "", {}
    for place in range(8):
        status, summary = _call(rig, place, resume=place > 0, driver=driver, **how)
    return status, summary


def _set(path: Path) -> list[tuple[str, int, bool]]:
    """A run set's trials by their brief, number and whether each is an ablation run."""
    runs = RunSet.model_validate_json(path.read_bytes())
    out = []
    for entry in runs.trials:
        config = load_run_config(Path(entry.run_dir) / "run.json")
        out.append((config.brief_sha256, entry.trial, config.ablation))
    return out


# -- the order --------------------------------------------------------------------------------


def test_each_unit_keeps_the_cell_s_order_and_its_two_places_are_shuffled_by_the_same_generator(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _call(rig, 0)
    header = _ledger(rig)[0]
    order = header["order"]
    units, places = _drawn(rig, 2, 2)
    got = [(_id_of(rig, p["brief_sha256"]), p["trial"], p.get("arm", "harness")) for p in order]
    assert got == places
    assert [p["index"] for p in order] == list(range(8))
    # Both arms' trials of a task are seeded by the trial's number: the arm's is its reference's.
    assert [p["seed"] for p in order] == [p["trial"] + 1 for p in order]
    # A harness place is held as it always was; an arm's names the arm.
    assert all("arm" not in p for p in order if (p.get("arm") is None))
    assert sum(1 for p in order if p.get("arm") == ARM) == 4
    # The units' order is the cell's own: the same as a round without the arm.
    harness = [(_id_of(rig, p["brief_sha256"]), p["trial"]) for p in order if "arm" not in p]
    assert harness == units
    other = make_rig(tmp_path / "plain")
    _call(other, 0, arm=False)
    plain = _ledger(other)[0]["order"]
    assert [(_id_of(other, p["brief_sha256"]), p["trial"]) for p in plain] == units
    assert header["inputs"]["ablation"] == {
        "arm": ARM,
        "params_sha256": hashlib.sha256(rig.arm_params().read_bytes()).hexdigest(),
    }
    assert "ablation" not in _ledger(other)[0]["inputs"], "a round without an arm is held as before"


def test_the_shuffle_puts_the_arm_first_in_some_unit_and_second_in_another(tmp_path: Path) -> None:
    # Not a fixed alternation: with the registered seed, at this size, both come first somewhere.
    rig = make_rig(tmp_path)
    _units, places = _drawn(rig, 2, 2)
    firsts = {places[k][2] for k in range(0, len(places), 2)}
    assert firsts == {"harness", ARM}


# -- one place at a time, and what each arm's trial is ------------------------------------------


def test_an_arm_s_place_is_taken_on_alone_its_sheet_saying_no_raw_trial_is_ever_paired(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _units, places = _drawn(rig, 2, 2)
    first_arm = next(k for k, p in enumerate(places) if p[2] == ARM)
    for place in range(first_arm + 1):
        status, summary = _call(rig, place, resume=place > 0)
    assert status == "trial_assembled"
    where = rig.root / "out" / f"ablation.{ARM}" / "trials"
    sheet = json.loads((where / f"{first_arm:04d}.trial.json").read_bytes())
    assert (sheet["arm"], sheet["ablation"], sheet["raw_pair"]) == ("ablation", ARM, "never")
    assert summary["trial"] == {
        "arm": "ablation",
        "ablation": ARM,
        "index": first_arm,
        "runs": str(where / f"{first_arm:04d}.runs.json"),
        "raw_pair": "never",
    }
    runs = RunSet.model_validate_json((where / f"{first_arm:04d}.runs.json").read_bytes())
    (entry,) = runs.trials
    config = load_run_config(Path(entry.run_dir) / "run.json")
    # The arm's own parameters, as an ablation run's: never reportable, its reviewers off.
    assert (config.ablation, config.reportable, config.reviewers) == (True, False, "off")
    assert not (rig.root / "out" / "trials" / f"{first_arm:04d}.runs.json").exists()
    # Every line of the arm's place names the arm; none of a harness place's does.
    for line in _ledger(rig)[1:]:
        if "index" in line:
            assert line.get("arm") == (ARM if places[line["index"]][2] == ARM else None), line


def test_a_whole_round_writes_the_harness_s_sets_as_without_the_arm_and_the_arm_s_apart(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _whole(rig)
    assert status == "done"
    out = rig.root / "out"
    harness = _set(out / "visible.runs.json")
    combined = _set(_place(rig) / COMBINED)
    arm = _set(out / f"ablation.{ARM}.runs.json")
    assert [a for *_, a in harness + combined] == [False] * 8, "an ablation run in a harness set"
    assert [a for *_, a in arm] == [True] * 4
    # The harness's sets are those of the same round without the arm, trial for trial.
    other = make_rig(tmp_path / "plain")
    for place in range(4):
        _call(other, place, resume=place > 0, arm=False)
    plain = _set(other.root / "out" / "visible.runs.json")
    assert harness == plain
    assert combined == _set(_place(other) / COMBINED)
    # The harness's records and per-trial sets name the harness's runs alone.
    records = (out / "visible.trials.jsonl").read_text().splitlines()
    assert len(records) == 4
    arm_records = [
        json.loads(x) for x in (out / f"ablation.{ARM}.trials.jsonl").read_text().splitlines()
    ]
    assert len(arm_records) == 4
    # A review the arm skipped is no review that ran: none is counted, though each log says it.
    assert [r["review"]["reviews"] for r in arm_records] == [0] * 4
    assert all(r["review"]["reviews"] >= 1 for r in map(json.loads, records))
    for entry in RunSet.model_validate_json(
        (out / f"ablation.{ARM}.runs.json").read_bytes()
    ).trials:
        kinds = [
            json.loads(x)["kind"]
            for x in (Path(entry.run_dir) / "events.jsonl").read_text().splitlines()
        ]
        assert "review_skipped" in kinds and "review_ran" not in kinds
    assert sorted(p.name for p in (out / "trials").glob("*.runs.json")) == sorted(
        f"{k:04d}.runs.json" for k, p in enumerate(_ledger(rig)[0]["order"]) if "arm" not in p
    )
    # The round's line and record count each arm apart.
    assert summary["tiers"]["visible"]["trials"] == summary["tiers"]["visible"]["assembled"] == 4
    assert summary["arms"][ARM]["trials"] == summary["arms"][ARM]["assembled"] == 4
    assert summary["arms"][ARM]["pass"] == 4 and summary["arms"][ARM]["dropped"] == 0
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    assert len(record["trials"]) == 4
    assert {t["index"] for t in record["trials"]} == {
        k for k, p in enumerate(_ledger(rig)[0]["order"]) if "arm" not in p
    }
    assert len(record["arms"][ARM]["trials"]) == 4
    assert record["arms"][ARM]["raw_pair"] == "never"
    assert record["arms"][ARM]["dropped"] is None


def test_an_arm_s_trial_is_never_among_the_figures_the_cap_rule_reads(tmp_path: Path) -> None:
    # Every harness trial gives no figure; every arm's trial gives one. The arm's figures are no
    # figure of the cell: the round ends with no cap in it, its no-figure count the harness's.
    rig = make_rig(tmp_path)
    _units, places = _drawn(rig, 2, 2)
    harness_places = {k + 1 for k, p in enumerate(places) if p[2] == "harness"}
    status, summary = _whole(
        rig, driver=rig.driver(fails=dict.fromkeys(harness_places, "invalid_plan"))
    )
    assert status == "done_without_caps"
    assert summary["no_figure"] == {"visible": 4}
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    assert record["no_cap_in_the_cell"] == ["visible"]
    assert all(t["harness_total"] is not None for t in record["arms"][ARM]["trials"])


def test_an_arm_s_trial_with_no_figure_neither_counts_nor_defers_a_raw_pair(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _units, places = _drawn(rig, 2, 2)
    arm_places = {k + 1 for k, p in enumerate(places) if p[2] == ARM}
    status, summary = _whole(
        rig, driver=rig.driver(fails=dict.fromkeys(arm_places, "invalid_plan"))
    )
    assert status == "done"
    assert summary["no_figure"] == {"visible": 0}
    for k in sorted(arm_places):
        sheet = json.loads(
            (
                rig.root / "out" / f"ablation.{ARM}" / "trials" / f"{k - 1:04d}.trial.json"
            ).read_bytes()
        )
        assert sheet["harness_total"] is None and sheet["raw_pair"] == "never"


# -- what refuses the arm's trials --------------------------------------------------------------


def test_the_baseline_and_the_counting_rule_refuse_every_set_of_the_arm(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    _whole(rig)
    out = rig.root / "out"
    sets = [
        out / f"ablation.{ARM}.runs.json",
        *sorted((out / f"ablation.{ARM}" / "trials").glob("*.runs.json")),
    ]
    assert len(sets) == 5
    for path in sets:
        runs = RunSet.model_validate_json(path.read_bytes())
        with pytest.raises(BaselineError) as refused:
            plan(rig.made.store, "control", rig.made.version, runs, base_url=None)
        assert "ablation run" in str(refused.value)
    with pytest.raises(PerRoleError) as uncounted:
        census(
            rig.made.store,
            "control",
            rig.made.version,
            "visible",
            out / f"ablation.{ARM}.runs.json",
            out / f"ablation.{ARM}.trials.jsonl",
        )
    assert uncounted.value.context["refused_because"] == "run_not_measured"


# -- the command --------------------------------------------------------------------------------


def _argv(rig: Rig, only: int, *more: str) -> list[str]:
    return [
        "harness-round",
        *("--store", str(rig.made.store), "--role", "control", "--version", rig.made.version),
        *("--tier", "visible", "--trials", "2", "--seed-base", "1", "--tasks", "2"),
        *("--order-seed", "1124", "--only", str(only)),
        *("--params", str(rig.params), "--run-root", str(rig.run_root)),
        *("--target-from", str(rig.target), "--install", str(rig.root / "install")),
        *("--prices", "2026-10-16", "--out", str(rig.root / "out")),
        *("--ablation", ARM, "--ablation-params", str(rig.arm_params())),
        *more,
    ]


def test_the_command_takes_an_arm_s_place_and_exits_0_with_no_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = make_rig(tmp_path)
    _units, places = _drawn(rig, 2, 2)
    # Every decomposition fails to plan: no trial gives a figure.
    driver = rig.driver(fails=dict.fromkeys(range(1, 20), "invalid_plan"))
    monkeypatch.setattr(harness_round, "CommandDriver", lambda: driver)
    monkeypatch.setattr("physgate.evaluation.harness_round_cli._score", _score)
    for place in range(3):
        more = () if place == 0 else ("--resume",)
        code = main(_argv(rig, place, *more))
        (line,) = capsys.readouterr().out.strip().splitlines()
        said = json.loads(line)["trial"]
        if places[place][2] == ARM:
            assert (code, said["arm"], said["raw_pair"]) == (0, "ablation", "never")
        else:
            assert (code, said["arm"], said["raw_pair"]) == (3, "harness", "at_cell_end")


@pytest.mark.parametrize(
    ("words", "reason"),
    [
        (("--ablation", ARM), "ablation_needs_both"),
        (("--drop-ablation", "out of hours"), "ablation_drop_words"),
        (("--dropped-by", "time_rule"), "ablation_drop_words"),
    ],
)
def test_the_command_refuses_half_of_an_arm_s_words(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], words: tuple[str, ...], reason: str
) -> None:
    rig = make_rig(tmp_path)
    argv = _argv(rig, 0)
    argv = argv[: argv.index("--ablation")] + list(words)
    assert main(argv) == 1
    assert json.loads(capsys.readouterr().out)["refused_because"] == reason
    assert not (rig.root / "out").exists()
