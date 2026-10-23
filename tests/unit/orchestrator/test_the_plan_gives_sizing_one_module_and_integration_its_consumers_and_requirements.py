"""The plan of a run with sizing and integration: what the plan must say, and what is refused.

Sizing and integration are cross-cutting roles (ARCH-051). The plan gives sizing one
module at most: the harness opens and closes the domain work with it. The plan gives
integration no module at all, because the harness writes integration's specification
from the recorded plan; its directory is kept for it. What integration checks has to be
fixed before any module runs, so a run with the integration role plans two more things,
in the one model call:

- **the consumers of each interface node:** the modules that read it, by name. The
  module pairs whose contract is tested are read from this list, and they cannot be
  read from what the modules later write;
- **the system requirements:** each requirement of the brief that only the assembled
  system can show, with the module criteria that contribute to it.

Both are untrusted input, held by code to the plan they sit in and to the brief: a
module, an interface or a criterion that does not exist, an entry given twice, a
requirement the brief does not number, or a producer named as its own consumer is a
problem, and the plan is refused.

Both roles are found in the register by what they own, never by their names.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from physgate import roles
from physgate.orchestrator.decompose import (
    IntegratedPlan,
    Plan,
    judge,
    plan_model,
    plan_problems,
    plan_schema,
    plan_sha256,
    prompt_for,
)
from physgate.reviewers.contract import issued_criteria
from physgate.roles import CrossCuttingRole

#: The run's roles: two domain roles and both cross-cutting ones.
ROLES = ("control", "firmware", "integration", "sizing")
DOMAIN_ONLY = ("control", "firmware")
MODEL = "claude-opus-5-5"

BRIEF = (
    "Build a two-wheeled balancing robot.\n\n"
    "## Acceptance criteria\n\n"
    "1. It stands upright for 60 s.\n"
    "2. It recovers from a 5 N push.\n"
    "3. It reports its tilt at 100 Hz.\n"
)
UNNUMBERED_BRIEF = "Build a two-wheeled balancing robot that recovers from a 5 N push.\n"

#: The one sentence the prompt gains with integration, word for word.
REQUIREMENTS_SENTENCE = (
    "List each requirement of the brief that only the assembled system can show, with the "
    "module criteria that contribute to it."
)


def spec(criteria: int) -> str:
    """A module specification numbering ``criteria`` acceptance criteria."""
    lines = "".join(f"{i}. Criterion {i} holds.\n" for i in range(1, criteria + 1))
    return f"Do the work.\n\n## Acceptance criteria\n\n{lines}"


def module(
    name: str, role: str, criteria: int = 3, module_dir: str | None = None
) -> dict[str, str]:
    return {
        "name": name,
        "role": role,
        "module_dir": module_dir or f"modules/{name}",
        "spec": spec(criteria) if criteria else "Do the work.\n",
    }


def interface(node_id: str = "iface.drive", owner: str = "control") -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "interface",
        "domain": owner,
        "owner_role": owner,
        "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": owner}},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-23T00:00:00Z",
    }


GOOD: dict[str, Any] = {
    "modules": [
        module("sizing", "sizing"),
        module("control", "control"),
        module("firmware", "firmware"),
    ],
    "interface_nodes": [interface()],
    "interface_consumers": [{"interface": "iface.drive", "consumers": ["firmware"]}],
    "system_requirements": [
        {
            "requirement": "2",
            "contributing": [
                {"module": "control", "criterion": "1"},
                {"module": "firmware", "criterion": "2"},
            ],
        }
    ],
}


def answer(**changes: Any) -> dict[str, Any]:  # noqa: ANN401 - a plan's own fields
    """The good answer with ``changes`` made to it; a field given as ``None`` is left out."""
    given = copy.deepcopy(GOOD)
    for key, value in changes.items():
        if value is None:
            given.pop(key)
        else:
            given[key] = value
    return given


def integrated(**changes: Any) -> IntegratedPlan:  # noqa: ANN401 - a plan's own fields
    return IntegratedPlan.model_validate_json(json.dumps(answer(**changes)))


def result(structured: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "terminal_reason": "completed",
        "num_turns": 2,
        "structured_output": structured,
    }


def judged(structured: dict[str, Any], run_roles: tuple[str, ...] = ROLES) -> Any:  # noqa: ANN401
    return judge(
        result(structured),
        exit_code=0,
        timed_out=False,
        model=MODEL,
        roles=run_roles,
        answered=frozenset({MODEL}),
        brief=BRIEF,
    )


@pytest.fixture(autouse=True)
def sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it will stand once sizing ships: the stand-ins' way, written directly."""
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


# --- the good plan ------------------------------------------------------------------------


