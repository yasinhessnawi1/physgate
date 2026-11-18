"""Every decomposition prompt says which quantities go on an interface node, and who names them.

The plan review fails an interface quantity that no module other than its producer reads: a
quantity on an interface node is there because another module needs it, and one that no
specification reads is an orphan. Plans told to state every quantity with its unit and source
put quantities only their producer uses (a switching frequency firmware alone reads, a ratio or
a rating no consuming specification names) on the shared nodes, and failed the review on them.
The decomposition reads nothing but its prompt, so the rule is stated in every prompt, in the
paragraph that says what an interface node holds, directly after it says so: a quantity goes on
an interface node only where another module's specification reads it by name; one only its own
module uses stays in that module's specification, off every interface node; and each quantity
on an interface node is named, as the node names it, in the specification of every module that
reads it. A re-plan is sent the same prompt, so it is told the rule too.

No check in code refuses a plan for an orphan: a specification is prose, and whether it reads a
quantity or only mentions a word of its name is read, not matched. The plan review judges it,
from its rubric.
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

#: What an interface node holds, as the paragraph says it: the sentence follows these words.
HOLDS = "never a solution's tuned parameters. "

#: The sentence, whole, in the words the review reads an orphan in.
SENTENCE = (
    "A quantity goes on an interface node only where the specification of at least one module "
    "other than the one that produces it reads it by name; a quantity that only its own module "
    "uses stays in that module's specification, off every interface node; and each quantity on "
    "an interface node is named, as the node names it, in the specification of every module that "
    "reads it."
)

#: Words the paragraph must not hold: each lets a quantity no other module reads onto a node.
NOT_SAID = (
    # A producer counted as its own reader.
    "or its producer",
    "including its producer",
    # A rule left to the planner's taste.
    "where possible",
    "preferably",
    # A node as the default home of every quantity a module states.
    "every quantity a module states goes on an interface node",
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def _holds(prompt: str) -> str:
    """The one paragraph that says what an interface node holds; none or two fail an assertion."""
    found = [p for p in prompt.split("\n\n") if "An interface node holds what both sides" in p]
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("parts", [False, True], ids=["no parts", "parts"])
@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_every_prompt_states_the_rule_once_after_what_a_node_holds(
    run_roles: tuple[str, ...], parts: bool
) -> None:
    prompt = prompt_for(BRIEF, run_roles, parts=parts)
    paragraph = _holds(prompt)
    assert prompt.count(SENTENCE) == 1
    assert paragraph.count(f"{HOLDS}{SENTENCE} ") == 1
    for words in NOT_SAID:
        assert words not in paragraph, words
    assert "\n" not in paragraph


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_the_rule_precedes_the_brief(run_roles: tuple[str, ...]) -> None:
    prompt = prompt_for(BRIEF, run_roles)
    assert prompt.index(SENTENCE) < prompt.index("Answer by calling StructuredOutput once.")
    assert prompt.index(SENTENCE) < prompt.index(f"Brief:\n{BRIEF}\n")


def test_the_paragraph_is_the_same_words_for_every_set_of_roles() -> None:
    # Generated from nothing the run plans: the same paragraph whatever its roles.
    said = {_holds(prompt_for(BRIEF, run_roles)) for run_roles in RUN_ROLES}
    assert len(said) == 1, said


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_a_replan_is_told_the_rule_too(run_roles: tuple[str, ...]) -> None:
    again = replan_prompt(BRIEF, run_roles, pairs.integrated(), ReplanFindings("found", False))
    assert again.count(SENTENCE) == 1
