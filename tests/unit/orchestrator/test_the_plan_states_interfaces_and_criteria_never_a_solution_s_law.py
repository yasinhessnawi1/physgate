"""Every decomposition prompt says a plan fixes interfaces and criteria, never a solution's law.

The decomposition reads nothing but its prompt. A plan that writes a reference implementation's
control law into a specification, and its tuned coefficients onto an interface node, leaves the
module that designs the controller no way to meet a margin the law cannot meet: its
specification forbids another law, and no session may write an interface node (ARCH-011). So the
rule is stated in every prompt, in one paragraph after the words that ask for the modules and
interfaces: a specification states interfaces and acceptance criteria, never a solution's
internal law, structure or coefficients unless the brief fixes them; the brief fixes a method only
where one of its requirements says, in its own words, that the design shall use, run or contain
it, and a program it cites for a number, a part or a condition is a source of those only; an
interface node holds what both sides must agree on, the physical properties one side gives the
other among them, never tuned parameters; and where one module implements what another designs,
whether or not a criterion says so, the designer comes before the implementer, writes its design
on a node of its own that both specifications name, its id the designing module's name and then
what it holds (the harness reads the pair from that id), and the implementer's criteria compare it
with that node as merged; an implementer that starts before the node is merged reports it and
implements no design of its own. A re-plan is sent the same prompt, so it is told the rule too.

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
    "never the internal law, structure or coefficients of a solution, unless the brief fixes them",
    # What "fixes" means: a requirement's own words, not a citation.
    "The brief fixes a method only where one of its requirements, in its own words, says the "
    "design shall use, run or contain it",
    "a program or document the brief cites as the source of a number, a part or a condition is a "
    "source of those only",
    # What an interface node holds, physical properties included.
    "An interface node holds what both sides must agree on before either works",
    "the signals that cross, with their units and rates",
    "the limits both sides hold to",
    "the physical properties one side gives the other, such as a mass or a motor constant",
    "never a solution's tuned parameters",
    # The designer's node: wherever one module implements another's design.
    "Where one module implements what another designs",
    "the designing module comes before the implementing module in the plan",
    'writes its design on a node of its own, "<the designing module\'s name>.<what it holds>", '
    "named in both specifications",
    "acceptance criteria compare its implementation with that node as merged",
    "where the node is not merged when it starts, it reports that and implements no design of its "
    "own",
)

#: Words the paragraph must not hold: each can be read more narrowly than the rule means.
NOT_SAID = (
    # A closed list that leaves out a mass or a motor constant.
    "signals, units, rates and limits",
    # A route conditioned on a criterion that requires it.
    "Where the brief requires",
    # An order that reads as ahead of every module.
    "comes first in the plan",
    # A citation that is a source of numbers whatever the brief requires.
    "a reference implementation the brief cites is a source of numbers only",
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def _paragraphs(prompt: str) -> list[str]:
    """The prompt's paragraphs that speak of a solution's law."""
    return [p for p in prompt.split("\n\n") if "law, structure or coefficients" in p]


def _rule(prompt: str) -> str:
    """The one paragraph that states the rule; a prompt with none or two fails on an assertion."""
    found = _paragraphs(prompt)
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("parts", [False, True], ids=["no parts", "parts"])
@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_every_prompt_states_the_rule_once_in_one_paragraph(
    run_roles: tuple[str, ...], parts: bool
) -> None:
    prompt = prompt_for(BRIEF, run_roles, parts=parts)
    paragraph = _rule(prompt)
    for words in SAID:
        assert words in paragraph, (words, paragraph)
    for words in NOT_SAID:
        assert words not in paragraph, (words, paragraph)
    assert "\n" not in paragraph


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_the_rule_follows_the_request_for_modules_and_interfaces_and_precedes_the_brief(
    run_roles: tuple[str, ...],
) -> None:
    prompt = prompt_for(BRIEF, run_roles)
    paragraphs = prompt.split("\n\n")
    rule = _rule(prompt)
    asked = next(i for i, p in enumerate(paragraphs) if p.startswith("For each module give"))
    assert paragraphs.index(rule) == asked + 1
    assert prompt.index(rule) < prompt.index("Answer by calling StructuredOutput once.")
    assert prompt.index(rule) < prompt.index(f"Brief:\n{BRIEF}\n")


def test_the_rule_is_the_same_words_for_every_set_of_roles() -> None:
    # Generated from nothing the run plans: the same paragraph whatever its roles.
    said = {_rule(prompt_for(BRIEF, run_roles)) for run_roles in RUN_ROLES}
    assert len(said) == 1, said


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_a_replan_is_told_the_rule_too(run_roles: tuple[str, ...]) -> None:
    rule = _rule(prompt_for(BRIEF, run_roles))
    again = replan_prompt(BRIEF, run_roles, pairs.integrated(), ReplanFindings("found", False))
    assert again.count(rule) == 1