def test_a_plan_that_carries_what_integration_needs_has_no_problem() -> None:
    assert plan_problems(integrated(), ROLES, BRIEF) == []
    cause, detail, plan, _, _ = judged(answer())
    assert cause is None, detail
    assert isinstance(plan, IntegratedPlan)
    assert plan.interface_consumers[0].consumers == ("firmware",)
    assert plan.system_requirements[0].contributing[1].criterion == "2"


# --- the plan's form ----------------------------------------------------------------------


def test_the_plan_s_form_follows_whether_integration_is_a_role() -> None:
    assert plan_model(ROLES) is IntegratedPlan
    assert plan_model(DOMAIN_ONLY) is Plan
    assert plan_model(("control", "firmware", "sizing")) is Plan
    schema = json.loads(plan_schema(ROLES))
    fields = {"modules", "interface_nodes", "interface_consumers", "system_requirements"}
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False
    assert not {"title", "description", "$id", "$comment"} & set(schema)
    assert set(json.loads(plan_schema(DOMAIN_ONLY))["properties"]) == {
        "modules",
        "interface_nodes",
    }


def test_an_integration_plan_must_carry_its_system_requirements_list() -> None:
    # Required, and it may be empty: a brief may hold no requirement only the assembled
    # system can show, and the plan says so by an empty list, not by leaving it out.
    cause, detail, _, _, _ = judged(answer(system_requirements=None))
    assert cause == "invalid_plan" and "system_requirements" in detail
    cause, detail, plan, _, _ = judged(answer(system_requirements=[]))
    assert cause is None, detail
    assert isinstance(plan, IntegratedPlan) and plan.system_requirements == ()


def test_an_integration_plan_must_name_the_consumers_of_its_interfaces() -> None:
    cause, detail, _, _, _ = judged(answer(interface_consumers=None))
    assert cause == "invalid_plan" and "interface_consumers" in detail


def test_the_two_lists_are_refused_from_a_run_without_integration() -> None:
    # The base plan forbids every field it does not name, so the lists cannot ride along.
    cause, _, _, _, _ = judged(answer(), DOMAIN_ONLY)
    assert cause == "invalid_plan"


def test_a_plan_of_the_other_form_is_a_problem_wherever_it_is_judged() -> None:
    base = Plan.model_validate_json(
        json.dumps(answer(interface_consumers=None, system_requirements=None))
    )
    found = plan_problems(base, ROLES, BRIEF)
    assert any("integration" in p and "no list" in p for p in found), found
    found = plan_problems(integrated(), DOMAIN_ONLY, BRIEF)
    assert any("no integration role" in p for p in found), found


# --- the system requirements --------------------------------------------------------------


def _requirement(requirement: str, *contributing: tuple[str, str]) -> dict[str, Any]:
    return {
        "requirement": requirement,
        "contributing": [{"module": m, "criterion": c} for m, c in contributing],
    }


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        (
            {"system_requirements": [_requirement("2", ("drive", "1"))]},
            "'drive', which is no module of the plan",
        ),
        (
            {"system_requirements": [_requirement("2", ("control", "7"))]},
            "criterion '7' of 'control'",
        ),
        (
            {
                "modules": [
                    module("sizing", "sizing"),
                    module("control", "control"),
                    module("firmware", "firmware", criteria=0),
                ],
            },
            "criterion '2' of 'firmware'",
        ),
        (
            {
                "system_requirements": [
                    _requirement("2", ("control", "1")),
                    _requirement("2", ("firmware", "2")),
                ]
            },
            "listed more than once",
        ),
        (
            {"system_requirements": [_requirement("4", ("control", "1"))]},
            "'4' is not one of the brief's numbered acceptance criteria",
        ),
        (
            {"system_requirements": [_requirement("It stands upright.", ("control", "1"))]},
            "is not one of the brief's numbered acceptance criteria",
        ),
    ],
    ids=[
        "an unknown module",
        "a criterion not in that module's spec",
        "a criterion of a module whose spec numbers none",
        "a duplicate requirement",
        "a requirement number the brief does not have",
        "the brief's words where the brief numbers its criteria",
    ],
)
def test_a_system_requirement_the_plan_cannot_back_is_refused(
    changes: dict[str, Any], problem: str
) -> None:
    found = plan_problems(integrated(**changes), ROLES, BRIEF)
    assert any(problem in p for p in found), found
    cause, detail, plan, _, _ = judged(answer(**changes))
    assert cause == "invalid_plan" and problem in detail and plan is None


