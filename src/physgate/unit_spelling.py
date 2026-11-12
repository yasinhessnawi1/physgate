"""Units written by roles, parsed at a bounded cost: the spelling a unit must have first.

A role writes unit strings (on a graph quantity, on an axis of a simulation record), and
the unit registry that reads them evaluates any arithmetic in the string exactly, in
fractions. A length bound does not bound that work: the twelve characters ``10**10**10*m``
kept one process busy until a 5 s CPU limit killed it (16.10.2026, pint 0.26.1). So a unit
is held to a spelling before the registry ever sees it:

- named units, spelt in ASCII letters and underscores and three letters units use, the
  micro sign ``µ``, the Greek ``μ`` and the ohm ``Ω``; joined by ``*`` and ``/`` with
  optional spaces. Not "any letter": the registry reads a superscript digit as an
  exponent, which a Unicode letter class admits as a letter, so ``km⁹⁹⁹⁹⁹⁹⁹⁹`` parsed as
  the kilometre to the 99,999,999th power and converting it ran until a 5 s CPU limit
  killed it (16.10.2026, n = 1); and a full-width or numeral letter reads differently to
  the registry than to this check;
- each with an optional exponent of one or two digits, which may be negative;
- or a leading ``1`` (``1/s``);
- after a ``/``, a bracketed product of such units (``1/(rad*s)``, ``V/(m*s)``), which is read
  as the chain of divisions it means (``1/rad/s``, ``V/m/s``): :func:`require_bounded_spelling`
  returns that product, so the registry is handed no bracket. Two spellings of one unit
  compare equal in the form :func:`canonical_unit` gives, not in that product, which keeps
  the order and the powers as written;
- at most :data:`MAX_LENGTH` characters, matched whole (a trailing newline does not slip
  past an end-of-line anchor).

Nothing else: no numbers as factors, no bracket inside a bracket or anywhere but a
denominator, no exponent towers. Every unit a simulation's axis or the physics gate's
catalogue carries fits it. A refusal names the spelling this grammar takes for the unit it
refused, where one exists (:func:`accepted_spelling`): in a full run a role wrote ``1/(rad*s)``
again and again while the grammar refused brackets and named no other spelling. The worst a matching
unit costs is milliseconds, conversion included: the largest prefix at the largest exponent,
``Ym**99`` nine times over (62 characters), parsed in 0.54 ms and converted to base units in
2.21 ms, a factor near 10**21384; n = 1 each, laptop, pint 0.26.1.

This module imports nothing but the standard library's ``re``, so that the physics gate
can use it too without widening what its import fence admits by more than this one name.
The simulation-record format and the physics gate's own unit parser use it. The series
writer, which runs alone in a role's interpreter, carries a copy of the grammar and of
:func:`accepted_spelling` that a test holds to be the same code.
"""

from __future__ import annotations

import re

#: The longest unit, the same bound the physics gate's parser holds a unit to.
MAX_LENGTH = 64
#: One named unit with an optional small exponent.
FACTOR = r"[A-Za-z_\u00b5\u03bc\u03a9]+(?:(?:\*\*|\^)-?[0-9]{1,2})?"
#: A bracketed product of named units, taken only as a denominator: ``/(rad*s)``.
DENOMINATOR = rf"\([ ]*{FACTOR}(?:[ ]*\*[ ]*{FACTOR})*[ ]*\)"
#: A whole unit, matched with ``fullmatch``.
PATTERN = rf"(?:1|{FACTOR})(?:[ ]*\*[ ]*{FACTOR}|[ ]*/[ ]*(?:{FACTOR}|{DENOMINATOR}))*"
UNIT_SPELLING = re.compile(PATTERN)
_BRACKETED = re.compile(rf"[ ]*/[ ]*({DENOMINATOR})")
_FACTOR = re.compile(FACTOR)


class UnitSpellingError(ValueError):
    """A unit is not spelt so that parsing it has a bounded cost; ``spelling`` is one that is."""

    def __init__(self, message: str, spelling: str | None = None) -> None:
        """Say why, and keep the spelling the grammar takes for the unit, where one exists."""
        super().__init__(message)
        self.spelling = spelling


def require_bounded_spelling(unit: str) -> str:
    """``unit`` as the product the grammar reads it as, if parsing it costs a bounded amount.

    A unit without a bracket is returned as it is written. A bracketed denominator is read as
    the chain of divisions it means: ``1/(rad*s)`` is returned as ``1/rad/s``, which is never
    longer and holds no bracket.

    Raises:
        UnitSpellingError: it is longer than :data:`MAX_LENGTH`, or not a product of named
            units with small integer powers. The message names the spelling the grammar takes
            for it, where one exists.
    """
    if len(unit) > MAX_LENGTH or not UNIT_SPELLING.fullmatch(unit):
        spelling = accepted_spelling(unit, MAX_LENGTH)
        msg = (
            f"the unit {unit[:MAX_LENGTH]!r} is not a product of named units with small "
            "integer powers (for example m, rad/s, kg*m/s**2, 1/(rad*s)); a unit holds no "
            "numbers, a bracket only as one denominator of named units, and at most "
            f"{MAX_LENGTH} characters" + ("" if spelling is None else f"; write it as {spelling}")
        )
        raise UnitSpellingError(msg, spelling)
    return _BRACKETED.sub(lambda found: "/" + "/".join(_FACTOR.findall(found[1])), unit)


