"""How closely a graph quantity must agree with the value read off the record it names.

**Frozen before any record existed.** This file is committed on its own, before the code that
reads a value off a record and before any role has recorded one, so the bar was not chosen by
looking at what passes it. It is changed only by a new decision taken before new data, never
to admit a result.

The bar is three significant figures, relative: the quantity ``q`` and the value ``e`` read
off the record agree when ``|q - e| <= 0.005 * max(|q|, |e|)``, and two zeros agree. It is
the convention the physics gate already holds declared numbers to (an equality within
three-significant-figure rounding), so a margin written to three figures from the very
sweep it was read off agrees, and one written from another computation may not: measured
on analytic loops, a sampled sensitivity peak of a lightly damped loop sat 0.6 % from the
true peak on a 300-point grid and 28 % at a damping ratio of 0.05. A role therefore reports
the value it reads off its own recorded samples with the published extractors.

The comparison is exact: both numbers enter as fractions of their decimal spelling, so no
rounding in the comparison itself moves the bar.
"""

from __future__ import annotations

from fractions import Fraction

#: The relative tolerance: three significant figures.
RELATIVE_TOLERANCE = Fraction(5, 1000)


def _exact(value: float | int) -> Fraction:
    return Fraction(repr(value)) if isinstance(value, float) else Fraction(value)


def agrees(quantity: float | int, extracted: float | int) -> bool:
    """Whether ``quantity`` agrees with ``extracted`` within :data:`RELATIVE_TOLERANCE`."""
    q, e = _exact(quantity), _exact(extracted)
    if q == 0 and e == 0:
        return True
    return abs(q - e) <= RELATIVE_TOLERANCE * max(abs(q), abs(e))
