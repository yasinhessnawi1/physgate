"""``reviewers: generalist`` reviews each role's work as its paired reviewer would, less the domain.

An ablation run's arm. Each role's reviewer is the same Claude reviewer, on the same reviewer pin,
judging with the generalist rubric made by code from the role's promoted paired rubric (its two
domain sections left out), and shown a packet without the role's own library files. Its review
line names the rubric's kind and digest, so the record says which arm judged each attempt.

The loop takes a verdict only from the rubric the arm names: under ``generalist`` a verdict
judged with any other rubric is refused, and under ``paired`` a generalist verdict is. Replay
holds the record to the same rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of, refusal
from loop_fakes import FakeGate, FakeReviewer, Rig, plan
from orch_helpers import CLEAN_HARNESS, make_config
from test_the_physgate_command_starts_and_decides import _promoted

from physgate.knowledge.promote import KNOWLEDGE_ROOT
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.exceptions import ReviewerNotRegisteredError
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage
from physgate.orchestrator.run_config import ModelStrings, RunConfig
from physgate.reviewers.claude import ReviewerSetup, claude_reviewers
from physgate.reviewers.rubric import generalist_of, load_rubric

ROLES = ("control", "firmware")
MODELS = ModelStrings(
    decomposition="claude-sonnet-5",
    roles=dict.fromkeys(ROLES, "claude-opus-5-5"),
    reviewers=dict.fromkeys(ROLES, "claude-sonnet-5"),
)


def _arm(value: str) -> dict[str, Any]:
    return {"reviewers": value, "ablation": value != "paired", "harness": CLEAN_HARNESS}


def _setup(tmp: Path, value: str) -> ReviewerSetup:
    library = tmp / "harness"
    if not (library / KNOWLEDGE_ROOT).exists():
        for role in ROLES:
            _promoted(library, role)
    config = outcome_of(lambda: make_config(models=MODELS, **_arm(value)))
    assert isinstance(config, RunConfig), f"an ablation run is refused reviewers: {value}: {config}"
    return ReviewerSetup.of_run(
        config,
        review_root=tmp / "rs",
        repo=tmp / "target",
        install_bin=tmp / "install" / "bin" / "physgate",
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
        library=library,
    )


def test_the_reviewers_setup_carries_the_arm(tmp_path: Path) -> None:
    assert getattr(_setup(tmp_path, "generalist"), "reviewers", None) == "generalist"
    assert getattr(_setup(tmp_path, "paired"), "reviewers", None) == "paired"


def test_under_generalist_each_role_is_judged_with_the_generalist_rubric_of_its_paired_one(
    tmp_path: Path,
) -> None:
    built = claude_reviewers(_setup(tmp_path, "generalist"))
    assert sorted(built) == list(ROLES)
    for role, reviewer in built.items():
        paired = load_rubric(tmp_path / "harness" / KNOWLEDGE_ROOT, role)
        rubric = reviewer.rubric  # type: ignore[attr-defined]
        assert rubric.kind == "generalist", f"{role} is not judged with the generalist rubric"
        assert rubric == generalist_of(paired)
        assert reviewer.model == "claude-sonnet-5", "the generalist moved off the reviewer pin"


def test_under_paired_each_role_is_judged_with_its_paired_rubric_as_before(tmp_path: Path) -> None:
    built = claude_reviewers(_setup(tmp_path, "paired"))
    for role, reviewer in built.items():
        paired = load_rubric(tmp_path / "harness" / KNOWLEDGE_ROOT, role)
        assert reviewer.rubric == paired  # type: ignore[attr-defined]


# -- through the loop -------------------------------------------------------------------------


def _verdict(kind: str | None) -> ReviewResult:
    usage = Usage(
        input_tokens=7, output_tokens=7, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    return ReviewResult(
        verdict="pass",
        finding="the change is sound",
        reviewer_model="claude-opus-5-5",
        session_id="rev-1",
        usage=(MessageUsage(message_id="r1", usage=usage),),
        rubric_sha256=None if kind is None else "e" * 64,
        rubric_kind=kind,  # type: ignore[arg-type]
    )


def _run(tmp: Path, value: str, kind: str | None) -> tuple[Rig, Any]:  # noqa: ANN401
    rig = Rig(
        tmp,
        gate=FakeGate(),
        reviewer=FakeReviewer(results={1: _verdict(kind)}),
        config_overrides=_arm(value),
    )
    loop = outcome_of(rig.open)
    assert not isinstance(loop, Exception), f"the run is refused at its configuration: {loop}"
    try:
        loop.start(plan("s1"))
        return rig, outcome_of(loop.run)
    finally:
        loop.close()


def _lines(tmp: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in (tmp / "events.jsonl").read_text().splitlines()]


def test_under_generalist_a_generalist_verdict_merges_and_its_line_names_the_rubric(
    tmp_path: Path,
) -> None:
    rig, step = _run(tmp_path, "generalist", "generalist")
    assert not isinstance(step, Exception), step
    assert step.kind == "done"
    ran = next(line for line in _lines(tmp_path) if line["kind"] == "review_ran")
    assert (ran["result"]["rubric_kind"], ran["result"]["rubric_sha256"]) == (
        "generalist",
        "e" * 64,
    )
    assert len(rig.merger.merges) == 1
    assert _lines(tmp_path)[0]["reviewers"] == "generalist"


@pytest.mark.parametrize(
    ("value", "kind"), [("generalist", "paired"), ("generalist", None), ("paired", "generalist")]
)
def test_a_verdict_judged_with_another_arm_s_rubric_is_refused(
    tmp_path: Path, value: str, kind: str | None
) -> None:
    rig, step = _run(tmp_path, value, kind)
    assert isinstance(step, ReviewerNotRegisteredError), (
        f"under reviewers: {value} the loop took a verdict judged with a {kind} rubric: {step}"
    )
    assert "rubric" in str(step)
    assert rig.merger.merges == []
    assert not any(line["kind"] == "review_ran" for line in _lines(tmp_path))


def _with_kind(tmp: Path, value: str, kind: str | None) -> list[dict[str, Any]]:
    """A run that merged under ``value``'s own rubric, its review line rewritten to ``kind``."""
    own = "generalist" if value == "generalist" else "paired"
    _run(tmp, value, own)
    log = _lines(tmp)
    ran = next(line for line in log if line["kind"] == "review_ran")
    ran["result"]["rubric_kind"] = kind
    if kind is None:
        ran["result"]["rubric_sha256"] = None
    return log


@pytest.mark.parametrize(
    ("value", "kind"), [("generalist", "paired"), ("generalist", None), ("paired", "generalist")]
)
def test_replay_refuses_a_review_line_of_another_arm_s_rubric(
    tmp_path: Path, value: str, kind: str | None
) -> None:
    log = _with_kind(tmp_path / "run", value, kind)
    assert refusal(tmp_path, log), f"replay took a {kind} review under reviewers: {value}"


def test_replay_takes_each_arm_s_own_rubric(tmp_path: Path) -> None:
    assert (
        refusal(tmp_path / "g", _with_kind(tmp_path / "g" / "run", "generalist", "generalist"))
        == ""
    )
    assert refusal(tmp_path / "p", _with_kind(tmp_path / "p" / "run", "paired", "paired")) == ""
    # A run recorded before rubrics were named on the line reads as paired.
    assert refusal(tmp_path / "o", _with_kind(tmp_path / "o" / "run", "paired", None)) == ""
