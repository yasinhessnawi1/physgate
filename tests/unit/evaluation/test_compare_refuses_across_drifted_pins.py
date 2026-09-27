"""``compare`` refuses across a drifted model, binary or endpoint, and reports the rest.

Criterion: when a pinned model string, the binary's version or the endpoint
differs from the baseline's, the comparison is refused and every drifted field
named; one test per field. What an ablation varies on purpose (gate mode, auth,
effort, harness) is compared and reported beside the numbers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from observe_rig import HARNESS, fake_run, target_repo

from physgate.evaluation.observe.compare import compare, drift
from physgate.evaluation.observe.exceptions import CompareRefusedError
from physgate.evaluation.observe.manifest import read_manifest
from physgate.orchestrator.run_config import ModelStrings

MODELS = {
    "decomposition": "claude-sonnet-5",
    "roles": {"electrical": "claude-sonnet-5"},
    "reviewers": {"electrical": "claude-opus-5-5"},
}


def models(**changes: Any) -> ModelStrings:  # noqa: ANN401
    return ModelStrings(**(MODELS | changes))


@pytest.mark.parametrize(
    ("overrides", "drifted"),
    [
        ({"models": models(decomposition="claude-haiku-4-5-20251001")}, "models.decomposition"),
        (
            {"models": models(roles={"electrical": "claude-haiku-4-5-20251001"})},
            "models.roles.electrical",
        ),
        (
            {"models": models(reviewers={"electrical": "claude-haiku-4-5-20251001"})},
            "models.reviewers.electrical",
        ),
        (
            {
                "models": models(
                    roles={"electrical": "claude-sonnet-5", "mechanical": "claude-sonnet-5"},
                    reviewers={"electrical": "claude-opus-5-5", "mechanical": "claude-opus-5-5"},
                )
            },
            "models.reviewers.mechanical",
        ),
        ({"claude_version": "2.1.273"}, "claude_version"),
        ({"endpoint": "default"}, "endpoint"),
    ],
)
def test_a_drifted_pin_is_refused_and_named(
    tmp_path: Path, overrides: dict[str, Any], drifted: str
) -> None:
    repo = target_repo(tmp_path)
    baseline = fake_run(tmp_path, "base", repo)
    candidate = fake_run(tmp_path, "cand", repo, overrides=overrides)
    with pytest.raises(CompareRefusedError, match="re-run the baseline") as refusal:
        compare(baseline, candidate)
    assert drifted in refusal.value.context["drifted"].split(",")
    with pytest.raises(CompareRefusedError):
        compare(candidate, baseline)


def test_an_added_role_names_both_its_model_strings(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    base = read_manifest(fake_run(tmp_path, "base", repo)).config
    two = base.model_copy(
        update={
            "models": models(
                roles={"electrical": "claude-sonnet-5", "mechanical": "claude-sonnet-5"},
                reviewers={"electrical": "claude-opus-5-5", "mechanical": "claude-opus-5-5"},
            )
        }
    )
    assert drift(base, two) == ["models.roles.mechanical", "models.reviewers.mechanical"]
    assert drift(base, base) == []


def test_an_ablation_s_own_changes_are_compared_and_reported(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    baseline = fake_run(tmp_path, "base", repo)
    moved = HARNESS.model_copy(
        update={"commit": "0" * 40, "clean": True, "uncommitted_sha256": None}
    )
    candidate = fake_run(
        tmp_path,
        "cand",
        repo,
        overrides={
            "gate_mode": "observe",
            "auth": "subscription",
            "effort": "low",
            "harness": moved,
        },
    )
    side = compare(baseline, candidate)
    assert side.differs_in == ("gate_mode", "auth", "effort", "harness")
    assert (side.baseline.gate_mode, side.candidate.gate_mode) == ("on", "observe")
    assert side.candidate.harness_commit == "0" * 40


def test_the_numbers_stand_side_by_side_each_with_its_manifest_id(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    baseline = fake_run(tmp_path, "base", repo)
    candidate = fake_run(tmp_path, "cand", repo)
    side = compare(baseline, candidate)
    assert side.differs_in == ()
    assert side.baseline.manifest_id == read_manifest(baseline).manifest_id
    assert side.candidate.manifest_id == read_manifest(candidate).manifest_id
    for numbers in (side.baseline, side.candidate):
        assert (numbers.sessions, numbers.attempts_merged, numbers.attempts_rejected) == (2, 2, 0)
        assert numbers.integration == "pass" and numbers.subtasks_escalated == 0
        # Sessions 10+3+5 and 20+3+5; two reviews of 40+9; routing none.
        assert numbers.tokens == {"decomposition": 0, "session": 46, "reviewer": 98, "routing": 0}
        assert numbers.wall_clock_s >= 0
