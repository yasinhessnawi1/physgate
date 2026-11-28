"""A cell's raw trials are held to its harness round, whatever rounds and files a person names.

Both arms on the rig, the harness round the real driver. Each raw trial is the pair of one place
of the harness round, found from the entry by the round's own ledger: a second baseline round of
the same pair is refused naming the first, and its one once-more is the only other round it may
have. A raw trial whose harness trial gives no figure is capped from the harness round's own set
of the tier, never from a set a person names, and not before the round has assembled its last
place. The gatherer brings the cell's harness records and each pair's one raw record together.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import PRICES, SCORED, Rig, StandInArm, make_rig, setup_for
from test_the_two_arms_wait_for_the_usage_limit_alike_and_count_a_pair_once import _installed

from physgate.evaluation.baseline.audit import audit_raw
from physgate.evaluation.baseline.gather import gather
from physgate.evaluation.baseline.runner import BaselineError, RunSet, run_baseline
from physgate.evaluation.harness_round import HARNESS_ROUNDS, ROUND_RECORD, run_round
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers.store import withheld_root

UNREADABLE = {**SCORED, "passed": "yes"}


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _ledger(rig: Rig) -> list[dict[str, Any]]:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])
    return [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]


def _runs(path: Path) -> RunSet:
    runs = RunSet.model_validate_json(path.read_bytes())
    for entry in runs.trials:
        _installed(Path(entry.run_dir))
    return runs


def _raw(rig: Rig, runs: RunSet, out: Path, arm: StandInArm | None = None, **how: Any) -> Any:  # noqa: ANN401
    try:
        return run_baseline(
            store=rig.made.store,
            role="control",
            version=rig.made.version,
            runs=runs,
            out=out,
            setup_for=setup_for,
            score=_score,
            prices=load_price_sheet(PRICES),
            arm=arm or StandInArm(),
            sleep=lambda _s: None,
            **how,
        )
    except BaselineError as exc:
        return exc


def _id(out: Path) -> str:
    return str(json.loads((out / "ledger.jsonl").read_text().splitlines()[0])["round"])


def _because(outcome: Any) -> str | None:  # noqa: ANN401
    return outcome.context.get("refused_because") if isinstance(outcome, BaselineError) else None


def test_a_harness_trial_has_one_raw_round_and_one_once_more_and_the_cell_gathers_them(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    rig = make_rig(tmp_path_factory.mktemp("trial"))
    raws = tmp_path_factory.mktemp("raws")
    status, _ = run_round(rig.inputs(), driver=rig.driver(), scorer=_score, sleep=lambda _: None)
    assert status == "done"
    out = rig.root / "out"
    zero = _runs(out / "trials" / "0000.runs.json")
    one = _runs(out / "trials" / "0001.runs.json")
    assert _because(_raw(rig, zero, raws / "first")) is None
    # The same one-entry set given to a second round, and the entry in the tier's whole set.
    again = _raw(rig, zero, raws / "second")
    assert _because(again) == "pair_recorded"
    assert again.context["earlier_round"] == _id(raws / "first")
    assert _because(_raw(rig, _runs(out / "visible.runs.json"), raws / "all")) == "pair_recorded"
    # A round stopped for a cause, its one once-more, and no second.
    stopped = _raw(rig, one, raws / "stopped", StandInArm(answered={1: "claude-other-1"}))
    assert _because(stopped) == "pair_differs"
    once = _raw(rig, one, raws / "once", rerun_of=raws / "stopped")
    assert _because(once) is None, once
    twice = _raw(rig, one, raws / "twice", rerun_of=raws / "stopped")
    assert (_because(twice), twice.context["why"]) == ("rerun_refused", "rerun_twice")
    assert twice.context["earlier_round"] == _id(raws / "once")
    plain = _raw(rig, one, raws / "plain")
    assert (_because(plain), plain.context["earlier_round"]) == (
        "pair_recorded",
        _id(raws / "once"),
    )
    gathered = gather(rig.made.store, "control", rig.made.version, _runs(out / "visible.runs.json"))
    assert sorted(gathered.raw_rounds) == sorted([_id(raws / "first"), _id(raws / "once")])
    assert [r.arm for r in gathered.harness + gathered.raw] == ["harness"] * 2 + ["raw"] * 2


def test_a_trial_with_no_figure_is_capped_from_its_harness_round_s_own_cell(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    rig = make_rig(tmp_path_factory.mktemp("cell"))
    raws = tmp_path_factory.mktemp("raws")
    calls = [0]

    def bad(_t: Any, _a: Path) -> dict[str, Any]:  # noqa: ANN401
        calls[0] += 1
        return dict(UNREADABLE if calls[0] == 2 else SCORED)

    inputs = rig.inputs(trials=2, tasks=3)
    driver = rig.driver(infra={2, 3, 4, 5, 6, 7})
    status, _ = run_round(inputs, driver=driver, scorer=bad, sleep=lambda _: None)
    assert status == "done"
    ledger = _ledger(rig)
    order = {p["index"]: p for p in ledger[0]["order"]}
    assembled = [x for x in ledger if x["kind"] == "assembled"]
    excluded = [x for x in ledger if x["kind"] == "excluded"]
    none = [x for x in assembled if x["harness_total"] is None]
    assert none and excluded, "the rig gave a trial with no figure and an excluded draw"
    target = none[0]
    brief = order[target["index"]]["brief_sha256"]
    want = max(
        x["harness_total"]
        for x in assembled
        if order[x["index"]]["brief_sha256"] == brief and x["harness_total"] is not None
    )
    out = rig.root / "out"
    own = _runs(out / "trials" / f"{target['index']:04d}.runs.json")
    whole = _runs(out / "visible.runs.json")
    others = [e for e in whole.trials if e.run_dir != own.trials[0].run_dir]
    # A cell a person names that is not the round's own refuses the round: the trial and one
    # other task's trial; the trial and the draw the round excluded.
    for name, trials in (
        ("chosen", [own.trials[0], others[-1]]),
        ("excluded", [own.trials[0], {"run_dir": excluded[0]["run_dir"], "trial": 7}]),
    ):
        given = RunSet.model_validate_json(
            json.dumps({"format": 1, "trials": [_entry(t) for t in trials]})
        )
        refused = _raw(rig, own, raws / name, cell=given)
        assert _because(refused) == "cell_not_the_round_s", (name, refused)
    arm = StandInArm()
    done = _raw(rig, own, raws / "own", arm)
    assert _because(done) is None, done
    assert [cap for _, cap, _ in arm.calls] == [want]
    cap = json.loads(next((raws / "own").glob("work/0000-*/harness/cap.json")).read_bytes())
    assert (cap["rule"], cap["cap"], cap["cell"]["round"]) == (
        "task_largest",
        want,
        ledger[0]["round"],
    )
    assert (
        audit_raw(
            store=rig.made.store,
            role="control",
            version=rig.made.version,
            runs=own,
            out=raws / "own",
            prices=load_price_sheet(PRICES),
            score=_score,
        )
        == []
    )


def _entry(trial: Any) -> dict[str, Any]:  # noqa: ANN401
    return trial if isinstance(trial, dict) else trial.model_dump(mode="json")


def test_a_trial_with_no_figure_is_refused_until_its_harness_round_s_last_place(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    rig = make_rig(tmp_path_factory.mktemp("early"))
    raws = tmp_path_factory.mktemp("raws")
    inputs = rig.inputs(trials=2, tasks=2, seed_base=1, order_seed=1124)
    driver = rig.driver(infra=set(range(1, 20)))
    status, summary = run_round(inputs, driver=driver, scorer=_score, sleep=lambda _: None, only=0)
    assert status == "trial_assembled"
    sheet = summary["trial"]
    assert sheet["raw_pair"] == "at_cell_end", sheet
    refused = _raw(rig, _runs(Path(sheet["runs"])), raws / "early")
    assert _because(refused) == "cell_not_ended"
    assert refused.context["places_left"] == "1,2,3"
