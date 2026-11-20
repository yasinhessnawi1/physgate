"""Every decomposition prompt says a criterion is written only against what the run can measure.

A plan once gave firmware acceptance criteria measured "on the board" in a run with no board, so no
session could produce the evidence and every attempt was rejected for it; plans of earlier runs had
named a simulator on their own, which is planner variance, not a rule. The plan is written before a
person says which parts they have, so the prompt takes no board as connected unless the brief says
so. Without a board, behaviour on the target is checked in a simulator only where the run's
environment provides one: the prompt promises none, since a run environment may give firmware a
compiler and no simulator, and it names no product, since it does not know which is installed.
Otherwise a criterion is written against what can be measured (that the code compiles without a
warning in the module's own files, its size, and a check of its logic with the tools the
environment provides), and the specification says behaviour on the target is not measured in this
run. It names no instrument the run's environment may lack (a static analyser, a host compiler for
tests): a criterion written against one could not be evaluated and would block the module. Nor
does it ask for a build with no warning at all, which the board's own core and libraries print on
every build. The same plan gave firmware no
value for its command timeout, its sensor-fault rule, its reset state, its limits or its bus
timeout, so firmware could only end blocked; the prompt asks each specification to state every
limit, timeout and fault behaviour its module must implement, with a value. A module's own limit
put on an interface node would be one no other module reads, against the interface paragraph's
rule, so the sentence names an interface node for one only where both sides must agree on its
value.

Both sentences end the paragraph that says how one criterion is written, so a re-plan is told them
too. The method of verification stays one of the four the review counts: a check in a simulator,
a build or a check of the logic is a test, so the paragraph still names no fifth method.
"""

from __future__ import annotations

import pytest
import test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan as pairs
from test_every_acceptance_criterion_is_one_statement_with_its_verification_method import (
    BRIEF,
    NOT_SAID,
    RUN_ROLES,
)

from physgate import roles
from physgate.orchestrator.decompose import (
    CRITERION_FORM_SENTENCE,
    ReplanFindings,
    prompt_for,
    replan_prompt,
)

INSTRUMENT = (
    "Write each criterion only against what the run's environment can measure. No board is "
    "connected unless the brief says so; without one, behaviour on the target is checked in a "
    "simulator only where the run's environment provides one, and otherwise the criterion is "
    "written against what can be measured (that the code compiles without a warning in the "
    "module's own files, its size, and a check of its logic with the tools the environment "
    "provides) and the specification states that behaviour on the target is not measured in this "
    "run."
)
STATED = (
    "Each module's specification states, with a value, every limit, timeout and fault behaviour "
    "the module must implement, and names the interface node that carries one only where both "
    "sides must agree on its value."
)
#: Products the prompt does not know are installed, so it names none of them.
NOT_NAMED = ("simavr", "avr-gcc", "platformio", "arduino-cli", "qemu", "renode")
#: Words that would promise the run's environment has a simulator, a static analyser or a host
#: compiler.
PROMISED = (
    "a simulator of its processor that",
    "simulator the run's environment has",
    "static checks",
    "on the host",
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def test_the_sentences_end_the_paragraph_on_a_criterion_s_form() -> None:
    assert CRITERION_FORM_SENTENCE.endswith(
        f"outside the acceptance criteria. {INSTRUMENT} {STATED}"
    )
    for words in NOT_SAID:
        assert words not in CRITERION_FORM_SENTENCE, words
    for product in NOT_NAMED:
        assert product not in CRITERION_FORM_SENTENCE.lower(), product
    for words in PROMISED:
        assert words not in CRITERION_FORM_SENTENCE, words


@pytest.mark.parametrize("parts", [False, True], ids=["no parts", "parts"])
@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_every_prompt_and_every_replan_says_them_once(
    run_roles: tuple[str, ...], parts: bool
) -> None:
    prompt = prompt_for(BRIEF, run_roles, parts=parts)
    again = replan_prompt(
        BRIEF, run_roles, pairs.integrated(), ReplanFindings("found", False), parts=parts
    )
    for said in (INSTRUMENT, STATED):
        assert prompt.count(said) == 1, said
        assert again.count(said) == 1, said
