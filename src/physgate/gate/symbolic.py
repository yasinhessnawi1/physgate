"""The gate's one door to sympy: a balance built as an expression and evaluated exactly.

sympy ships no type information, so it is imported here and nowhere else in the
gate, and a test holds it here; the untyped values it returns never leave this
module. A balance is written as a sum of symbols, one per term, and evaluated by
substituting exact rationals with ``xreplace``, which walks the expression once.
``subs`` is not used: it was measured quadratic, 23 s per pass on a dense graph
where ``xreplace`` took 27 ms.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

import sympy

SYMPY = f"sympy {sympy.__version__}"


def _symbol(label: str, index: int) -> sympy.Symbol:
    safe = "".join(c if c.isalnum() else "_" for c in label)
    return sympy.Symbol(f"t{index}_{safe}")


def residual(
    positive: Sequence[tuple[str, Fraction]], negative: Sequence[tuple[str, Fraction]]
) -> Fraction:
    """``sum(positive) - sum(negative)``, computed by sympy over one symbol per term.

    Each term is ``(label, value)``; the label names the symbol, for a reader of
    the expression, and plays no part in the value.

    Raises:
        ValueError: sympy's answer is not an exact rational, which would mean a
            term was not one.
    """
    terms = [*positive, *negative]
    symbols = [_symbol(label, i) for i, (label, _) in enumerate(terms)]
    split = len(positive)
    expression = sympy.Add(*symbols[:split]) - sympy.Add(*symbols[split:])
    values = {
        symbol: sympy.Rational(value.numerator, value.denominator)
        for symbol, (_, value) in zip(symbols, terms, strict=True)
    }
    result = expression.xreplace(values)
    if not result.is_Rational:
        msg = f"the balance did not evaluate to an exact number: {result}"
        raise ValueError(msg)
    return Fraction(int(result.p), int(result.q))
