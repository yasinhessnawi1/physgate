"""``compare`` classes every field of a run's configuration: none is equal by being overlooked.

Each field, and each kind of model string inside ``models``, sits in exactly one of three lists:
refused when the two runs differ on it (what answered, what was asked and from where), reported
beside the numbers when they differ (what an ablation varies on purpose), or named as never
compared (what names one run, or is measured from fields that are compared). A field added
later with no decision is named by the census, so a new switch or pin cannot compare as equal.

Two runs of different briefs, or from different commits of the target, are not one comparison,
nor are two under different bounds, another always-loaded ceiling, another network setting or
another held-out tier: each is refused, and named.
"""

from __future__ import annotations

from typing import Any

import pytest
from design_review_rig import outcome_of
from orch_helpers import CLEAN_HARNESS, SCRIPTED_BOUNDS, make_config

from physgate.evaluation.observe import compare
from physgate.orchestrator.run_config import ModelStrings, RunConfig
from physgate.oslayer.probe import Absent

DRIFT: tuple[str, ...] = getattr(compare, "DRIFT", ())
PER_RUN: tuple[str, ...] = getattr(compare, "PER_RUN", ())

REFUSED = {
    "models.decomposition",
    "models.roles",
    "models.reviewers",
    "effort",
    "max_output_tokens",
    "thinking_display",
    "role_python",
    "claude_version",
    "binary",
    "git_binary",
    "endpoint",
    "brief_sha256",
    "target_head",
    "bounds",
    "token_ceiling",
    "network",
    "held_out_sha256",
}
REPORTED = {
    "gate_mode",
    "auth",
    "harness",
    "escalation_backend",
    "queue_decisions",
    "design_review",
    "parts_on_hand",
    "reportable",
    "ablation",
    "os_layer",
    "os_layer_absent",
    "reviewers",
    "skills",
    "hooks",
}
NEVER_COMPARED = {
    "run_id",
    "seed",
    "held_out",
    "held_out_canaries",
    "network_enforced",
    "account",
}


def _fields() -> set[str]:
    """Every field of a run's configuration, each kind of model string by its own path."""
    top = set(RunConfig.model_fields) - {"models"}
    return top | {f"models.{kind}" for kind in ModelStrings.model_fields}


def _problems(model: type[RunConfig] = RunConfig) -> Any:  # noqa: ANN401 - the list, or why none
    census = getattr(compare, "census_problems", None)
    assert census is not None, "compare has no census of the run's fields"
    return outcome_of(lambda: census(model))


def test_every_field_sits_in_exactly_one_list() -> None:
    classed = [*DRIFT, *compare.REPORTED, *PER_RUN]
    assert sorted(classed) == sorted(_fields())
    assert _problems() == []


def test_each_field_is_in_the_list_decided_for_it() -> None:
    assert set(DRIFT) == REFUSED
    assert set(compare.REPORTED) == REPORTED
    assert set(PER_RUN) == NEVER_COMPARED


class _AdvisedModels(ModelStrings):
    advisor: str | None = None


class _Advised(RunConfig):
    models: _AdvisedModels
    web: str = "off"


def test_a_field_added_with_no_decision_is_named_top_level_or_among_the_models() -> None:
    assert _problems(_Advised) == [
        "models.advisor: in no list, so two runs that differ on it would compare as equal",
        "web: in no list, so two runs that differ on it would compare as equal",
    ]


def test_a_field_in_two_lists_or_a_name_that_is_no_field_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compare, "PER_RUN", (*PER_RUN, "ablation", "advisor"), raising=False)
    assert _problems() == [
        "ablation: in more than one list",
        "advisor: names no field of a run's configuration",
    ]


def _differing(**fields: Any) -> Any:  # noqa: ANN401 - what drifted, or why nothing was compared
    def drifted() -> list[str]:
        same: dict[str, Any] = {"ablation": False, "reviewers": "paired"} | {
            "skills": "on",
            "hooks": "on",
            "held_out": ("/tiers/held",),
            "held_out_sha256": ("1" * 64,),
        }
        return compare.drift(make_config(**same), make_config(**(same | fields)))

    return outcome_of(drifted)


@pytest.mark.parametrize(
    ("name", "other"),
    [
        ("brief_sha256", "f" * 64),
        ("target_head", "f" * 40),
        ("bounds", SCRIPTED_BOUNDS.model_copy(update={"session_max_turns": 21})),
        ("token_ceiling", 100_001),
        ("network", "none"),
        ("held_out_sha256", ("2" * 64,)),
    ],
)
def test_two_runs_that_differ_on_what_was_asked_or_from_where_are_refused(
    name: str,
    other: Any,  # noqa: ANN401 - each field's own type
) -> None:
    assert _differing(**{name: other}) == [name]
    assert _differing() == []


def test_what_an_ablation_varies_and_what_names_one_run_is_never_refused() -> None:
    varied: dict[str, Any] = {
        "run_id": "run-2",
        "seed": 8,
        "gate_mode": "observe",
        "ablation": True,
        "harness": CLEAN_HARNESS,
        "os_layer": Absent(reason="none here"),
        "os_layer_absent": "allow",
        "held_out_canaries": ("a" * 32,),
    }
    assert _differing(**varied) == []


def test_each_run_s_numbers_name_the_switches_they_were_measured_under() -> None:
    named = {"ablation", "reviewers", "skills", "hooks", "design_review", "queue_decisions"}
    assert named <= set(compare.RunNumbers.model_fields)