def test_an_empty_contributing_list_is_refused_by_the_schema() -> None:
    with pytest.raises(ValidationError, match="contributing"):
        integrated(system_requirements=[_requirement("2")])
    cause, _, _, _, _ = judged(answer(system_requirements=[_requirement("2")]))
    assert cause == "invalid_plan"
    entry = json.loads(plan_schema(ROLES))["$defs"]["SystemRequirement"]
    assert entry["properties"]["contributing"]["minItems"] == 1


def test_with_an_unnumbered_brief_a_requirement_is_given_in_the_brief_s_words() -> None:
    words = _requirement("It recovers from a 5 N push.", ("control", "1"))
    plan = integrated(system_requirements=[words])
    assert plan_problems(plan, ROLES, UNNUMBERED_BRIEF) == []
    # The same words against a brief that numbers its criteria are refused (above).
    assert plan_problems(plan, ROLES, BRIEF) != []


def test_a_requirement_and_a_criterion_are_bounded_by_the_schema() -> None:
    with pytest.raises(ValidationError):
        integrated(system_requirements=[_requirement("x" * 501, ("control", "1"))])
    with pytest.raises(ValidationError):
        integrated(system_requirements=[_requirement("", ("control", "1"))])
    for criterion in ("one", "1a", "", "-1"):
        with pytest.raises(ValidationError):
            integrated(system_requirements=[_requirement("2", ("control", criterion))])
    assert (
        plan_problems(
            integrated(system_requirements=[_requirement("2", ("control", "3"))]), ROLES, BRIEF
        )
        == []
    )


# --- the consumers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        (
            {"interface_consumers": [{"interface": "iface.drive", "consumers": ["drive"]}]},
            "'drive' as a consumer, which is no module of the plan",
        ),
        (
            {
                "interface_consumers": [
                    {"interface": "iface.drive", "consumers": ["firmware"]},
                    {"interface": "iface.other", "consumers": ["firmware"]},
                ]
            },
            "'iface.other', which is no interface node of the plan",
        ),
        (
            {"interface_nodes": [interface(), interface("iface.tilt", owner="firmware")]},
            "'iface.tilt' has no consumers entry",
        ),
        (
            {
                "interface_consumers": [
                    {"interface": "iface.drive", "consumers": ["firmware"]},
                    {"interface": "iface.drive", "consumers": ["sizing"]},
                ]
            },
            "'iface.drive' has more than one consumers entry",
        ),
        (
            {"interface_consumers": [{"interface": "iface.drive", "consumers": ["control"]}]},
            "'control' as a consumer, which is a module of its producing role 'control'",
        ),
    ],
    ids=[
        "an unknown module",
        "an unknown interface",
        "a missing entry",
        "a duplicate entry",
        "a producer listed as its own consumer",
    ],
)
def test_consumers_the_plan_cannot_back_are_refused(changes: dict[str, Any], problem: str) -> None:
    found = plan_problems(integrated(**changes), ROLES, BRIEF)
    assert any(problem in p for p in found), found
    cause, detail, _, _, _ = judged(answer(**changes))
    assert cause == "invalid_plan" and problem in detail


def test_an_empty_consumers_list_is_refused_by_the_schema() -> None:
    empty = [{"interface": "iface.drive", "consumers": []}]
    with pytest.raises(ValidationError, match="consumers"):
        integrated(interface_consumers=empty)
    cause, _, _, _, _ = judged(answer(interface_consumers=empty))
    assert cause == "invalid_plan"
    entry = json.loads(plan_schema(ROLES))["$defs"]["InterfaceConsumers"]
    assert entry["properties"]["consumers"]["minItems"] == 1


# --- sizing's module and integration's ----------------------------------------------------


def test_a_plan_with_two_sizing_modules_is_refused() -> None:
    modules = [*GOOD["modules"], module("sizing-two", "sizing")]
    found = plan_problems(integrated(modules=modules), ROLES, BRIEF)
    assert any("2 modules of the sizing role" in p for p in found), found
    # Without integration as well: the rule is sizing's own.
    base = Plan.model_validate_json(
        json.dumps({"modules": modules, "interface_nodes": [interface()]})
    )
    found = plan_problems(base, ("control", "firmware", "sizing"), BRIEF)
    assert any("2 modules of the sizing role" in p for p in found), found


def test_a_plan_with_an_integration_module_is_refused() -> None:
    modules = [*GOOD["modules"], module("checks", "integration")]
    found = plan_problems(integrated(modules=modules), ROLES, BRIEF)
    assert any("'checks' is assigned the integration role" in p for p in found), found


@pytest.mark.parametrize(
    "module_dir",
    [
        "modules/integration",
        "modules/integration/checks",
        "modules",
        # One directory on a file system that ignores case, as the laptop's does.
        "Modules/Integration",
        "modules/INTEGRATION/checks",
        "MODULES",
    ],
)
def test_a_module_overlapping_integration_s_directory_is_refused(module_dir: str) -> None:
    modules = [*GOOD["modules"][:2], module("firmware", "firmware", module_dir=module_dir)]
    found = plan_problems(integrated(modules=modules), ROLES, BRIEF)
    assert any("modules/integration, which the harness keeps" in p for p in found), found


