"""A system requirement is named by the brief's number alone, and the decomposition is told so.

Where the brief numbers its acceptance criteria, the plan check refuses a system requirement that
is not one of those numbers, character for character: ``"AC4"`` or ``"AC4: every criterion met"``
is not ``"4"``. A real plan named its requirements that way and was refused after its one paid
call, since nothing it was sent gave the form. So the form is given where the brief numbers its
criteria, and only there: the prompt states it in one sentence with one of the brief's own numbers
as its example, and the schema the binary holds the answer to carries a pattern of the brief's
numbers on the requirement. With a brief that numbers nothing, a requirement is given in the
brief's words, and the prompt and the schema are the bytes sent before. The check itself is as
strict as it was.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan as pairs
import test_the_plan_gives_sizing_one_module_and_integration_its_consumers_and_requirements as sized
import test_without_the_cross_cutting_roles_the_decomposition_is_sent_as_before as before
from orch_helpers import make_config

import physgate.orchestrator.decompose as decompose
from physgate import roles
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import (
    REQUIREMENTS_SENTENCE,
    ReplanFindings,
    plan_problems,
    plan_schema,
    prompt_for,
    replan_prompt,
)
from physgate.orchestrator.run_config import ModelStrings
from physgate.reviewers.contract import issued_criteria

#: The run role sets with integration: without sizing, and with it.
WITH_INTEGRATION = [("control", "firmware", "integration"), pairs.BOTH]
#: The run role sets without integration, whose prompt has no system requirements at all.
WITHOUT_INTEGRATION = [("control", "firmware"), ("control", "firmware", "sizing")]

#: Briefs that number their acceptance criteria: from 1, and from a later number, so the
#: example is seen to be the brief's own.
NUMBERED = [
    sized.BRIEF,
    "Build a robot.\n\n## Acceptance criteria\n\n7. It stands.\n8. It recovers from a push.\n",
]
#: Briefs that number nothing: a requirement is then given in the brief's words.
UNNUMBERED = ["Build a robot.", sized.UNNUMBERED_BRIEF]


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def _requirements_paragraph(prompt: str) -> str:
    """The prompt's paragraph that asks for the system requirements."""
    (paragraph,) = [p for p in prompt.split("\n\n") if p.startswith(REQUIREMENTS_SENTENCE)]
    return paragraph


def _schema(run_roles: tuple[str, ...], brief: str) -> Any:  # noqa: ANN401 - parsed JSON
    """The plan schema a call for ``brief`` sends, parsed."""
    assert "brief" in inspect.signature(plan_schema).parameters, "the schema is not the brief's"
    return json.loads(plan_schema(run_roles, brief))


# --- the prompt ---------------------------------------------------------------------------


@pytest.mark.parametrize("brief", NUMBERED, ids=["from 1", "from 7"])
@pytest.mark.parametrize("run_roles", WITH_INTEGRATION, ids=", ".join)
def test_with_a_numbered_brief_the_prompt_names_each_requirement_by_the_brief_s_number(
    run_roles: tuple[str, ...], brief: str
) -> None:
    numbered = issued_criteria(brief)
    assert numbered is not None
    prompt = prompt_for(brief, run_roles)
    form = _requirements_paragraph(prompt).removeprefix(REQUIREMENTS_SENTENCE).strip()
    assert form, "the prompt asks for the requirements and never gives their form"
    # One sentence, right after the one that asks for the requirements.
    assert form.count(". ") == 0 and form.endswith("."), form
    for word in ("brief", "number", "alone"):
        assert word in form, (word, form)
    # One example, and it is one of the brief's own numbers, so the check passes it.
    assert re.findall(r'"([^"]+)"', form) == [numbered[0]], form
    # A re-plan is sent the same prompt, so it is told the form too.
    again = replan_prompt(brief, run_roles, pairs.integrated(), ReplanFindings("found", False))
    assert form in again


@pytest.mark.parametrize("brief", UNNUMBERED, ids=["one line", "one sentence"])
@pytest.mark.parametrize("run_roles", WITH_INTEGRATION, ids=", ".join)
def test_with_an_unnumbered_brief_the_prompt_gives_no_such_sentence(
    run_roles: tuple[str, ...], brief: str
) -> None:
    prompt = prompt_for(brief, run_roles)
    assert _requirements_paragraph(prompt) == REQUIREMENTS_SENTENCE
    if brief == "Build a robot.":
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        assert digest == pairs.INTEGRATED_PROMPT_SHA256[run_roles]


@pytest.mark.parametrize("brief", NUMBERED, ids=["from 1", "from 7"])
@pytest.mark.parametrize("run_roles", WITHOUT_INTEGRATION, ids=", ".join)
def test_without_integration_a_numbered_brief_gives_the_prompt_no_such_sentence(
    run_roles: tuple[str, ...], brief: str
) -> None:
    prompt = prompt_for(brief, run_roles)
    assert REQUIREMENTS_SENTENCE not in prompt
    assert prompt == prompt_for("Build a robot.", run_roles).replace(
        "Brief:\nBuild a robot.\n", f"Brief:\n{brief}\n"
    )


