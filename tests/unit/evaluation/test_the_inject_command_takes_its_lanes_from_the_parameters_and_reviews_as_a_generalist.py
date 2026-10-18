"""The inject command's lanes, pause and reviewer kind come from what the run records.

With real reviewers, the parameters file states the lanes and the lane-wide pause, and a
file without them is refused before anything runs; a ``--lanes`` that disagrees with the
file is refused too. ``--generalist`` builds every role's reviewer on its rubric less the
domain sections, the same model and setup as the paired one. Nothing here calls a model.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from physgate.evaluation.inject.cli import _lane_rules, generalist_reviewers
from physgate.evaluation.inject.exceptions import InstrumentParamsError
from physgate.evaluation.inject.runner import InstrumentParams
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup

ROOT = Path(__file__).resolve().parents[3]
BOUNDS = RunBounds(
    binary_max_retries=0,
    session_wall_clock_s=4500,
    session_max_turns=80,
    infra_retry_delays_s=(60.0, 900.0, 2700.0),
)


def _params(**lanes: object) -> InstrumentParams:
    return InstrumentParams.model_validate(
        {
            "auth": "subscription",
            "reviewers": {"control": "claude-sonnet-5"},
            "bounds": BOUNDS.model_dump(),
            "effort": "high",
            "max_output_tokens": 64000,
            "token_ceiling": 400000,
            **lanes,
        }
    )


RULES = {"lanes": 4, "pause_after_failures": 3, "pause_s": 900.0, "repair_resumes": 1}


def test_the_parameters_file_states_the_lanes_and_the_pause() -> None:
    assert _lane_rules(argparse.Namespace(lanes=None), _params(**RULES)) == (4, 3, 900.0)


def test_a_parameters_file_without_lanes_is_refused() -> None:
    with pytest.raises(InstrumentParamsError, match="lanes and the lane-wide pause"):
        _lane_rules(argparse.Namespace(lanes=None), _params())


def test_lanes_given_against_the_file_are_refused() -> None:
    with pytest.raises(InstrumentParamsError, match="not the parameters file's"):
        _lane_rules(argparse.Namespace(lanes=2), _params(**RULES))


def test_the_generalist_mode_reviews_every_role_on_its_rubric_less_the_domain_sections(
    tmp_path: Path,
) -> None:
    setup = ReviewerSetup(
        run_id="g-1",
        models={"control": "claude-sonnet-5", "firmware": "claude-sonnet-5"},
        claude_version="2.1.301",
        bounds=BOUNDS,
        effort="high",
        max_output_tokens=64000,
        token_ceiling=400000,
        review_root=tmp_path,
        repo=None,
        install_bin=tmp_path / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="subscription", secret="unused"),
        library=ROOT,
    )
    built = generalist_reviewers(setup)
    assert sorted(built) == ["control", "firmware"]
    for role, reviewer in built.items():
        assert isinstance(reviewer, ClaudeReviewer)
        assert reviewer.rubric.kind == "generalist" and reviewer.rubric.role == role
        assert reviewer.model == "claude-sonnet-5"


def test_a_parameters_file_without_its_repair_resumes_is_refused() -> None:
    rules = {k: v for k, v in RULES.items() if k != "repair_resumes"}
    with pytest.raises(InstrumentParamsError, match="repair resumes"):
        _lane_rules(argparse.Namespace(lanes=None), _params(**rules))
