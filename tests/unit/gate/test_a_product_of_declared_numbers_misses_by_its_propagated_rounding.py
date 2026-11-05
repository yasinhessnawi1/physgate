"""A product or quotient of declared numbers may miss by the rounding its factors carry, exactly.

Each declared number is taken as the rounding of a true one to three significant figures, so
the true value lies within a share epsilon of the declared one, either way. A term that
multiplies P declared factors (counted with their powers) and divides by N of them is then off
by at most its own magnitude times ``(1 + epsilon)**P / (1 - epsilon)**N - 1``: the worst case,
taken where every factor above the line is high and every factor below it is low. That bound is
an exact rational, it is reached, and for one plain term it is the gate's existing rule. An
integer coefficient the law carries is exact and adds nothing.

The rule is proven here directly, by checking every corner of the box the true values lie in.
The first-order form of the same rule (fractional uncertainties add for products and quotients)
is J. R. Taylor, *An Introduction to Error Analysis*, 2nd edition, section 3.3, read through a
secondary source; the exact bound exceeds it by a term of second order in epsilon.
"""

from __future__ import annotations

import itertools
import random
from collections.abc import Callable, Iterable
from fractions import Fraction
from types import ModuleType
from typing import Any

import pytest

from physgate.gate import tolerances
from physgate.gate.tolerances import ROUNDING_SHARE, rounding_allowance


def _api(name: str) -> Callable[..., Any]:
    """The tolerance module's ``name``, or a failed test saying the rule is not there yet."""
    module: ModuleType = tolerances
    found = module.__dict__.get(name)
    if not callable(found):
        pytest.fail(f"the gate has no propagated rounding rule ({name}) yet")
    return found  # type: ignore[no-any-return]


def bound(magnitude: Fraction, positive: int, negative: int) -> Fraction:
    result = _api("propagated_bound")(magnitude, positive, negative)
    assert isinstance(result, Fraction), "the bound is an exact rational"
    return result


def allowance(terms: Iterable[tuple[Fraction, int, int]]) -> Fraction:
    result = _api("propagated_allowance")(terms)
    assert isinstance(result, Fraction), "the allowance is an exact rational"
    return result


def refusal(build: Callable[[], object]) -> str:
    """The message ``build`` is refused with; an accepted build fails an assertion."""
    try:
        build()
    except ValueError as exc:
        return str(exc)
    raise AssertionError("accepted, where a refusal was expected")


def worst_corner(declared: list[Fraction], powers: list[int]) -> Fraction:
    """The largest miss of ``prod(declared**powers)`` over every corner of the rounding box."""
    eps = ROUNDING_SHARE
    term = Fraction(1)
    for value, power in zip(declared, powers, strict=True):
        term *= value**power
    worst = Fraction(0)
    for signs in itertools.product((1, -1), repeat=len(declared)):
        true = Fraction(1)
        for value, power, sign in zip(declared, powers, signs, strict=True):
            true *= (value * (1 + sign * eps)) ** power
        worst = max(worst, abs(true - term))
    return worst


def test_one_plain_term_is_the_existing_rule() -> None:
    for value in (Fraction(1), Fraction("12.9"), Fraction("-0.0039"), Fraction(10**6)):
        assert bound(value, 1, 0) == rounding_allowance([value]) == ROUNDING_SHARE * abs(value)


def test_a_product_over_a_quotient_misses_by_six_hundred_and_one_parts_in_39800() -> None:
    # (1 + 1/200)**2 / (1 - 1/200) - 1 = 601/39800, above the first-order 3/200 by 4/39800.
    assert bound(Fraction(1), 2, 1) == Fraction(601, 39800)
    assert bound(Fraction(1), 2, 1) - 3 * ROUNDING_SHARE == Fraction(4, 39800)


def test_the_bound_is_relative_to_the_term_s_magnitude_whatever_its_sign() -> None:
    assert bound(Fraction(-3), 2, 1) == bound(Fraction(3), 2, 1) == 3 * Fraction(601, 39800)
    assert bound(Fraction(0), 3, 2) == 0


def test_a_term_with_no_declared_factor_carries_no_rounding() -> None:
    # An integer the law itself carries is exact.
    assert bound(Fraction(7, 2), 0, 0) == 0


def test_a_quotient_is_wider_than_the_product_of_as_many_factors() -> None:
    # Dividing by a number that may be low by epsilon swings further than multiplying by one
    # that may be high by epsilon: 1/(1 - e) - 1 > (1 + e) - 1.
    assert bound(Fraction(1), 0, 1) == Fraction(1, 199)
    assert bound(Fraction(1), 0, 1) > bound(Fraction(1), 1, 0)
    assert bound(Fraction(1), 1, 2) > bound(Fraction(1), 2, 1)


@pytest.mark.parametrize(
    "powers",
    [[1], [2], [1, 1], [1, -1], [2, -1], [1, 1, -1], [3], [-2], [1, -1, -1], [2, 1, -3]],
)
def test_the_bound_is_the_worst_corner_of_the_rounding_box_exactly(powers: list[int]) -> None:
    rng = random.Random(f"propagated-{powers}")
    for _ in range(5):
        declared = [Fraction(rng.randint(1, 9999), rng.choice((1, 10, 100, 1000))) for _ in powers]
        term = Fraction(1)
        for value, power in zip(declared, powers, strict=True):
            term *= value**power
        positive = sum(p for p in powers if p > 0)
        negative = -sum(p for p in powers if p < 0)
        assert bound(term, positive, negative) == worst_corner(declared, powers)


def test_an_equality_s_allowance_is_the_sum_of_its_terms_bounds() -> None:
    terms = [(Fraction("12.9"), 1, 0), (Fraction("12.87"), 2, 0), (Fraction(-4), 2, 1)]
    assert allowance(terms) == sum(bound(t, p, n) for t, p, n in terms)
    assert allowance([]) == 0


def test_over_plain_terms_the_allowance_is_the_existing_one() -> None:
    rng = random.Random("plain-terms")
    for _ in range(20):
        terms = [Fraction(rng.randint(-(10**6), 10**6), 1000) for _ in range(rng.randint(1, 6))]
        assert allowance((t, 1, 0) for t in terms) == rounding_allowance(terms)


def test_a_count_of_factors_below_zero_is_refused() -> None:
    assert "factors" in refusal(lambda: bound(Fraction(1), -1, 0))
    assert "factors" in refusal(lambda: bound(Fraction(1), 0, -2))