# --- the schema ---------------------------------------------------------------------------


@pytest.mark.parametrize("run_roles", WITH_INTEGRATION, ids=", ".join)
def test_with_a_numbered_brief_the_schema_holds_a_requirement_to_the_brief_s_numbers(
    run_roles: tuple[str, ...],
) -> None:
    requirement = _schema(run_roles, sized.BRIEF)["$defs"]["SystemRequirement"]["properties"][
        "requirement"
    ]
    assert "pattern" in requirement, requirement
    pattern = requirement["pattern"]
    # Of the features every regular-expression dialect reads alike, as the store's pattern is.
    assert set(pattern) <= set("^$()|0123456789"), pattern
    assert (requirement["minLength"], requirement["maxLength"]) == (1, 500)
    # A JSON Schema pattern is searched for, so it anchors itself.
    for number in ("1", "2", "3"):
        assert re.search(pattern, number), (number, pattern)
    for refused in ("AC2", "AC2: It recovers from a 5 N push.", "2.", " 2", "02", "4", "12"):
        assert not re.search(pattern, refused), (refused, pattern)
    later = _schema(run_roles, NUMBERED[1])["$defs"]["SystemRequirement"]["properties"]
    assert re.search(later["requirement"]["pattern"], "7")
    assert not re.search(later["requirement"]["pattern"], "1")


@pytest.mark.parametrize("brief", UNNUMBERED, ids=["one line", "one sentence"])
def test_with_an_unnumbered_brief_or_without_integration_the_schema_is_as_sent_before(
    brief: str,
) -> None:
    for run_roles in WITH_INTEGRATION:
        schema = json.dumps(_schema(run_roles, brief), sort_keys=True, separators=(",", ":"))
        assert hashlib.sha256(schema.encode()).hexdigest() == pairs.INTEGRATED_SCHEMA_SHA256
    for numbered in NUMBERED:
        domain = json.dumps(
            _schema(sized.DOMAIN_ONLY, numbered), sort_keys=True, separators=(",", ":")
        )
        assert hashlib.sha256(domain.encode()).hexdigest() == before.SCHEMA_SHA256


@pytest.mark.parametrize("brief", [*NUMBERED, *UNNUMBERED], ids=["1", "7", "line", "sentence"])
def test_the_call_sends_the_schema_and_the_prompt_of_its_own_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, brief: str
) -> None:
    sent: dict[str, Any] = {}

    def ran(argv: list[str], **given: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        sent["schema"] = argv[argv.index("--json-schema") + 1]
        sent["prompt"] = given["input"]
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")

    run_roles = pairs.BOTH
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(run_roles, "claude-sonnet-5"),
        reviewers=dict.fromkeys(run_roles, "claude-opus-5-5"),
    )
    monkeypatch.setattr(decompose, "claude_binary", lambda: "/nonexistent/claude")
    monkeypatch.setattr(decompose, "binary_version", lambda binary=None: "2.1.272")
    monkeypatch.setattr(subprocess, "run", ran)
    decompose.call(
        brief,
        config=make_config(models=models),
        workdir=tmp_path / "decomposition",
        base_url=None,
        credential=Credential(mode="api_key", secret="sk-ant-test-dummy-not-a-credential"),
    )
    assert sent["schema"] == plan_schema(run_roles, brief)
    assert sent["prompt"] == prompt_for(brief, run_roles)
    pattern = (
        "pattern"
        in json.loads(sent["schema"])["$defs"]["SystemRequirement"]["properties"]["requirement"]
    )
    assert pattern is (issued_criteria(brief) is not None)


# --- the check ----------------------------------------------------------------------------


def _requirement(name: str) -> dict[str, Any]:
    return {"requirement": name, "contributing": [{"module": "drive", "criterion": "1"}]}


@pytest.mark.parametrize(
    "name", ["AC2", "AC2: It recovers from a 5 N push.", "2.", " 2", "02", "criterion 2", "4"]
)
def test_the_check_still_refuses_a_requirement_not_named_by_the_brief_s_number_alone(
    name: str,
) -> None:
    plan = sized.integrated(system_requirements=[_requirement(name)])
    expected = (
        f"system requirement {name!r} is not one of the brief's numbered acceptance criteria "
        "(1, 2, 3)"
    )
    assert plan_problems(plan, sized.ROLES, sized.BRIEF) == [expected]
    cause, detail, refused, _, _ = sized.judged(
        sized.answer(system_requirements=[_requirement(name)])
    )
    assert cause == "invalid_plan" and expected in detail and refused is None
    # The brief's bare number passes, and an unnumbered brief's words pass as before.
    named = sized.integrated(system_requirements=[_requirement("2")])
    assert plan_problems(named, sized.ROLES, sized.BRIEF) == []
    assert plan_problems(plan, sized.ROLES, sized.UNNUMBERED_BRIEF) == []