def as_product(unit: str) -> str:
    """``unit`` as the product the grammar reads it as; as written, where the grammar refuses it.

    For comparing two writings of a unit by spelling: ``1/(rad*s)`` and ``1/rad/s`` are one.
    """
    try:
        return require_bounded_spelling(unit)
    except UnitSpellingError:
        return unit


def canonical_unit(unit: str) -> str:
    """``unit`` in the one form two spellings of it share; as written, where the grammar refuses it.

    The grammar's own named units, each as written, sorted, with their integer powers summed and
    a zero power dropped (``1`` where none is left): ``1/(rad*s)``, ``1/rad/s``, ``rad**-1*s**-1``
    and ``s**-1/rad`` are all ``rad**-1*s**-1``. Never the registry's root units, which reduce
    ``Hz`` to ``1/s`` and drop the radian and the count: ``rad/s`` and ``Hz`` stay two units here,
    as do ``m`` and ``mm`` and ``N*m`` and ``J``. For comparing two writings of a unit; whether two
    units are of one kind is the registry's question.
    """
    try:
        require_bounded_spelling(unit)
    except UnitSpellingError:
        return unit
    tokens = [found.group(1) for found in _SPELLING_TOKEN.finditer(unit.rstrip(" "))]
    powers, _ = _spelling_product(tokens, 0)
    factors = [n if powers[n] == 1 else f"{n}**{powers[n]}" for n in sorted(powers)]
    return "*".join(factors) or "1"


# The spelling a refused unit has in this grammar. The series writer carries this block, from
# here to the end of this module, byte for byte (a test holds it): it runs alone in a role's
# interpreter (Python 3.9 and the standard library) and names the same spelling when it refuses.
_SPELLING_TOKEN = re.compile(r"[ ]*([A-Za-z_\u00b5\u03bc\u03a9]+|[0-9]+|\*\*|[-^*/()])")


def accepted_spelling(unit: str, longest: int) -> str | None:
    """The spelling the unit grammar takes for ``unit``, read as the registry reads it, or None.

    The unit is read with brackets nested, a power on a bracket and a quotient in one: named
    units (the grammar's letters), the number 1, ``*``, ``/``, and a power ``**`` or ``^`` of a
    whole number, with the registry's precedence. Anything else (another number, a fraction, a
    power of a power, a letter the grammar does not take) has no spelling. The spelling is a
    product of the units named, each once, in the order they first appear: those with a
    positive power first, joined by ``*`` (``1`` where there is none), then each with a negative
    power after a ``/``. None where a power is over 99 or the spelling over ``longest``.
    """
    if len(unit) > 2 * longest:
        return None
    tokens: list[str] = []
    at, end = 0, len(unit.rstrip(" "))
    while at < end:
        found = _SPELLING_TOKEN.match(unit, at)
        if found is None:
            return None
        tokens.append(found.group(1))
        at = found.end()
    try:
        powers, at = _spelling_product(tokens, 0)
    except ValueError:
        return None
    if at != len(tokens) or any(abs(power) > 99 for power in powers.values()):
        return None
    above = [n if p == 1 else f"{n}**{p}" for n, p in powers.items() if p > 0]
    below = [n if p == -1 else f"{n}**{-p}" for n, p in powers.items() if p < 0]
    spelling = "*".join(above) or "1"
    for factor in below:
        spelling += "/" + factor
    return spelling if len(spelling) <= longest else None


def _spelling_product(tokens: list[str], at: int) -> tuple[dict[str, int], int]:
    """Terms joined by ``*`` and ``/`` from ``tokens[at]``: their powers, and where they end."""
    powers, at = _spelling_term(tokens, at)
    while at < len(tokens) and tokens[at] in ("*", "/"):
        sign = 1 if tokens[at] == "*" else -1
        more, at = _spelling_term(tokens, at + 1)
        for name, power in more.items():
            powers[name] = powers.get(name, 0) + sign * power
    return {name: power for name, power in powers.items() if power != 0}, at


def _spelling_term(tokens: list[str], at: int) -> tuple[dict[str, int], int]:
    """A named unit, 1 or a bracket, with its power, from ``tokens[at]``.

    Raises:
        ValueError: the tokens hold no such term there.
    """
    if at >= len(tokens):
        raise ValueError(at)
    token = tokens[at]
    if token == "(":
        powers, at = _spelling_product(tokens, at + 1)
        if at >= len(tokens) or tokens[at] != ")":
            raise ValueError(at)
        at += 1
    elif token == "1":
        powers, at = {}, at + 1
    elif token[0] not in "0123456789-^*/()":
        powers, at = {token: 1}, at + 1
    else:
        raise ValueError(at)
    if at < len(tokens) and tokens[at] in ("**", "^"):
        sign = -1 if at + 1 < len(tokens) and tokens[at + 1] == "-" else 1
        at += 2 if sign == -1 else 1
        if at >= len(tokens) or not tokens[at].isdigit() or len(tokens[at]) > 2:
            raise ValueError(at)
        exponent = sign * int(tokens[at])
        powers, at = {name: power * exponent for name, power in powers.items()}, at + 1
    return powers, at
