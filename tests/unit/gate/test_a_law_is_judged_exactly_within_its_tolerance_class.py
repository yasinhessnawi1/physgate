"""A law is evaluated exactly, and misses only by what its tolerance class allows.

Every input is measured against its kind and evaluated in exact fractions. An equality of the
``rounding`` class may miss by the rounding its terms carry, each term's bound propagated
through its products and quotients (each member of a sum its own term); a ``model`` law by its
sourced share of the right side's magnitude; an inequality by nothing. A failing record carries
everything a reader needs to see why: the law, its source and state, the instance spelled over
nodes, every input as declared and as evaluated with the quantity's own source and writer, both
sides, the residual, the allowance, the table's digest and the law's count.

The evaluator is the gate's own exact walk over the law's sums of monomials. It is held equal to
sympy's exact evaluation of the same expression, so the walk adds nothing sympy would not.
"""

from __future__ import annotations

import random
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
import sympy
from gate_fixtures import graph, node
from law_cases import (
    gate,
    joule_heating,
    laws_records,
    of_law,
    one,
    output_within_rating,
    reaction_sum,
    stall_by_resistance,
    table,
    within_rating,
)
from law_fixtures import cleared, laws_module, sound_law

from physgate.gate.graph import GraphView
from physgate.gate.tolerances import propagated_bound
from physgate.orchestrator.protocols import (
    CheckRecord,
    LawDetails,
    LawInput,
    NumericOutput,
    QuantityRef,
)

E = Fraction(1, 200)


def view_of(tmp_path: Path, *payloads: dict[str, Any]) -> GraphView:
    graph(tmp_path / "g", *payloads)
    return GraphView.read(tmp_path / "g", base_revision=0)


def outcome(laws: Any, view: GraphView, law_id: str) -> str:
    records = [r for r in of_law(laws_records(laws, view), law_id) if r.outcome != "pass"]
    if not records:
        return "pass" if of_law(laws_records(laws, view), law_id) else "absent"
    record = one(records)
    return "fail" if record.outcome == "warn" else record.outcome


def failing(laws: Any, view: GraphView, law_id: str) -> tuple[CheckRecord, LawDetails]:
    record = one([r for r in of_law(laws_records(laws, view), law_id) if r.outcome == "warn"])
    assert isinstance(record.details, LawDetails)
    return record, record.details


def exact(output: NumericOutput | None) -> Fraction:
    assert output is not None
    return (
        Fraction(repr(output.value)) if isinstance(output.value, float) else Fraction(output.value)
    )


def imu(power_mw: Fraction | float) -> dict[str, Any]:
    return node(
        "electrical.imu",
        quantities={
            "power_draw": (float(power_mw), "mW"),
            "supply_voltage": (3.3, "V"),
            "current_draw": (3.9, "mA"),
        },
    )


# --- rounding ------------------------------------------------------------------------------

#: 3.3 V times 3.9 mA, in watts, and the most that product and a declared power may miss by.
PRODUCT = Fraction("3.3") * Fraction("0.0039")


def allowed(power_w: Fraction) -> Fraction:
    return E * power_w + PRODUCT * ((1 + E) ** 2 - 1)


def test_a_rounding_law_holds_up_to_its_propagated_allowance_and_not_past_it(
    tmp_path: Path,
) -> None:
    laws = table(tmp_path / "t", [sound_law()])
    # Declared power just inside and just outside the allowance above the product.
    inside = Fraction("0.013063")  # W; the product is 0.01287 W
    assert inside - PRODUCT <= allowed(inside)
    outside = Fraction("0.013070")
    assert outside - PRODUCT > allowed(outside)
    assert outcome(laws, view_of(tmp_path / "a", imu(inside * 1000)), "electrical_power") == "pass"
    assert outcome(laws, view_of(tmp_path / "b", imu(outside * 1000)), "electrical_power") == "fail"


def test_a_failing_record_carries_every_field_of_the_law_and_the_instance(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [sound_law()])
    record, details = failing(laws, view_of(tmp_path, imu(19.5)), "electrical_power")
    assert details.law_id == "electrical_power"
    assert details.statement == sound_law()["statement"]
    assert "Fundamentals of Electric Circuits" in details.source and "1.5" in details.source
    assert details.law_status == "warn"
    assert details.expression == (
        "power_draw(electrical.imu) == "
        "supply_voltage(electrical.imu) * current_draw(electrical.imu)"
    )
    assert details.comparator == "==" and details.tolerance == "rounding"
    assert details.laws_sha256 == laws.sha256
    assert details.evaluated == 1
    assert (exact(details.left), details.left.unit) == (Fraction("0.0195"), "W")
    assert (exact(details.right), details.right.unit) == (PRODUCT, "W")
    assert exact(details.residual) == Fraction("0.0195") - PRODUCT
    assert exact(details.allowance) == allowed(Fraction("0.0195"))
    assert record.value is not None and exact(record.value) == exact(details.residual)
    by_name = {i.name: i for i in details.inputs}
    assert set(by_name) == {"power_draw", "supply_voltage", "current_draw"}
    current = by_name["current_draw"]
    assert current == LawInput(
        node_id="electrical.imu",
        name="current_draw",
        declared=NumericOutput(value=3.9, unit="mA"),
        canonical=NumericOutput(value=0.0039, unit="A"),
        source="datasheet",
        written_by="electrical",
    )
    assert "electrical_power" in record.message and details.statement in record.message


def test_a_blocking_failure_hands_the_verdict_the_law_s_anchor_input_first(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [sound_law(status="block", cleared=cleared())])
    result = gate(laws).run(view_of(tmp_path, imu(19.5)), ["system"], "on")
    assert result.verdict == "fail" and result.failing_check == "laws"
    assert result.quantities[0] == QuantityRef(
        node_id="electrical.imu", name="power_draw", value=19.5, unit="mW"
    )
    assert {q.name for q in result.quantities} == {"power_draw", "supply_voltage", "current_draw"}


