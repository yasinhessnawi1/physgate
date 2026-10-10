"""The default binding answers yes exactly where the loop already sends a subtask to a person.

ARCH-131's ``rules`` binding is the loop's own conditions through the interface, at
confidence 1.0: the third rejection (the repair budget, ARCH-030), a blocked review and
a review with no verdict. Anywhere else it answers no. Through the interface it
therefore never routes by its answer or by the floor, only where the route is forced,
which is what makes the queue the same as before the interface existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

import pytest

from physgate.orchestrator.budget import REPAIR_BUDGET
from physgate.orchestrator.escalation import (
    TO_THE_QUEUE,
    AttemptEnd,
    RulesBackend,
    bind,
)


@dataclass(frozen=True)
class End:
    attempt_end: AttemptEnd
    attempt_count: int


CASES = [(end, attempt) for end in get_args(AttemptEnd) for attempt in range(1, REPAIR_BUDGET + 1)]


def expected(end: str, attempt: int) -> str:
    """ARCH-030 and the two review outcomes with no verdict to act on, spelled out here."""
    if end == "rejected":
        return "yes" if attempt == 3 else "no"
    return "yes"


@pytest.mark.parametrize(("end", "attempt"), CASES)
def test_rules_answers_yes_exactly_where_the_loop_has_nothing_else_to_do(
    end: AttemptEnd, attempt: int
) -> None:
    answered = RulesBackend().decide(TO_THE_QUEUE, End(end, attempt))
    assert answered.answer == expected(end, attempt)
    assert answered.confidence == 1.0


@pytest.mark.parametrize(("end", "attempt"), CASES)
def test_through_the_interface_rules_routes_only_where_the_route_is_forced(
    end: AttemptEnd, attempt: int
) -> None:
    decision = bind("rules").decide(TO_THE_QUEUE, End(end, attempt))
    assert decision.backend_id == "rules"
    assert decision.backend_version == "rules/1"
    assert decision.basis in ("forced", None)
    assert decision.routed is (expected(end, attempt) == "yes")
    assert decision.forced is decision.routed


def test_the_budget_the_rules_read_is_three() -> None:
    assert REPAIR_BUDGET == 3
    assert [expected("rejected", a) for a in (1, 2, 3)] == ["no", "no", "yes"]
