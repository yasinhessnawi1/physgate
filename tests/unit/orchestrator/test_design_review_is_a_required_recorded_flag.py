"""Whether a run reviews its plan is a flag of the register, required and recorded.

``design_review`` is ``off`` or ``observe`` (ARCH-060). A new run names it, or the command refuses
it before anything is written; it is never read from the environment. A run recorded before the
flag existed reads as ``off``, with exactly the digest its first line carries, and so does every
``off`` run, whose recorded form leaves the field out; an ``observe`` run records it, and names a
design reviewer. A reportable run starts only under ``observe``: its review is recorded and never
changes what the run does.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

from design_review_rig import outcome_of
from orch_helpers import CLEAN_HARNESS, make_config

import physgate.flags as flags
from physgate.evaluation.requirements import REQUIREMENTS
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import (
    ModelStrings,
    RunConfig,
    load_run_config,
    write_run_config,
)
from physgate.oslayer.probe import Present

PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
PINNED = ModelStrings(
    decomposition="claude-sonnet-5",
    roles={"electrical": "claude-sonnet-5"},
    reviewers={"electrical": "claude-opus-5-5", "design": "claude-opus-5-5"},
)


def _config(**fields: Any) -> Any:  # noqa: ANN401 - a configuration, or why there is none
    return outcome_of(lambda: make_config(**fields))


def test_the_register_names_the_flag_with_off_and_observe() -> None:
    flag = getattr(flags, "DESIGN_REVIEW", None)
    assert flag is not None, "the register has no design_review flag"
    assert flag.name == "design_review"
    assert flag.values == ("off", "observe")
    assert flag.architecture == "ARCH-060"
    assert flag in flags.REGISTER
    assert typing.get_args(getattr(flags, "DesignReview", None)) == flag.values


def test_design_review_is_a_required_recorded_flag(tmp_path: Path) -> None:
    field = RunConfig.model_fields.get("design_review")
    assert field is not None, "the run's configuration has no design_review"
    assert field.is_required()
    observe = _config(design_review="observe", models=PINNED)
    off = _config(design_review="off", models=PINNED)
    assert isinstance(observe, RunConfig), observe
    assert isinstance(off, RunConfig), off
    assert b'"design_review":"observe"' in observe.canonical_bytes()
    assert b"design_review" not in off.canonical_bytes()
    assert observe.sha256() != off.sha256()
    path = tmp_path / "observe.json"
    write_run_config(path, observe)
    assert load_run_config(path).design_review == "observe"


def test_a_run_recorded_before_the_flag_reads_as_off_with_its_digest_unchanged(
    tmp_path: Path,
) -> None:
    config = _config(design_review="off")
    assert isinstance(config, RunConfig), config
    path = tmp_path / "run.json"
    write_run_config(path, config)
    recorded = json.loads(path.read_bytes())
    assert "design_review" not in recorded  # what a run before the flag wrote, byte for byte
    loaded = load_run_config(path)
    assert loaded.design_review == "off"
    assert loaded.sha256() == config.sha256()


def test_a_run_that_reviews_its_plan_names_its_design_reviewer() -> None:
    unpinned = _config(design_review="observe")  # the helper's pins name no design reviewer
    assert not isinstance(unpinned, RunConfig), unpinned
    assert "design reviewer" in str(unpinned)
    assert isinstance(_config(design_review="off"), RunConfig)


def _refusals(config: RunConfig, *, new_run: bool = True) -> list[str]:
    facts = RunFacts(config=config, os_layer=PRESENT, shell_sessions=True, new_run=new_run)  # type: ignore[call-arg]
    return [why for requirement in REQUIREMENTS if (why := requirement(facts)) is not None]


def test_a_reportable_run_starts_only_under_observe() -> None:
    off = _config(design_review="off", reportable=True, harness=CLEAN_HARNESS, models=PINNED)
    observe = _config(
        design_review="observe", reportable=True, harness=CLEAN_HARNESS, models=PINNED
    )
    assert isinstance(off, RunConfig), off
    assert isinstance(observe, RunConfig), observe
    refused = outcome_of(lambda: _refusals(off))
    assert isinstance(refused, list), refused
    assert any("design_review: observe" in why for why in refused), refused
    assert outcome_of(lambda: _refusals(observe)) == []
    # A run the product starts, not reportable, reviews its plan or not as its parameters say.
    plain = _config(design_review="off", models=PINNED)
    assert outcome_of(lambda: _refusals(plain)) == []


def test_a_reportable_run_recorded_before_the_flag_still_resumes() -> None:
    off = _config(design_review="off", reportable=True, harness=CLEAN_HARNESS, models=PINNED)
    assert isinstance(off, RunConfig), off
    assert outcome_of(lambda: _refusals(off, new_run=False)) == []


def test_the_comparison_reports_the_flag() -> None:
    from physgate.evaluation.observe.compare import REPORTED

    assert "design_review" in REPORTED
