"""Units written by roles, parsed at a bounded cost: the spelling a unit must have first.

A role writes unit strings (on a graph quantity, on an axis of a simulation record), and
the unit registry that reads them evaluates any arithmetic in the string exactly, in
fractions. A length bound does not bound that work: the twelve characters ``10**10**10*m``
kept one process busy until a 5 s CPU limit killed it (16.10.2026, pint 0.26.1). So a unit
is held to a spelling before the registry ever sees it:

- named units (any letters, so ``µm`` and ``Ω`` too, and underscores; no digits), joined
  by ``*`` and ``/`` with optional spaces;
- each with an optional exponent of one or two digits, which may be negative;
- or a leading ``1`` (``1/s``);
- at most :data:`MAX_LENGTH` characters, matched whole (a trailing newline does not slip
  past an end-of-line anchor).

Nothing else: no numbers as factors, no brackets, no exponent towers. Every unit a
simulation's axis or the physics gate's catalogue carries fits it. The worst a matching
unit can cost is about a millisecond: a 64-character unit of maximal exponents parsed in
0.91 ms (n = 1, laptop, pint 0.26.1).

This module imports nothing but the standard library's ``re``, so that the physics gate
can use it too without widening what its import fence admits by more than this one name.
The simulation-record format uses it today; the gate's own unit parser does not yet.
"""

from __future__ import annotations

import re

#: The longest unit, the same bound the physics gate's parser holds a unit to.
MAX_LENGTH = 64
#: One named unit with an optional small exponent.
FACTOR = r"[^\W\d]+(?:(?:\*\*|\^)-?[0-9]{1,2})?"
#: A whole unit, matched with ``fullmatch``.
PATTERN = rf"(?:1|{FACTOR})(?:[ ]*[*/][ ]*{FACTOR})*"
UNIT_SPELLING = re.compile(PATTERN)


class UnitSpellingError(ValueError):
    """A unit is not spelt so that parsing it has a bounded cost."""


def require_bounded_spelling(unit: str) -> str:
    """``unit``, if parsing it costs a bounded amount; refused before any parse otherwise.

    Raises:
        UnitSpellingError: it is longer than :data:`MAX_LENGTH`, or not a product of named
            units with small integer powers.
    """
    if len(unit) > MAX_LENGTH or not UNIT_SPELLING.fullmatch(unit):
        msg = (
            f"the unit {unit[:MAX_LENGTH]!r} is not a product of named units with small "
            "integer powers (for example m, rad/s, kg*m/s**2); a unit holds no numbers or "
            f"brackets, and at most {MAX_LENGTH} characters"
        )
        raise UnitSpellingError(msg)
    return unit