def test_a_power_counts_each_factor_of_its_base_in_the_bound(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [joule_heating()])
    winding = node(
        "electrical.motor",
        quantities={
            "heat_dissipation": (5, "W"),
            "current_draw": (2, "A"),
            "motor_resistance": (1, "ohm"),
        },
    )
    _, details = failing(laws, view_of(tmp_path, winding), "joule_heating")
    assert exact(details.allowance) == propagated_bound(Fraction(5), 1, 0) + propagated_bound(
        Fraction(4), 3, 0
    )


def test_each_member_of_a_sum_is_its_own_term_for_the_bound(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [reaction_sum()])
    view = view_of(
        tmp_path,
        node(
            "mechanical.chassis",
            kind="module",
            domain="mechanical",
            quantities={"reaction_moment": (4, "N*m")},
        ),
        *(
            node(
                f"mechanical.{name}",
                domain="mechanical",
                quantities={"reaction_moment": (moment, "N*m")},
                constrains=["mechanical.chassis"],
            )
            for name, moment in (("left", -1), ("right", 2))
        ),
    )
    _, details = failing(laws, view, "reaction_moment_sum")
    # |4| + |-1| + |2|, each at one share: the members are not netted before the bound.
    assert exact(details.allowance) == E * 7
    assert exact(details.right) == 1
    assert details.expression == (
        "reaction_moment(mechanical.chassis) == "
        "reaction_moment(mechanical.left) + reaction_moment(mechanical.right)"
    )


# --- inequality ----------------------------------------------------------------------------


def rated(draw: float, limit: float) -> dict[str, Any]:
    return node(
        "electrical.imu", quantities={"current_draw": (draw, "A"), "current_limit": (limit, "A")}
    )


def test_an_inequality_gets_no_allowance_at_all(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [within_rating()])
    assert outcome(laws, view_of(tmp_path / "a", rated(2, 2)), "within_rating") == "pass"
    assert outcome(laws, view_of(tmp_path / "b", rated(2.000001, 2)), "within_rating") == "fail"
    _, details = failing(laws, view_of(tmp_path / "c", rated(2.5, 2)), "within_rating")
    assert details.allowance is None and details.comparator == "<="
    assert exact(details.residual) == Fraction("0.5")


def test_a_greater_or_equal_law_is_read_the_right_way_round(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [output_within_rating()])

    def stage(rated_w: float, out_w: float) -> dict[str, Any]:
        return node(
            "electrical.regulator",
            quantities={"rated_output_power": (rated_w, "W"), "output_power": (out_w, "W")},
        )

    assert outcome(laws, view_of(tmp_path / "a", stage(10, 10)), "output_within_rating") == "pass"
    assert outcome(laws, view_of(tmp_path / "b", stage(10, 8)), "output_within_rating") == "pass"
    assert outcome(laws, view_of(tmp_path / "c", stage(8, 10)), "output_within_rating") == "fail"


# --- model ---------------------------------------------------------------------------------


def motor(stall_a: float) -> dict[str, Any]:
    return node(
        "electrical.motor",
        quantities={
            "stall_current": (stall_a, "A"),
            "rated_voltage": (12, "V"),
            "motor_resistance": (6, "ohm"),
        },
    )


def test_a_model_law_misses_by_its_share_of_the_right_side_and_no_more(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [stall_by_resistance()])
    # 12 V over 6 ohm is 2 A; a tenth of that is 0.2 A either way.
    assert outcome(laws, view_of(tmp_path / "a", motor(2.2)), "stall_by_resistance") == "pass"
    assert outcome(laws, view_of(tmp_path / "b", motor(1.8)), "stall_by_resistance") == "pass"
    assert outcome(laws, view_of(tmp_path / "c", motor(2.2001)), "stall_by_resistance") == "fail"
    _, details = failing(laws, view_of(tmp_path / "d", motor(3)), "stall_by_resistance")
    assert exact(details.allowance) == Fraction(1, 5) and details.tolerance == "model"


# --- the evaluator against sympy -----------------------------------------------------------


def test_the_evaluator_agrees_with_sympy_s_exact_value_of_the_same_expression() -> None:
    side_value = laws_module().__dict__.get("side_value")
    if side_value is None:
        pytest.fail("the law table module has no evaluator (side_value) yet")
    parse_expression = laws_module().parse_expression
    rng = random.Random("against-sympy")
    names = ("a", "b", "c", "d")
    for _ in range(200):
        terms = []
        for _ in range(rng.randint(1, 3)):
            factors = rng.sample(names, rng.randint(1, 3))
            spelled = " * ".join(f"{f}**{rng.choice((1, 2, -1, 3, -2))}" for f in factors)
            terms.append(f"{rng.randint(1, 5)} * {spelled}")
        text = f"{' + '.join(terms)} == a"
        parsed = parse_expression(text, names)
        values = {n: Fraction(rng.randint(1, 999), rng.choice((1, 10, 100))) for n in names}
        walked = side_value(parsed.left, values)
        symbols = {n: sympy.Symbol(n) for n in names}
        expression = sympy.Integer(0)
        for monomial in parsed.left:
            product = sympy.Rational(
                monomial.coefficient.numerator, monomial.coefficient.denominator
            )
            for name, power in monomial.powers:
                product *= symbols[name] ** power
            expression += product
        exact_value = expression.xreplace(
            {symbols[n]: sympy.Rational(v.numerator, v.denominator) for n, v in values.items()}
        )
        assert walked == Fraction(int(exact_value.p), int(exact_value.q))
