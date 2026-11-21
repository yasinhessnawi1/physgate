"""A value that is NaN, infinite or a bool is refused in words that say so.

The decision's own parser refuses such a value before it reaches the unit check, but the check
is a function of its own and is also called on a value built without it. It must not say that
the unit is one pint cannot read, which it was not.
"""

from __future__ import annotations

from typing import Any

import pytest

from physgate.orchestrator.queue import DeclaredValue, declared_problem


@pytest.mark.parametrize("name", ["mass", "own_note"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, False])
def test_a_value_that_is_no_finite_number_says_so_and_does_not_blame_the_unit(
    name: str,
    value: Any,  # noqa: ANN401
) -> None:
    told = declared_problem(name, DeclaredValue.model_construct(value=value, unit="kg"))
    assert told is not None
    assert "finite number" in told
    assert "pint" not in told and "unit" not in told


def test_a_finite_number_in_its_unit_is_still_accepted() -> None:
    assert declared_problem("mass", DeclaredValue(value=0.4, unit="kg")) is None
