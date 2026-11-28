"""A trial whose own records say its answer is not to be trusted is run once more, and no more.

Decided by the field of the excluded record's reason alone (an instrument's fault, not a leak),
before anyone reads a score: the draw is named in the ledger with its reason and spend on an
``excluded`` line and left where it lies for the exposure scan, in no run set and no cap; the
trial is run again into a fresh directory with the same seed, and the re-run's record is the
trial's, naming the draw it replaced. A second such exclusion is kept as the trial's record, and
nothing runs a third time. An exposure, or a reason nobody enumerated, is never run again. The
trial's one more go of the machine's rule is one per trial: a draw that spent it leaves none for
its re-run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig

from physgate.evaluation.baseline.runner import RunSet
from physgate.evaluation.harness_round import HARNESS_ROUNDS, ROUND_RECORD, run_round
from physgate.evaluation.harness_round_reruns import rerun_cause
from physgate.evaluation.tiers.store import withheld_root

#: A score whose verdict is not a bool, which the scorer never writes: the record excludes it.
UNREADABLE = {**SCORED, "passed": "yes"}


def _scorer(bad: set[int]) -> Any:  # noqa: ANN401
    calls = [0]

    def score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
        calls[0] += 1
        return dict(UNREADABLE if calls[0] in bad else SCORED)

    return score


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (_place(rig) / "ledger.jsonl").read_text().splitlines()]


def _round(rig: Rig, bad: set[int], **driver: Any) -> tuple[str, dict[str, Any]]:  # noqa: ANN401
    status, summary = run_round(
        rig.inputs(trials=1),
        driver=rig.driver(**driver),
        scorer=_scorer(bad),
        sleep=lambda _: None,
    )
    return status, summary


def test_an_untrusted_draw_is_named_and_the_trial_run_once_more_with_the_same_seed(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, {1})
    assert status == "done"
    lines = _ledger(rig)
    kinds = [(x["kind"], x.get("attempt")) for x in lines[1:] if x["kind"] != "ended"]
    assert kinds == [("placed", 1), ("excluded", 1), ("placed", 2), ("assembled", 2)]
    excluded = lines[2]
    assert (excluded["field"], excluded["by"]) == ("score", "rule")
    assert excluded["reason"].startswith("score:")
    assert excluded["tokens"] > 0 and excluded["once_more_spent"] is False
    first, second = (x for x in lines if x["kind"] == "placed")
    assert first["seed"] == second["seed"]
    # The re-run's placed line is the first's, for its own attempt, naming the draw it follows.
    assert second == {
        **first,
        "attempt": 2,
        "run_id": first["run_id"][:-1] + "2",
        "run_dir": first["run_dir"][:-1] + "2",
        "after_exclusion": 1,
    }
    assert Path(excluded["run_dir"]).is_dir(), "the draw stays where it lies"
    assembled = [x for x in lines if x["kind"] == "assembled"][-1]
    assert assembled["outcome"] == "pass"
    assert assembled["rerun_of"] == {
        "attempt": 1,
        "run_id": excluded["run_id"],
        "run_dir": excluded["run_dir"],
        "field": "score",
        "reason": excluded["reason"],
    }
    # The draw is in no run set: the tier's and the trial's name the re-run alone.
    out = rig.root / "out"
    for where in (out / "visible.runs.json", out / "trials" / "0000.runs.json"):
        named = RunSet.model_validate_json(where.read_bytes())
        assert [e.run_dir for e in named.trials] == [assembled["run_dir"]]
    sheet = json.loads((rig.root / "out" / "trials" / "0000.trial.json").read_bytes())
    assert sheet["rerun_of"] == assembled["rerun_of"]
    assert (sheet["excluded"], sheet["class"]) == (None, None)
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    assert [x["run_id"] for x in record["excluded_runs"]] == [excluded["run_id"]]
    assert record["trials"][0]["rerun_of"] == assembled["rerun_of"]
    assert summary["excluded_runs"] == 1


def test_a_second_untrusted_draw_is_kept_as_the_trial_s_record_and_none_runs_a_third_time(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, _summary = _round(rig, {1, 2})
    assert status == "done"
    lines = _ledger(rig)
    assert len([x for x in lines if x["kind"] == "placed"]) == 2
    assembled = [x for x in lines if x["kind"] == "assembled"][-1]
    assert (assembled["kind"], assembled["attempt"], assembled["outcome"]) == (
        "assembled",
        2,
        "excluded",
    )
    sheet = json.loads((rig.root / "out" / "trials" / "0000.trial.json").read_bytes())
    assert sheet["excluded"].startswith("score:") and sheet["class"] == "untrusted"


def test_a_draw_that_spent_the_one_more_go_leaves_none_for_its_re_run(tmp_path: Path) -> None:
    # The first draw's sessions end on the machine until the run halts, it is resumed (the one
    # more go), and its answer's score cannot be read; the re-run's halt then has no resume left.
    rig = make_rig(tmp_path)
    status, _summary = _round(rig, {1}, infra={1, 2, 4, 5})
    lines = _ledger(rig)
    (excluded,) = [x for x in lines if x["kind"] == "excluded"]
    assert excluded["once_more_spent"] is True
    assembled = [x for x in lines if x["kind"] == "assembled"][-1]
    assert (assembled["attempt"], assembled["outcome"], assembled["unscored"]) == (
        2,
        "unscored",
        True,
    )
    assert status == "done_without_caps"


@pytest.mark.parametrize(
    ("reason", "arm", "cause"),
    [
        ("stream: session s's stream is gone", "harness", "untrusted"),
        ("session: s never ended, so its stream was never scanned", "harness", "untrusted"),
        (
            "held_out_canaries: the task is held out and the run did not look for its canary",
            "harness",
            "untrusted",
        ),
        ("run: the run has not ended", "harness", "untrusted"),
        ("events: the run's event log is empty", "harness", "untrusted"),
        ("leftover_read: session s's stream was never scanned", "harness", "untrusted"),
        ("score: the verdict is not a bool", "harness", "untrusted"),
        ("canary: the task's own canary showed in a stream of the run", "harness", "exposure"),
        ("incident: the run recorded a held-out read (event 9)", "harness", "exposure"),
        ("end: watch_failed; the watch could not hold the session to its cap", "raw", "untrusted"),
        ("sentinel_after_stop: the end check refused the session", "raw", "untrusted"),
        (
            "held_out_seen: the record does not say whether a held-out canary showed",
            "raw",
            "exposure",
        ),
        ("end: anything", "harness", "unknown"),
        ("nothing anyone enumerated", "raw", "unknown"),
    ],
)
def test_whether_a_draw_is_run_again_is_read_from_its_reason_s_field_alone(
    reason: str, arm: str, cause: str
) -> None:
    assert rerun_cause(reason, arm) == cause  # type: ignore[arg-type]