def test_without_integration_its_directory_and_name_are_any_module_s() -> None:
    # Nothing is reserved for a role the run does not have; the plan is judged as before.
    base = Plan.model_validate_json(
        json.dumps(
            {
                "modules": [module("control", "control", module_dir="modules/integration")],
                "interface_nodes": [interface()],
            }
        )
    )
    assert plan_problems(base, DOMAIN_ONLY, BRIEF) == []
    stray = Plan.model_validate_json(
        json.dumps({"modules": [module("checks", "integration")], "interface_nodes": [interface()]})
    )
    # Refused as before, and for that reason only: the run has no model for the role.
    assert plan_problems(stray, DOMAIN_ONLY, BRIEF) == [
        "module 'checks' is assigned a role the run has no model for",
        "interface node 'iface.drive' is owned by a role no module has",
    ]


def test_the_roles_are_found_in_the_register_by_what_they_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A register whose completion owner is not named integration: the plan's rules follow
    # the duty, not the name.
    closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
    monkeypatch.delitem(roles.ROLES, "integration")
    monkeypatch.setitem(roles.ROLES, closer.name, closer)
    run_roles = ("closer", "control", "firmware", "integration", "sizing")
    assert plan_model(run_roles) is IntegratedPlan
    assert plan_model(("control", "firmware", "integration")) is Plan
    assert "Roles available: control, firmware, integration, sizing." in prompt_for(
        BRIEF, run_roles
    )
    modules = [*GOOD["modules"], module("checks", "closer")]
    found = plan_problems(integrated(modules=modules), run_roles, BRIEF)
    assert any("'checks' is assigned the closer role" in p for p in found), found
    ordinary = [*GOOD["modules"], module("checks", "integration")]
    assert plan_problems(integrated(modules=ordinary), run_roles, BRIEF) == []


# --- the prompt ---------------------------------------------------------------------------


def test_the_prompt_carries_the_requirements_sentence_only_with_integration() -> None:
    prompt = prompt_for(BRIEF, ROLES)
    assert prompt.count(REQUIREMENTS_SENTENCE) == 1
    assert "Roles available: control, firmware, sizing.\n" in prompt
    assert prompt.endswith(f"Brief:\n{BRIEF}\n")
    for run_roles in (DOMAIN_ONLY, ("control", "firmware", "sizing")):
        assert "assembled system" not in prompt_for(BRIEF, run_roles)


def test_with_integration_the_prompt_asks_for_criteria_numbered_as_they_are_read() -> None:
    # The system requirements cite module criteria by number, and a number is read only
    # under a heading that names acceptance criteria (the reviewers' own reading). The
    # prompt says so in one sentence, only with integration: the spec it describes, built
    # from the sentence's own heading and numeral, is read with its numbers.
    paragraphs = prompt_for(BRIEF, ROLES).split("\n\n")
    (sentence,) = [p for p in paragraphs if "number" in p and "Acceptance criteria" in p]
    assert sentence.count(". ") == 0 and sentence.endswith(".")
    quoted = sentence.split('"')[1::2]
    (heading,) = [q for q in quoted if q.startswith("#")]
    assert "acceptance criteria" in heading.casefold()
    assert {"1.", "2."} <= set(quoted)
    written = f"Do the work.\n\n{heading}\n\n1. The first holds.\n2. The second holds.\n"
    assert issued_criteria(written) == ("1", "2")
    for run_roles in (DOMAIN_ONLY, ("control", "firmware", "sizing")):
        assert sentence not in prompt_for(BRIEF, run_roles)


# --- the plan's digest --------------------------------------------------------------------


def test_plan_sha256_covers_the_requirements_list() -> None:
    plan = integrated()
    canonical = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    assert plan_sha256(plan) == hashlib.sha256(canonical.encode()).hexdigest()
    assert plan_sha256(integrated()) == plan_sha256(plan)
    changed = [
        integrated(system_requirements=[]),
        integrated(system_requirements=[_requirement("1", ("control", "1"))]),
        integrated(system_requirements=[_requirement("2", ("control", "1"))]),
        integrated(system_requirements=[_requirement("2", ("control", "1"), ("firmware", "3"))]),
        integrated(interface_consumers=[{"interface": "iface.drive", "consumers": ["sizing"]}]),
    ]
    digests = {plan_sha256(p) for p in changed}
    assert len(digests) == len(changed) and plan_sha256(plan) not in digests
