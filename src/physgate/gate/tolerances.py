"""How far an equality between separately declared numbers may miss, and nothing else.

The gate computes in exact fractions, so arithmetic adds no error of its own.
What remains is the rounding in the numbers an agent declares. That matters in
exactly one place: an **equality** between numbers declared separately, such as
the reactions on a mount against its loads, or a module's declared mass against
the sum of its parts. Each side was rounded on its own, so the two can differ
without anything being physically wrong.

**Inequalities get no allowance.** A supply that must cover its consumers, a
value that must lie in its range, a margin that must not be negative: the design
claims those numbers, and rounding is never credited toward a pass.

The allowance is relative, because an allowance of "half a unit in the last digit
written" can be widened by the choice of unit: a moment written as 0 kN*m would
buy half a kilonewton-metre of slack. Each declared term is taken to carry three
significant figures, so its rounding error is at most half a unit in its third
figure, which is at most 0.5 per cent of its magnitude; the worst case of a sum
is the sum of those bounds.

Source for three significant figures: R. C. Hibbeler, *Engineering Mechanics:
Statics*, 14th edition, section 1.6, where answers are rounded to three
significant figures "since most data in engineering mechanics, such as geometry
and loads, may be reliably measured to this accuracy". That wording, and the
junction-to-ambient thermal resistance definition the thermal check uses (Texas
Instruments application note SPRA953, *Semiconductor and IC Package Thermal
Metrics*), were taken from secondary sources on 26.09.2026, not read in the
documents themselves.

This value was fixed before the gate had run on anything, in a commit of its own.
Changing it is a change to what the gate accepts, and is recorded as one.
"""

from __future__ import annotations

from collections.abc import Iterable
from fractions import Fraction

#: Half a unit in the third significant figure, as a share of the magnitude.
ROUNDING_SHARE = Fraction(5, 1000)


def rounding_allowance(terms: Iterable[Fraction]) -> Fraction:
    """The most an equality over ``terms`` can miss by declared rounding alone."""
    return ROUNDING_SHARE * sum((abs(term) for term in terms), Fraction(0))


def holds_within_rounding(residual: Fraction, terms: Iterable[Fraction]) -> bool:
    """True if an equality's ``residual`` is explained by the rounding of its ``terms``.

    ``terms`` is every term of the equation, in one unit, the residual's own.
    """
    return abs(residual) <= rounding_allowance(terms)
