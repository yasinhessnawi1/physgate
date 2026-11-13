"""A law's expression is read by a syntax-tree allowlist and nothing else.

The table is protected, but it is still text that reaches the gate's process, so no row can
carry code: the expression is parsed into a syntax tree and walked against a short list of
what a closed-form law needs, with its length and its size bounded before the parser sees it.
Everything else is refused, naming the row: a call, an attribute, a subscript, a string, a
float, an exponent that is not a small integer, a comparator other than ``==``, ``<=`` and
``>=``, a chain of comparisons, a name the row does not declare, and a literal the row does not
declare with its reason, so that a count of parts can never hide in a coefficient.

Each side must be a sum of monomials, products and quotients of declared symbols with integer
powers and declared literals, because the rounding allowance is proven per monomial; and a
summed member term stands alone, once, to the first power.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from law_fixtures import laws_module, load, refused, sound_law


@pytest.mark.parametrize(
    ("expression", "why"),
    [
        ("abs(P) == V * I", "call"),
        ("P.real == V * I", "attribute"),
        ("P[0] == V * I", "subscript"),
        ("P == 'V' * I", "string"),
        ("P == 0.5 * V * I", "float"),
        ("P == V ** 4 * I", "exponent"),
        ("P == V ** I", "exponent"),
        ("P == V ** 0.5 * I", "exponent"),
        ("P != V * I", "comparator"),
        ("P < V * I", "comparator"),
        ("P <= V * I <= P", "one comparison"),
        ("P", "comparison"),
        ("P == V * I * X", "not declared"),
        ("P == 6 * V * I", "literal"),
        ("P == (V + V) * I", "monomial"),
        ("P == -(V * I - V * I) * I", "monomial"),
        ("P == V // I", "operator"),
        ("P == V % I", "operator"),
        ("(lambda: P)() == V", "call"),
        ("P == V * I and P", "comparison"),
        ("P == [V][0] * I", "subscript"),
        ("P == [V for V in I][0]", "subscript"),
        ("P == sum(V for V in I)", "call"),
        ("P == f'{V}' * I", "not allowed"),
        ("P == {V: I}[V]", "subscript"),
        ("P == (V if P else I) * I", "conditional"),
        ("P == ... * V * I", "literal of type"),
    ],
)
def test_each_refused_form_names_the_row_and_the_form(
    tmp_path: Path, expression: str, why: str
) -> None:
    message = refused(tmp_path, [sound_law(expression=expression)])
    assert "electrical_power" in message and why in message


def test_an_expression_longer_than_the_bound_is_refused_before_it_is_parsed(
    tmp_path: Path,
) -> None:
    module = laws_module()
    long = "P == V * I" + " + 0 * P" * 40
    assert len(long) > module.MAX_EXPRESSION_LENGTH == 256
    assert "long" in refused(tmp_path, [sound_law(expression=long)])


def test_an_expression_of_more_nodes_than_the_bound_is_refused(tmp_path: Path) -> None:
    module = laws_module()
    many = "P == " + " * ".join(["V"] * 40) + " * I"
    assert len(many) <= module.MAX_EXPRESSION_LENGTH
    assert module.MAX_EXPRESSION_NODES == 64
    assert "nodes" in refused(tmp_path, [sound_law(expression=many)])


@pytest.mark.parametrize(
    "expression",
    [
        "P == V * I",
        "P >= V * I",
        "V * I <= P",
        "P == I * V",
        "P - V * I == 0 * P",
        "P * I ** -1 == V",
        "P / I == V",
        "-P == -V * I",
    ],
)
def test_sums_of_monomials_over_declared_symbols_load(tmp_path: Path, expression: str) -> None:
    tolerance = "rounding" if "==" in expression else "inequality"
    literals = [{"value": "0", "reason": "a side that is zero"}] if "0 *" in expression else []
    row = sound_law(expression=expression, tolerance=tolerance, literals=literals)
    if tolerance == "inequality":
        # The worked examples are run at load: an inequality's failing one draws too little.
        failing = {**row["example"][1], "values": {**row["example"][1]["values"]}}
        failing["values"]["P"] = {"value": 10, "unit": "mW"}
        row["example"] = [row["example"][0], failing]
    assert "electrical_power" in load(tmp_path, [row]).laws


def test_a_declared_literal_with_its_reason_loads(tmp_path: Path) -> None:
    row = sound_law(
        expression="2 * P == 2 * V * I",
        literals=[{"value": "2", "reason": "both sides doubled, to test the literal rule"}],
    )
    assert "electrical_power" in load(tmp_path, [row]).laws
    without_reason = sound_law(expression="2 * P == 2 * V * I", literals=[{"value": "2"}])
    assert "reason" in refused(tmp_path / "b", [without_reason])
    float_literal = sound_law(
        expression="2 * P == 2 * V * I", literals=[{"value": "2.0", "reason": "r"}]
    )
    assert "literal" in refused(tmp_path / "c", [float_literal])


def test_a_ratio_literal_is_two_declared_integers(tmp_path: Path) -> None:
    row = sound_law(
        expression="P == 1 / 2 * V * I + 1 / 2 * V * I",
        literals=[
            {"value": "1", "reason": "one half, written as a ratio of integers"},
            {"value": "2", "reason": "one half, written as a ratio of integers"},
        ],
    )
    assert "electrical_power" in load(tmp_path, [row]).laws


@pytest.mark.parametrize(
    ("comparator", "tolerance"),
    [("<=", "rounding"), ("==", "inequality"), (">=", "model")],
)
def test_a_comparator_outside_its_tolerance_class_is_refused(
    tmp_path: Path, comparator: str, tolerance: str
) -> None:
    model = {"share": "1/10", "source": "s"} if tolerance == "model" else None
    row = sound_law(expression=f"P {comparator} V * I", tolerance=tolerance)
    if model is not None:
        row["model"] = model
    assert "tolerance" in refused(tmp_path, [row])
