"""The rounding allowance on equalities: relative, three significant figures, exact."""

from __future__ import annotations

from fractions import Fraction

from physgate.gate.tolerances import ROUNDING_SHARE, holds_within_rounding, rounding_allowance

# A 1 kg load at 0.1 m on a cantilever: its moment about the support, exactly.
LOAD_MOMENT = Fraction("9.80665") * Fraction("0.1")


def test_a_cantilever_declaring_no_moment_reaction_misses_by_far_more_than_rounding() -> None:
    # Declared reaction moment 0; the load's moment is 0.980665 N*m.
    terms = [Fraction(0), LOAD_MOMENT]
    residual = Fraction(0) - LOAD_MOMENT
    assert abs(residual) > Fraction("0.98")
    assert rounding_allowance(terms) < Fraction("0.0050")
    assert not holds_within_rounding(residual, terms)


def test_a_moment_reaction_declared_to_three_figures_is_accepted() -> None:
    declared = Fraction("0.981")
    terms = [declared, LOAD_MOMENT]
    assert holds_within_rounding(declared - LOAD_MOMENT, terms)


def test_the_allowance_is_half_a_unit_in_the_third_figure_of_the_terms() -> None:
    assert Fraction(1, 200) == ROUNDING_SHARE
    assert rounding_allowance([Fraction(100), Fraction(-100)]) == Fraction(1)


def test_the_allowance_does_not_grow_with_the_unit_chosen() -> None:
    # The same moment written in kN*m and in N*m buys the same relative slack.
    in_newton_metres = rounding_allowance([LOAD_MOMENT])
    in_kilonewton_metres = rounding_allowance([LOAD_MOMENT / 1000]) * 1000
    assert in_newton_metres == in_kilonewton_metres


def test_a_residual_one_step_past_the_allowance_is_refused() -> None:
    terms = [Fraction(10), Fraction(10)]
    edge = rounding_allowance(terms)
    assert holds_within_rounding(edge, terms)
    assert not holds_within_rounding(edge + Fraction(1, 10**9), terms)
