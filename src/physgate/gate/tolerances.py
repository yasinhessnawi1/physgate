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

**Products and quotients of declared numbers** (a law's terms, such as a voltage times a
current) carry the rounding of every factor. Each declared factor x is the rounding of a true
value within ``ROUNDING_SHARE`` of it either way, so a term t = c * prod(x_i ** k_i), with an
exact coefficient c, has true over declared value prod((x_i / x_hat_i) ** k_i). That ratio is
largest where every factor above the line is high and every factor below it is low:
``(1 + e) ** P / (1 - e) ** N``, with P the sum of the positive powers and N the sum of the
negative ones taken positive. Its smallest value is ``(1 - e) ** P / (1 + e) ** N``, and the
upper swing is the larger, so the term is off by at most
``|t| * ((1 + e) ** P / (1 - e) ** N - 1)``. The bound is reached, so it is the worst case, and
it is an exact rational. For one plain term (P = 1, N = 0) it is the rule above, unchanged; a
sum of plain terms has exactly the allowance it had. An equality between sums of such terms may
miss by the sum of their bounds and no more, and an inequality still gets nothing.

The first-order form of this rule, that fractional uncertainties add for products and
quotients, is J. R. Taylor, *An Introduction to Error Analysis*, 2nd edition, section 3.3,
taken from a secondary source on 05.11.2026 and not read in the book. The rule here does not
rest on it: it rests on the worst-case argument above, which the tests check corner by corner.
It exceeds the first-order sum by a term of second order in the share (601/39800 against
3/200 for two factors over one). It was fixed in a commit of its own, before any law ran on a
real design.
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


def propagated_bound(term: Fraction, positive: int, negative: int) -> Fraction:
    """The most ``term`` can be off by from the rounding of its declared factors.

    ``positive`` is the sum of the powers of the declared factors above the line, and
    ``negative`` the sum of those below it, taken positive; a coefficient the law carries is
    exact and counts in neither.

    Raises:
        ValueError: a count of factors is below zero.
    """
    if positive < 0 or negative < 0:
        msg = "a term's counts of declared factors are never below zero"
        raise ValueError(msg)
    swing = (1 + ROUNDING_SHARE) ** positive / (1 - ROUNDING_SHARE) ** negative - 1
    return abs(term) * swing


def propagated_allowance(terms: Iterable[tuple[Fraction, int, int]]) -> Fraction:
    """The most an equality over ``terms`` can miss by the rounding of their declared factors.

    Each term is ``(value, positive, negative)``, as :func:`propagated_bound` reads it, every
    value in one unit, the residual's own.
    """
    return sum((propagated_bound(t, p, n) for t, p, n in terms), Fraction(0))
