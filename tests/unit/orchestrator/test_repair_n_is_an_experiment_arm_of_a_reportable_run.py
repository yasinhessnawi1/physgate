"""``design_review: repair:N`` is an experiment arm: in the register, and only in a reportable run.

A rejected plan re-planned at most N times is a second decomposition call, which the one-call rule
allows nowhere else, so the configuration refuses ``repair:N`` unless the run is reportable. A
reportable run reviews its plan: under ``observe``, or under the arm its frozen criteria name
(``on`` or ``repair:N``); one that does not review it is refused. Until the rounds a re-plan needs
are recorded, ``decompose`` refuses ``repair:N`` before any call is spent.
"""

from __future__ import annotations

import typing
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of
from orch_helpers import CLEAN_HARNESS, make_config
from test_decompose_reviews_the_plan_before_it_writes_anything import (
    REVIEWING,
    Calls,
    StandIn,
    _args,
    _exit,
    _nothing_recorded,
    _verdict,
    calls,  # noqa: F401 - the fixture
)

import physgate.flags as flags
import physgate.orchestrator.cli as orchestrator_cli
from physgate.evaluation.requirements import REQUIREMENTS
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import ModelStrings, RunConfig
from physgate.oslayer.probe import Present

PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
PINNED = ModelStrings(
    decomposition="claude-sonnet-5",
    roles={"electrical": "claude-sonnet-5"},
    reviewers={"electrical": "claude-opus-5-5", "design": "claude-opus-5-5"},
)
REPAIRS = ("repair:1", "repair:2", "repair:3")


def _config(**fields: Any) -> Any:  # noqa: ANN401 - a configuration, or why there is none
    return outcome_of(lambda: make_config(**fields))


def _refusals(config: RunConfig) -> list[str]:
    facts = RunFacts(config=config, os_layer=PRESENT, shell_sessions=True, new_run=True)
    return [why for requirement in REQUIREMENTS if (why := requirement(facts)) is not None]


def test_the_register_names_repair_one_to_three() -> None:
    flag = flags.DESIGN_REVIEW
    assert flag.values == ("off", "observe", "on", *REPAIRS)
    assert typing.get_args(flags.DesignReview) == flag.values
    for value in REPAIRS:
        meaning = flag.meanings[value]
        assert "re-plan" in meaning and "reportable" in meaning, value


@pytest.mark.parametrize("value", REPAIRS)
def test_repair_n_is_refused_in_a_run_that_is_not_reportable(value: str) -> None:
    plain = _config(design_review=value, models=PINNED)
    assert not isinstance(plain, RunConfig), plain
    assert "reportable" in str(plain)
    reportable = _config(design_review=value, reportable=True, harness=CLEAN_HARNESS, models=PINNED)
    assert isinstance(reportable, RunConfig), reportable
    assert f'"design_review":"{value}"'.encode() in reportable.canonical_bytes()


@pytest.mark.parametrize("value", ["observe", "on", *REPAIRS])
def test_a_reportable_run_may_review_its_plan_under_observe_or_the_arm_its_criteria_name(
    value: str,
) -> None:
    config = _config(design_review=value, reportable=True, harness=CLEAN_HARNESS, models=PINNED)
    assert isinstance(config, RunConfig), config
    assert outcome_of(lambda: _refusals(config)) == []


def test_a_reportable_run_that_does_not_review_its_plan_is_refused() -> None:
    off = _config(design_review="off", reportable=True, harness=CLEAN_HARNESS, models=PINNED)
    assert isinstance(off, RunConfig), off
    refused = outcome_of(lambda: _refusals(off))
    assert isinstance(refused, list) and refused, refused
    assert any("design_review: observe" in why for why in refused), refused


def test_decompose_spends_no_call_on_a_repair_arm_whose_rounds_it_cannot_record(
    tmp_path: Path,
    calls: Calls,  # noqa: F811 - the fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The reportable run's other requirements (a clean checkout, the OS layer) are this
    # machine's, not the arm's: the command reads a reportable repair arm as such a run would.
    monkeypatch.setattr(orchestrator_cli, "refusals", lambda facts: [])
    real = orchestrator_cli._config

    def reportable(args: Any) -> RunConfig:  # noqa: ANN401
        update = {"design_review": "repair:2", "reportable": True, "harness": CLEAN_HARNESS}
        return real(args).model_copy(update=update)

    monkeypatch.setattr(orchestrator_cli, "_config", reportable)
    params = {**REVIEWING, "design_review": "on"}
    reviewer = StandIn(_verdict())
    code = _exit(_args(tmp_path, params), reviewer)
    err = capsys.readouterr().err
    assert code == 2, (code, err)
    assert calls.made == 0
    assert reviewer.seen == []
    _nothing_recorded(tmp_path / "run")
    assert "repair" in err
