"""An ablation arm is refused unless its parameters take a part away and differ in nothing else.

An arm is given beside the round's reportable parameters: a plain name and an ablation run's
parameters (``ablation: true``, ``reportable: false``, by the configuration's own rule) that take
away at least one part a run takes only as an ablation run, and are the round's in every other
field, so the two arms differ in what is ablated alone; the field that differs is named. It runs
on the visible cell alone, in the registered order. Its file is held by its digest: a restart on
another file, or without the arm, is refused as other inputs are. Every refusal is made before
anything is made.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig

from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    ROUND_RECORD,
    Ablation,
    RoundError,
    run_round,
)
from physgate.evaluation.tiers.store import withheld_root

ARM = "reviewers_off"


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _run(rig: Rig, arm: Ablation | None, **changes: Any) -> tuple[str, dict[str, Any]]:  # noqa: ANN401
    resume = changes.pop("resume", False)
    fields: dict[str, Any] = {"trials": 1, "tasks": 1, "seed_base": 1, "order_seed": 1124}
    fields.update(changes)
    return run_round(
        rig.inputs(ablation=arm, **fields),
        driver=rig.driver(),
        scorer=_score,
        sleep=lambda _: None,
        resume=resume,
        only=0 if not resume else 1,
    )


def _refused(rig: Rig, arm: Ablation | None, **changes: Any) -> RoundError:  # noqa: ANN401
    with pytest.raises(RoundError) as refused:
        _run(rig, arm, **changes)
    if not changes.get("resume"):
        assert not (rig.root / "out").exists(), "a refused start makes nothing"
    return refused.value


@pytest.mark.parametrize("name", ["harness", "raw", "observe", "Reviewers", "a b", "1st", ""])
def test_an_arm_s_name_is_a_plain_word_and_never_an_arm_the_report_reads(
    tmp_path: Path, name: str
) -> None:
    rig = make_rig(tmp_path)
    refused = _refused(rig, Ablation(name, rig.arm_params()))
    assert refused.context["refused_because"] == "ablation_name"


def test_a_protected_tier_is_never_given_an_arm(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    for tiers in (("held_out",), ("validation",)):
        refused = _refused(rig, Ablation(ARM, rig.arm_params()), tiers=tiers)
        assert refused.context["refused_because"] == "ablation_protected_tier"


def test_an_arm_runs_only_in_the_registered_order(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    refused = _refused(rig, Ablation(ARM, rig.arm_params()), order_seed=None)
    assert refused.context["refused_because"] == "ablation_needs_the_order"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"ablation": False}, "ablation_params_not_an_ablation"),
        ({"reportable": True}, "ablation_params_not_an_ablation"),
        ({"ablation": 1}, "ablation_params_not_an_ablation"),
        ({"reviewers": "paired"}, "ablation_ablates_nothing"),
        ({"reviewers": "nobody"}, "ablation_not_built"),
        ({"skills": "sometimes"}, "ablation_not_built"),
    ],
)
def test_an_arm_s_parameters_are_an_ablation_run_s_that_take_a_part_away(
    tmp_path: Path, changes: dict[str, Any], reason: str
) -> None:
    rig = make_rig(tmp_path)
    refused = _refused(rig, Ablation(ARM, rig.arm_params(**changes)))
    assert refused.context["refused_because"] == reason


@pytest.mark.parametrize("name", ["effort", "gate_mode", "design_review", "bounds", "network"])
def test_an_arm_s_parameters_that_differ_in_anything_else_are_refused_naming_the_field(
    tmp_path: Path, name: str
) -> None:
    rig = make_rig(tmp_path)
    given = json.loads(rig.params.read_bytes())
    other: Any = {
        "effort": "low",
        "gate_mode": "observe",
        "design_review": "observe",
        "bounds": {**given["bounds"], "infra_retry_delays_s": [8.0]},
        "network": "open",
    }[name]
    refused = _refused(rig, Ablation(ARM, rig.arm_params(**{name: other})))
    assert refused.context["refused_because"] == "ablation_params_differ"
    assert refused.context["field"] == name


def test_a_field_only_one_of_the_two_names_is_a_difference(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    path = rig.arm_params()
    fields = json.loads(path.read_bytes())
    del fields["effort"]
    path.write_text(json.dumps(fields))
    refused = _refused(rig, Ablation(ARM, path))
    assert (refused.context["refused_because"], refused.context["field"]) == (
        "ablation_params_differ",
        "effort",
    )


def test_an_arm_that_takes_skills_or_hooks_away_is_an_arm_too(tmp_path: Path) -> None:
    # Not only the reviewers: any part a run takes only as an ablation run.
    rig = make_rig(tmp_path)
    status, summary = _run(
        rig, Ablation("skills_off", rig.arm_params(reviewers="paired", skills="off"))
    )
    assert status == "trial_assembled"
    assert "skills_off" in summary["arms"]


def test_an_arm_that_would_re_plan_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, design_review="repair:1")
    refused = _refused(rig, Ablation(ARM, rig.arm_params()))
    assert refused.context["refused_because"] == "ablation_replans"


def test_an_arm_s_parameters_that_cannot_be_read_are_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    for data in (b"{not json", b"[1, 2]"):
        path = rig.root / "bad.json"
        path.write_bytes(data)
        refused = _refused(rig, Ablation(ARM, path))
        assert refused.context["refused_because"] == "ablation_params_unreadable"
    refused = _refused(rig, Ablation(ARM, rig.root / "missing.json"))
    assert refused.context["refused_because"] == "ablation_params_unreadable"


def test_a_restart_on_another_arm_s_file_or_without_the_arm_is_refused_as_other_inputs(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _run(rig, Ablation(ARM, rig.arm_params()), trials=2)
    other = rig.arm_params(name="other", skills="off")
    for arm in (Ablation(ARM, other), None):
        with pytest.raises(RoundError) as refused:
            _run(rig, arm, trials=2, resume=True)
        assert refused.value.context["refused_because"] == "inputs_differ"
        assert "ablation" in refused.value.context["fields"].split(",")


def test_the_round_s_copy_of_the_arm_s_parameters_is_held_to_its_digest(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    _run(rig, Ablation(ARM, rig.arm_params()), trials=2)
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])
    copy = place / f"params.ablation.{ARM}.json"
    assert copy.read_bytes() == rig.arm_params().read_bytes()
    copy.write_text(copy.read_text().replace('"off"', '"generalist"', 1))
    with pytest.raises(RoundError) as refused:
        _run(rig, Ablation(ARM, rig.arm_params()), trials=2, resume=True)
    assert (refused.value.context["refused_because"], refused.value.context["arm"]) == (
        "params_changed",
        ARM,
    )
