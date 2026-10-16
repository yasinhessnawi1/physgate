"""The tolerance a quantity is held to against its record: three significant figures, exactly.

Each case sits on, just inside or just outside the bar, so a tolerance moved in either
direction turns one of them red.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from physgate.series.tolerance import RELATIVE_TOLERANCE, agrees


def test_the_bar_is_three_significant_figures() -> None:
    assert Fraction(5, 1000) == RELATIVE_TOLERANCE


@pytest.mark.parametrize(
    ("quantity", "extracted"),
    [
        (0.625, 0.625),
        (1.0, 1.005),
        (1.005, 1.0),
        (-1.0, -1.005),
        (0.0, 0.0),
        (0, 0),
        (2, 2.01),
        (1e-9, 1.004e-9),
    ],
)
def test_values_within_the_bar_agree(quantity: float, extracted: float) -> None:
    assert agrees(quantity, extracted)


@pytest.mark.parametrize(
    ("quantity", "extracted"),
    [
        (1.0, 1.00503),
        (1.00503, 1.0),
        (0.0, 1e-12),
        (1.0, -1.0),
        (0.625, 0.6215),
        (2, 2.0102),
    ],
)
def test_values_beyond_the_bar_do_not(quantity: float, extracted: float) -> None:
    assert not agrees(quantity, extracted)


def test_the_comparison_is_exact_on_the_decimal_spelling() -> None:
    # 0.995 against 1.0 sits exactly on the bar. In binary floats 1.0 - 0.995 is
    # 0.0050000000000000044, just outside it; on the decimal spelling it is exactly 0.005.
    assert 1.0 - 0.995 > 0.005 * 1.0
    assert agrees(0.995, 1.0)
    assert not agrees(0.9949, 1.0)
