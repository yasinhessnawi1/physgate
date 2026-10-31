"""A re-plan is told the brief's prompt, the plan its review did not pass and what it found.

The prompt is a fixed template, built by code from the brief, the run's roles, the previous plan
and the review's findings: nothing else reaches it. It names no repair budget and no round, so a
re-plan built after any round from the same plan and findings is the same prompt, and the first
call's prompt is the decomposition prompt whatever the run's policy for a rejected plan is. The
plan is quoted as the bytes its digest is taken over, and the findings between the fences every
repair instruction quotes data in. The findings are checked for the material the reviewers hold
before anything is sent.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of
from orch_helpers import make_config

import physgate.orchestrator.decompose as decompose
from physgate.orchestrator.canaries import CanaryCheck
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.plan import Plan
from physgate.orchestrator.protocols import (
    CriterionDefect,
    CriterionVerdict,
    ItemVerdict,
    MessageUsage,
    ReviewResult,
    SpecDefect,
    Usage,
)
from physgate.orchestrator.repair import quoted

BRIEF = "Build a robot.\n\n## Acceptance criteria\n\n1. It stands.\n"
ROLES = ("control", "electrical")
REVIEWER = "claude-opus-5-5"
REVIEW_SESSION = "review-session-7"


def _plan() -> Plan:
    node: dict[str, Any] = {
        "id": "iface.bus",
        "kind": "interface",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {
            "v_bus": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-31T00:00:00Z",
    }
    spec = "Power it.\n\n## Acceptance criteria\n\n1. It is powered.\n"
    answer = {
        "modules": [
            {"name": "power", "role": "electrical", "module_dir": "modules/p", "spec": spec}
        ],
        "interface_nodes": [node],
    }
    return Plan.model_validate_json(json.dumps(answer))


def _review(
    verdict: str = "fail",
    *,
    defects: tuple[SpecDefect, ...] = (),
    criteria: tuple[CriterionVerdict, ...] = (),
) -> ReviewResult:
    return ReviewResult(
        verdict=verdict,  # type: ignore[arg-type]
        finding="the plan leaves the bus unprotected",
        reviewer_model=REVIEWER,
        session_id=REVIEW_SESSION,
        usage=(MessageUsage(message_id="r1", usage=Usage(input_tokens=1, output_tokens=1)),),
        failing_item="PA-3",
        items=(
            ItemVerdict(
                item="PA-1", section="domain_standards", result="met", evidence="plan line 2"
            ),
            ItemVerdict(
                item="PA-3",
                section="domain_standards",
                result="unmet",
                evidence="no fuse on iface.bus",
            ),
            ItemVerdict(item="PA-9", section="antipatterns", result="unmet", evidence=""),
        ),
        criteria=criteria,
        spec_defects=defects,
    )


def _named(name: str) -> Any:  # noqa: ANN401 - whatever the module names, or None
    return getattr(decompose, name, None)


def _canonical(plan: Plan) -> str:
    return json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def test_the_replan_prompt_carries_no_text_but_the_findings_between_markers() -> None:
    findings_of, prompt_of = _named("replan_findings"), _named("replan_prompt")
    assert findings_of is not None and prompt_of is not None, "no re-plan prompt is built"
    findings = findings_of(_review())
    plan = _plan()
    prompt = prompt_of(BRIEF, ROLES, plan, findings)
    expected_findings = "\n".join(
        [
            "The review's finding: the plan leaves the bus unprotected",
            "PA-3: no fuse on iface.bus",
            "PA-9",
        ]
    )
    assert findings.text == expected_findings
    assert prompt == (
        decompose.prompt_for(BRIEF, ROLES)
        + "\n"
        + decompose.REPLAN_SENTENCE
        + "\n\nThe plan the reviewer did not pass:\n"
        + "\n".join(quoted(_canonical(plan)))
        + "\n\nWhat the review found:\n"
        + "\n".join(quoted(expected_findings))
        + "\n\nAnswer by calling StructuredOutput once.\n"
    )
    # Nothing of the review's session reaches the designer: its model, its id, a met item.
    for absent in (REVIEWER, REVIEW_SESSION, "PA-1", "plan line 2", "fail"):
        assert absent not in prompt.split("Brief:\n", 1)[1], absent


def test_the_plan_quoted_is_the_bytes_its_digest_is_taken_over() -> None:
    findings_of, prompt_of = _named("replan_findings"), _named("replan_prompt")
    assert findings_of is not None and prompt_of is not None, "no re-plan prompt is built"
    plan = _plan()
    prompt = prompt_of(BRIEF, ROLES, plan, findings_of(_review()))
    import hashlib

    from physgate.orchestrator.plan import plan_sha256

    body = _canonical(plan)
    assert hashlib.sha256(body.encode()).hexdigest() == plan_sha256(plan)
    assert f"\n<<<\n{body}\n>>>\n" in prompt


def test_a_replan_names_no_repair_budget_and_no_round() -> None:
    prompt_of = _named("replan_prompt")
    assert prompt_of is not None, "no re-plan prompt is built"
    # A pure function of the brief, the roles, the plan and the findings: no round, no budget.
    assert list(inspect.signature(prompt_of).parameters) == ["brief", "roles", "plan", "findings"]
    findings = decompose.replan_findings(_review())
    first = prompt_of(BRIEF, ROLES, _plan(), findings)
    again = prompt_of(BRIEF, ROLES, _plan(), decompose.replan_findings(_review()))
    assert first == again
    tail = first.split("Brief:\n", 1)[1]
    for said in ("round", "attempt", "remain", "budget", "re-plan", "last"):
        assert said not in tail.lower(), said


def test_the_brief_s_missing_input_is_quoted_with_the_line_that_it_is_not_supplied() -> None:
    findings_of, prompt_of = _named("replan_findings"), _named("replan_prompt")
    assert findings_of is not None and prompt_of is not None, "no re-plan prompt is built"
    criteria = (
        CriterionVerdict(criterion="1", result="unmet", evidence="nothing stands it up"),
        CriterionVerdict(criterion="2", result="met", evidence="it moves"),
        CriterionVerdict(
            criterion="3",
            result="not evaluable",
            evidence="no load is given",
            defect=CriterionDefect(finding="the brief gives no load", blocking=True),
        ),
    )
    defects = (
        SpecDefect(finding="the brief gives no supply voltage", blocking=True, item="PA-4"),
        SpecDefect(finding="the brief's units are loose", blocking=False),
    )
    findings = findings_of(_review("blocked", defects=defects, criteria=criteria))
    assert findings.text.splitlines()[3:] == [
        "The brief's criterion 1 is unmet: nothing stands it up",
        "The brief lacks what a check needs (PA-4): the brief gives no supply voltage",
        "The brief lacks what a check needs (criterion 3): the brief gives no load",
    ]
    assert findings.lacks_input
    prompt = prompt_of(BRIEF, ROLES, _plan(), findings)
    assert prompt.endswith(
        "\n\n" + decompose.NO_INPUT_SUPPLIED_LINE + "\n\nAnswer by calling StructuredOutput once.\n"
    )
    plain = prompt_of(BRIEF, ROLES, _plan(), findings_of(_review()))
    assert decompose.NO_INPUT_SUPPLIED_LINE not in plain
    assert "units are loose" not in prompt  # a defect that does not block is not a finding


def test_a_passed_plan_is_never_replanned() -> None:
    findings_of = _named("replan_findings")
    assert findings_of is not None, "no re-plan findings are built"
    found = outcome_of(lambda: findings_of(_review("pass")))
    assert isinstance(found, Exception), found
    assert "pass" in str(found)


@pytest.mark.parametrize(
    ("planted", "seen"),
    [("HELD-OUT-CANARY-1", "held_out"), ("RUBRIC-CANARY-2", "review_material"), (None, None)],
)
def test_a_canary_in_the_findings_is_found_before_anything_is_sent(
    planted: str | None, seen: str | None
) -> None:
    check_of = _named("canary_in_findings")
    assert check_of is not None, "no canary check on a review's findings"
    review = _review()
    if planted is not None:
        review = review.model_copy(update={"finding": f"the plan copies {planted} verbatim"})
    check = CanaryCheck(
        held_out=frozenset({"HELD-OUT-CANARY-1"}), review_material=frozenset({"RUBRIC-CANARY-2"})
    )
    assert check_of(decompose.replan_findings(review), check) == seen


def test_the_first_call_is_sent_the_prompt_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []

    class SentError(Exception):
        pass

    def argv(binary: str, *, prompt: str, **_: Any) -> list[str]:  # noqa: ANN401
        sent.append(prompt)
        raise SentError

    monkeypatch.setattr(decompose, "decomposition_argv", argv)
    monkeypatch.setattr(decompose, "claude_binary", lambda: "claude")
    monkeypatch.setattr(decompose, "binary_version", lambda binary=None: "2.1.301")
    config = make_config(claude_version="2.1.301")
    credential = Credential("api_key", "sk-ant-test-dummy-not-a-credential")
    roles = sorted(config.models.roles)
    for given in (None, "a re-plan's prompt"):
        kwargs: dict[str, Any] = {} if given is None else {"prompt": given}
        found = outcome_of(
            lambda kwargs=kwargs: decompose.call(
                BRIEF,
                config=config,
                workdir=tmp_path / "w",
                base_url=None,
                credential=credential,
                **kwargs,
            )
        )
        assert isinstance(found, SentError), found
    # Without a prompt the call is sent the decomposition prompt, whatever the run's policy.
    assert sent == [decompose.prompt_for(BRIEF, roles), "a re-plan's prompt"]
