"""Every decomposition prompt says a plan fixes interfaces and criteria, never a solution's law.

The decomposition reads nothing but its prompt. A plan that writes a reference implementation's
control law into a specification, and its tuned coefficients onto an interface node, leaves the
module that designs the controller no way to meet a margin the law cannot meet: its
specification forbids another law, and no session may write an interface node (ARCH-011). So the
rule is stated in every prompt, in one paragraph after the words that ask for the modules and
interfaces: a specification states interfaces and acceptance criteria, never a solution's
internal law, structure or coefficients the brief does not fix; a reference the brief cites is a
source of numbers only; an interface node holds signals, units, rates and limits, never tuned
parameters; and where one module implements what another designs, the designer comes first and
writes its design on a node of its own, and the implementer's criteria compare it with that node
as merged. A re-plan is sent the same prompt, so it is told the rule too.

No check in code tells a tuned coefficient on an interface node from a limit or a rate: a
quantity's name and unit say neither, so a plan that puts a law's coefficients on an interface
node passes ``plan_problems`` as it did before. The plan review judges it, from its rubric.
"""

from __future__ import annotations

import pytest
import test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan as pairs

from physgate import roles
from physgate.orchestrator.decompose import ReplanFindings, prompt_for, replan_prompt

BRIEF = "Build a robot."

#: Every set of roles the prompt differs by: domain roles alone, sizing alone, integration alone,
#: and both.
RUN_ROLES = [
    ("control", "firmware"),
    ("electrical",),
    ("control", "electrical", "firmware", "mechanical"),
    ("control", "firmware", "sizing"),
    ("control", "firmware", "integration"),
    pairs.BOTH,
]

#: What the paragraph must say, each in words the plan's reader cannot read another way.
SAID = (
    "interfaces and acceptance criteria",
    "never the internal law, structure or coefficients of a solution",
    "the brief does not itself fix",
    "a reference implementation the brief cites is a source of numbers only",
    "an interface node holds signals, units, rates and limits",
    "never a solution's tuned parameters",
    "one module to implement what another designs",
    "the designing module comes first in the plan",
    "writes its design on a node of its own",
    "acceptance criteria compare its implementation with that node as merged",
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def _paragraphs(prompt: str) -> list[str]:
    """The prompt's paragraphs that speak of a solution's law."""
    return [p for p in prompt.split("\n\n") if "law, structure or coefficients" in p]


@pytest.mark.parametrize("parts", [False, True], ids=["no parts", "parts"])
@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_every_prompt_states_the_rule_once_in_one_paragraph(
    run_roles: tuple[str, ...], parts: bool
) -> None:
    prompt = prompt_for(BRIEF, run_roles, parts=parts)
    found = _paragraphs(prompt)
    assert len(found) == 1, found
    (paragraph,) = found
    for words in SAID:
        assert words in paragraph, (words, paragraph)
    assert "\n" not in paragraph


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_the_rule_follows_the_request_for_modules_and_interfaces_and_precedes_the_brief(
    run_roles: tuple[str, ...],
) -> None:
    prompt = prompt_for(BRIEF, run_roles)
    paragraphs = prompt.split("\n\n")
    (rule,) = _paragraphs(prompt)
    asked = next(i for i, p in enumerate(paragraphs) if p.startswith("For each module give"))
    assert paragraphs.index(rule) == asked + 1
    assert prompt.index(rule) < prompt.index("Answer by calling StructuredOutput once.")
    assert prompt.index(rule) < prompt.index(f"Brief:\n{BRIEF}\n")


def test_the_rule_is_the_same_words_for_every_set_of_roles() -> None:
    # Generated from nothing the run plans: the same paragraph whatever its roles.
    said = {_paragraphs(prompt_for(BRIEF, run_roles))[0] for run_roles in RUN_ROLES}
    assert len(said) == 1, said


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_a_replan_is_told_the_rule_too(run_roles: tuple[str, ...]) -> None:
    (rule,) = _paragraphs(prompt_for(BRIEF, run_roles))
    again = replan_prompt(BRIEF, run_roles, pairs.integrated(), ReplanFindings("found", False))
    assert again.count(rule) == 1
