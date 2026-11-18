"""Every decomposition prompt says how one acceptance criterion is written.

The plan review reads each criterion of every specification for two things of form: that it says
how it is verified, as one of the four methods of verification (analysis, demonstration,
inspection, test), and that it states one requirement in "shall" form, not a value bundled with a
second check. Plans written to a prompt that said neither failed the review on both, whatever
their design: criteria gave a value with no method, and one numbered line held a value with its
agreement with another quantity, a value with a rule for the rest of the module, several margins,
or a figure with a setting. The decomposition reads nothing but its prompt, so the form is stated
in every prompt, in one paragraph after the paragraph saying a plan fixes interfaces and criteria
and never a solution's law: one statement of one thing, "The <module> shall <verb> <what>,
<threshold with its unit and tolerance>, verified by <method>.", the method one of the four,
named by its word; no threshold where no figure is set; each criterion's trace to the brief, or
its reason as derived; a requirement with several figures or conditions written as one criterion
for each; and a goal in "should", outside the criteria. A re-plan is sent the same prompt, so it
is told the form too.

No check in code holds a criterion to a method: whether a word names how the criterion is
verified, or only appears in it, is read, not matched. The plan review judges it, from its rubric.
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

#: What the paragraph must say, each in the words the plan review reads a criterion's form in.
SAID = (
    "Write each acceptance criterion as one statement of one thing",
    # The form, in "shall", with the method last.
    '"The <module> shall <verb> <what>, <threshold with its unit and tolerance>, verified by '
    '<method>."',
    # The four methods, by the words the review looks for, and nothing looser.
    "the method is one of analysis, demonstration, inspection or test, named by that word in the "
    "criterion",
    # A structural criterion is not forced to invent a figure.
    "a criterion that sets no figure has no threshold",
    # A split criterion still traces.
    "each criterion names the brief requirement it traces to or says it is derived and why",
    # The bundles, in general terms: each kind a plan has written as one criterion.
    "A requirement that holds several figures or conditions",
    "a value and its agreement with another quantity",
    "a value and a rule for the rest of the module",
    "two margins",
    "a figure and a setting",
    "becomes one criterion for each, so that each is met or unmet on its own",
    'A goal is written with "should", outside the acceptance criteria.',
)

#: Words the paragraph must not hold: each lets a criterion through without its method, or with
#: a method the review does not count as one.
NOT_SAID = (
    # A method that is optional, or left to the reader to infer.
    "where possible",
    "or implied",
    # A method other than the four, which the review does not read as one.
    "or measurement",
    "or simulation",
    # Two methods for one criterion.
    "analysis or test",
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def _form(prompt: str) -> str:
    """The one paragraph that states the form; a prompt with none or two fails on an assertion."""
    found = [p for p in prompt.split("\n\n") if "verified by <method>" in p]
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("parts", [False, True], ids=["no parts", "parts"])
@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_every_prompt_states_the_form_once_in_one_paragraph(
    run_roles: tuple[str, ...], parts: bool
) -> None:
    paragraph = _form(prompt_for(BRIEF, run_roles, parts=parts))
    for words in SAID:
        assert paragraph.count(words) == 1, words
    for words in NOT_SAID:
        assert words not in paragraph, words
    assert "\n" not in paragraph


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_the_form_follows_the_rule_on_a_solution_s_law_and_precedes_the_brief(
    run_roles: tuple[str, ...],
) -> None:
    prompt = prompt_for(BRIEF, run_roles)
    paragraphs = prompt.split("\n\n")
    form = _form(prompt)
    rule = next(i for i, p in enumerate(paragraphs) if "law, structure or coefficients" in p)
    assert paragraphs.index(form) == rule + 1
    assert prompt.index(form) < prompt.index("Answer by calling StructuredOutput once.")
    assert prompt.index(form) < prompt.index(f"Brief:\n{BRIEF}\n")


def test_the_form_is_the_same_words_for_every_set_of_roles() -> None:
    # Generated from nothing the run plans: the same paragraph whatever its roles.
    said = {_form(prompt_for(BRIEF, run_roles)) for run_roles in RUN_ROLES}
    assert len(said) == 1, said


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_a_replan_is_told_the_form_too(run_roles: tuple[str, ...]) -> None:
    form = _form(prompt_for(BRIEF, run_roles))
    again = replan_prompt(BRIEF, run_roles, pairs.integrated(), ReplanFindings("found", False))
    assert again.count(form) == 1
