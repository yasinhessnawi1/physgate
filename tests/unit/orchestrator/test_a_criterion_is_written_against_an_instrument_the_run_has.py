"""Every decomposition prompt says a criterion is written against an instrument the run has.

A plan once gave firmware acceptance criteria measured "on the board" in a run with no board, so no
session could produce the evidence and every attempt was rejected for it; plans of earlier runs had
named a simulator on their own, which is planner variance, not a rule. The plan is written before a
person says which parts they have, so the prompt takes no board as connected unless the brief says
so: behaviour on the target is then checked in a simulator of its processor that the run's
environment has, named in the criterion. The prompt names no simulator product, since it does not
know which one is installed. The same plan gave firmware no value for its command timeout, its
sensor-fault rule, its reset state, its limits or its bus timeout, so firmware could only end
blocked; the prompt asks each specification to state every limit, timeout and fault behaviour its
module must implement, with a value or the node that will carry it.

Both sentences end the paragraph that says how one criterion is written, so a re-plan is told them
too. The method of verification stays one of the four the review counts: a check in a simulator is
a test, so the paragraph still names no fifth method.
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
    "Write each criterion against an instrument the run's environment has: no board is connected "
    "unless the brief says so, so behaviour on the target is otherwise checked in a simulator of "
    "its processor that the run's environment has, named in the criterion."
)
STATED = (
    "Each module's specification states, with a value or the node that will carry it, every "
    "limit, timeout and fault behaviour the module must implement."
)
#: Products the prompt does not know are installed, so it names none of them.
NOT_NAMED = ("simavr", "avr-gcc", "arduino-cli", "qemu", "renode")


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
