"""Each number "as written" belongs to one term of the validated body, found by identity.

The text of an answer is read twice: into floats, from which the law is validated and its matrices
built, and into decimals, which a mode held at 1 is decided on. Nothing is taken out of a law, so
every term of the text is a term of the validated body: the numbers are keyed by the line's name
and the term's own place in the line, and each term of the body is given the number of its own
place. The scorer will not proceed if the numbers and the body do not correspond one to one.
"""

from __future__ import annotations

import importlib
import json
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError

_LAW = "physgate.evaluation.whole.law"
_ANSWER = "physgate.evaluation.whole.answer"
_CONVERT = "physgate.evaluation.whole.convert"


def _law() -> Any:
    return importlib.import_module(_LAW)


def _answer() -> Any:
    return importlib.import_module(_ANSWER)


SETTINGS: dict[str, Any] = {
    "update_rate": {"value": 100, "unit": "Hz"},
    "output_data_rate": {"value": 208, "unit": "Hz"},
    "gyro_full_scale": {"value": 1000, "unit": "deg/s"},
    "pwm_frequency": {"value": 20000, "unit": "Hz"},
    "pwm_full_scale": {"value": 400, "unit": "count"},
    "encoder_counts_per_wheel_revolution": {"value": 1322.9, "unit": "count"},
}


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _text(tiny: str = "0.0", kv: str = "1.0", period: str = "0.01", number: str = "1") -> bytes:
    """A law whose state integrates half the wheel speed, a term of ``tiny`` weight before them.

    ``tiny`` is the coefficient of that term (on the tilt), ``number`` the number of the first
    wheel-speed term; each is written as given, as text.
    """
    return (
        '{"form": "whole_run", "version": 3, "parameters": '
        + json.dumps(SETTINGS)
        + ', "controller": {"structure": "sampled_law", '
        f'"period": {{"value": {period}, "unit": "s"}}, '
        '"command_limit": {"value": 0.75, "unit": "1"}, '
        '"sensor_delay": {"value": 0.0048, "unit": "s"}, '
        '"compute_delay": {"value": 0.004, "unit": "s"}, '
        '"coefficients": {"kz": {"value": 0.002, "unit": "1"}, '
        '"g": {"value": 0.3, "unit": "1/rad"}, '
        f'"kv": {{"value": {kv}, "unit": "s/rad"}}, '
        f'"tiny": {{"value": {tiny}, "unit": "1/rad"}}}}, '
        '"memory": [{"name": "z", "unit": "1", "next": "z_now"}], '
        '"lines": [{"name": "z_now", "unit": "1", "terms": ['
        '{"sign": 1, "of": "previous.z"}, '
        '{"sign": 1, "number": 1, "coefficients": ["tiny"], "of": "tilt"}, '
        f'{{"sign": 1, "number": {number}, "coefficients": ["kv"], "of": "wheel_speed"}}, '
        '{"sign": -1, "number": 0.5, "coefficients": ["kv"], "of": "wheel_speed"}]}, '
        '{"name": "command", "unit": "1", "terms": ['
        '{"sign": 1, "coefficients": ["g"], "of": "wheel_angle"}, '
        '{"sign": 1, "coefficients": ["kz"], "of": "previous.z"}]}], '
        '"command": "command"}}'
    ).encode()


def _refused(raw: bytes) -> str:
    try:
        _answer().parse_answer(raw)
    except TaskFormatError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - what escaped is the finding
        pytest.fail(f"{type(exc).__name__} escaped: {exc}")
    pytest.fail("the answer was read")


# ── a number that is not the same number in both passes is refused by name ─────────────────────


@pytest.mark.parametrize(
    ("spelling", "place"),
    [
        ({"tiny": "1e-400"}, "the coefficient of a term"),
        ({"kv": "1e-400"}, "another coefficient"),
        ({"number": "1e-400"}, "a term's number"),
        ({"period": "1e-400"}, "the period"),
        ({"tiny": "1E-999"}, "an exponent past any float"),
        ({"tiny": "0.000000000000000000000000000000000000000000000000000001e-340"}, "long digits"),
    ],
)
def test_a_number_that_is_zero_as_a_float_and_not_as_a_decimal_is_refused_by_name(
    spelling: dict[str, str], place: str
) -> None:
    reason = _refused(_text(**spelling))
    assert "number_underflows" in reason, (place, reason)


@pytest.mark.parametrize(
    "spelling",
    [{"tiny": "1e999"}, {"kv": "-1e999"}, {"number": "1e400"}, {"period": "1e400"}],
)
def test_a_number_that_is_infinite_as_a_float_is_refused_by_name(spelling: dict[str, str]) -> None:
    assert "number_overflows" in _refused(_text(**spelling))


@pytest.mark.parametrize(
    "spelling",
    [{"tiny": "1E-999999999999999999999"}, {"kv": "1e999999999999999999999"}],
    ids=["underflow", "overflow"],
)
def test_a_number_with_an_exponent_no_decimal_holds_is_refused_by_name(
    spelling: dict[str, str],
) -> None:
    assert "number_unreadable_as_written" in _refused(_text(**spelling))


def test_such_an_exponent_where_no_law_is_read_is_no_ground_to_refuse() -> None:
    raw = _text().replace(b'"structure": "sampled_law"', b'"structure": "state_feedback"')
    # not a sampled law any more: the answer fails on its own names, not on a number as written
    assert "number_unreadable_as_written" not in _refused(
        raw.replace(b'"tiny": {"value": 0.0', b'"tiny": {"value": 0e99999999999999999999')
    )


def test_a_not_a_number_is_refused_under_a_name_that_says_so() -> None:
    reason = _refused(_text(tiny="NaN"))
    assert "number_is_not_a_number" in reason
    assert "number_overflows" not in reason


@pytest.mark.parametrize("spelling", [{"kv": "Infinity"}, {"kv": "-Infinity"}])
def test_an_infinite_constant_is_refused_as_an_overflow(spelling: dict[str, str]) -> None:
    assert "number_overflows" in _refused(_text(**spelling))


@pytest.mark.parametrize("zero", ["0", "0.0", "-0.0", "0e0", "0E-3", "0.000e+9", "-0e-400"])
def test_every_spelling_of_zero_is_zero_in_both_passes(zero: str) -> None:
    answer = _answer().parse_answer(_text(tiny=zero))
    written = answer.controller.written
    assert written.coefficients["tiny"] == 0
    assert [t.of for t in answer.controller.lines[0].terms] == [
        "previous.z",
        "tilt",
        "wheel_speed",
        "wheel_speed",
    ]


def test_a_number_that_is_small_but_not_zero_as_a_float_is_read_as_written() -> None:
    """Below the least normal float and still not zero: one number in both passes."""
    answer = _answer().parse_answer(_text(kv="1e-310"))
    value = answer.controller.written.coefficients["kv"]
    assert value == Fraction(Decimal("1e-310"))
    assert float(value) == answer.controller.coefficients["kv"].value != 0.0


# ── the numbers are the validated body's own, by line and the term's place in the text ─────────


def test_the_numbers_are_keyed_by_the_line_and_the_terms_own_place_in_the_line() -> None:
    answer = _answer().parse_answer(_text(tiny="0.0", number="0.75"))
    law = answer.controller
    written = law.written
    assert [t.of for t in law.lines[0].terms] == [
        "previous.z",
        "tilt",
        "wheel_speed",
        "wheel_speed",
    ]
    assert set(written.numbers) == {
        ("z_now", 0),
        ("z_now", 1),
        ("z_now", 2),
        ("z_now", 3),
        ("command", 0),
        ("command", 1),
    }
    assert written.number("z_now", 0) == Fraction(1)
    assert written.number("z_now", 2) == Fraction(3, 4)
    assert written.number("z_now", 3) == Fraction(1, 2)
    assert written.number("z_now", 4) is None


def test_a_term_of_zero_weight_stays_in_the_law_with_its_number() -> None:
    law = _answer().parse_answer(_text(tiny="0.0")).controller
    assert ("z_now", 1) in law.written.numbers
    assert len(law.lines[0].terms) == 4


def test_a_zero_weight_term_is_decided_as_the_law_without_it() -> None:
    law = _law()
    with_term = _answer().parse_answer(_text(tiny="0.0")).controller
    without = (
        _answer()
        .parse_answer(
            _text().replace(
                b'{"sign": 1, "number": 1, "coefficients": ["tiny"], "of": "tilt"}, ', b""
            )
        )
        .controller
    )
    values = {n: float(m.value) for n, m in with_term.coefficients.items()}
    for body in (with_term, without):
        assert law.held_modes(body, values, period=0.01, written=body.written) == ()


def test_duplicate_keys_and_two_spellings_of_one_number_agree_in_both_passes() -> None:
    raw = _text().replace(b'"kv": {"value": 1.0,', b'"kv": {"value": 9.5, "value": 1e0,')
    law = _answer().parse_answer(raw).controller
    assert law.coefficients["kv"].value == 1.0
    assert law.written.coefficients["kv"] == 1
    for spelling in ("1", "1.0", "1e0", "10E-1", "0.1e1", "1.00"):
        again = _answer().parse_answer(_text(kv=spelling)).controller
        assert again.written.coefficients["kv"] == 1
        assert again.coefficients["kv"].value == 1.0


# ── the scorer will not proceed with numbers that do not correspond ───────────────────────────


def _mismatched(written: Any) -> Any:
    """The law of ``_text`` given ``written`` as its numbers."""
    law = _answer().parse_answer(_text(tiny="0.0")).controller
    law._written = written  # noqa: SLF001 - constructing the fault the check is for
    return law


def _off_by_one(written: Any) -> Any:
    """What a reading that lost a term would have written: each place of the line one on."""
    return _shifted(
        written,
        numbers={
            (line, at + 1 if line == "z_now" else at): n
            for (line, at), n in written.numbers.items()
        },
    )


def test_numbers_that_belong_to_other_terms_are_refused_by_name_before_anything_is_decided() -> (
    None
):
    law_module = _law()
    law = _answer().parse_answer(_text(tiny="0.0")).controller
    values = {n: float(m.value) for n, m in law.coefficients.items()}
    wrong = _off_by_one(law.written)
    law._written = wrong  # noqa: SLF001
    for decide in (law_module.held_modes, law_module.held_report):
        with pytest.raises(law_module.LawRefused) as caught:
            decide(law, values, period=0.01, written=wrong)
        assert caught.value.code == "written_numbers_do_not_match"


def test_numbers_of_a_term_that_is_not_the_body_s_are_refused_in_the_conversion_too() -> None:
    law_module = _law()
    convert = importlib.import_module(_CONVERT)
    base = _answer().parse_answer(_text(tiny="0.0")).controller
    law = _mismatched(_off_by_one(base.written))
    radius = convert.ScaleFactor("wheel_radius", 0.04, "m", "this test's plant")
    with pytest.raises(law_module.LawRefused) as caught:
        convert.to_si(law, _answer().parse_answer(_text()).parameters, wheel_radius=radius)
    assert caught.value.code == "written_numbers_do_not_match"


def _shifted(written: Any, **change: Any) -> Any:
    law_module = _law()
    return law_module.Written(**{**written.__dict__, **change})


@pytest.mark.parametrize(
    "fault",
    [
        lambda w: _shifted(w, numbers={**w.numbers, ("z_now", 4): Fraction(1)}),
        lambda w: _shifted(w, numbers={**w.numbers, ("stranger", 0): Fraction(1)}),
        lambda w: _shifted(w, numbers={k: v for k, v in w.numbers.items() if k != ("z_now", 3)}),
        lambda w: _shifted(w, numbers={**w.numbers, ("z_now", 2): Fraction(7, 10)}),
        lambda w: _shifted(w, numbers={**w.numbers, ("z_now", 3): Fraction(1)}),
        lambda w: _shifted(w, coefficients={**w.coefficients, "kv": Fraction(2)}),
        lambda w: _shifted(w, coefficients={k: v for k, v in w.coefficients.items() if k != "kv"}),
        lambda w: _shifted(w, coefficients={**w.coefficients, "stranger": Fraction(1)}),
        lambda w: _shifted(w, coefficients={**w.coefficients, "period": Fraction(1, 50)}),
    ],
    ids=[
        "a_number_for_a_place_that_is_no_term",
        "a_number_for_a_line_that_is_not_the_law_s",
        "a_number_missing",
        "a_number_that_is_another_value",
        "the_number_of_the_other_wheel_speed_term",
        "a_coefficient_that_is_another_value",
        "a_coefficient_missing",
        "a_coefficient_not_in_the_law",
        "the_period_is_another_value",
    ],
)
def test_every_way_the_numbers_can_fail_to_match_the_body_is_refused(fault: Any) -> None:
    law_module = _law()
    law = _answer().parse_answer(_text(tiny="0.0")).controller
    values = {n: float(m.value) for n, m in law.coefficients.items()}
    wrong = fault(law.written)
    with pytest.raises(law_module.LawRefused) as caught:
        law_module.held_modes(law, values, period=0.01, written=wrong)
    assert caught.value.code == "written_numbers_do_not_match"


def test_the_numbers_of_the_body_pass_the_check_and_none_given_is_no_fault() -> None:
    law_module = _law()
    for raw in (_text(tiny="0.0"), _text(), _held_text(True), _held_text(False, rest="0.1")):
        law = _answer().parse_answer(raw).controller
        values = {n: float(m.value) for n, m in law.coefficients.items()}
        try:
            law_module.check_written(law, values, 0.01, law.written)
        except law_module.LawRefused as exc:
            pytest.fail(f"the numbers of the very law they were read for were refused: {exc}")
    plain = _answer().parse_answer(_text(tiny="0.0")).controller
    values = {n: float(m.value) for n, m in plain.coefficients.items()}
    assert law_module.held_modes(plain, values, period=0.01) == ()  # none given: the floats


def test_a_rational_is_itself_and_a_float_is_the_decimal_it_prints_as() -> None:
    law = _law()
    try:
        assert law.exact(Fraction(1, 3)) == Fraction(1, 3)
    except ArithmeticError as exc:
        pytest.fail(f"a rational was read as the text of a float: {exc}")
    assert law.exact(0.1) == Fraction(1, 10)
    assert law.exact(Decimal("0.25")) == Fraction(1, 4)
    assert law.exact(-3) == -3


# ── an analysed law is held to the same, and has numbers of its own ──────────────────────────


def _with_analysed(primary: bytes, analysed: bytes) -> bytes:
    """``primary`` with the controller of ``analysed`` added as its analysed controller."""
    head = b'"controller": '
    other = analysed[analysed.index(head) + len(head) : -1]
    return primary.replace(head, b'"analysed_controller": ' + other + b", " + head, 1)


def test_an_analysed_law_with_a_number_that_underflows_is_refused_by_name() -> None:
    assert "number_underflows" in _refused(_with_analysed(_text(), _text(tiny="1e-400")))
    assert "number_overflows" in _refused(_with_analysed(_text(), _text(kv="1e999")))


def test_an_analysed_law_has_the_numbers_it_was_written_with_and_the_primary_its_own() -> None:
    answer = _answer().parse_answer(
        _with_analysed(_held_text(False), _held_text(True, rest="0.10000000000000001"))
    )
    assert answer.controller.written.coefficients["rest"] == Fraction(1, 10)
    assert answer.analysed_controller.written.coefficients["rest"] == Fraction(
        10000000000000001, 10**17
    )
    assert answer.analysed_controller.written.number("z_now", 2) == Fraction(1)
    assert len(answer.analysed_controller.written.numbers) == 5
    assert len(answer.controller.written.numbers) == 4


# ── a held mode is decided on each term's own number, wherever the terms stand in the line ────


def _held_text(dead_first: bool, rest: str = "0.1") -> bytes:
    """A state held at 1 by ``0.9`` and ``rest`` of itself, read by the command."""
    dead = '{"sign": 1, "coefficients": ["off"], "of": "tilt"}, '
    return (
        '{"form": "whole_run", "version": 3, "parameters": '
        + json.dumps(SETTINGS)
        + ', "controller": {"structure": "sampled_law", '
        '"period": {"value": 0.01, "unit": "s"}, '
        '"command_limit": {"value": 0.75, "unit": "1"}, '
        '"sensor_delay": {"value": 0.0048, "unit": "s"}, '
        '"compute_delay": {"value": 0.004, "unit": "s"}, '
        '"coefficients": {"kz": {"value": 0.002, "unit": "1"}, '
        '"g": {"value": 0.3, "unit": "1/rad"}, '
        '"off": {"value": 0.0, "unit": "1/rad"}, '
        '"pole": {"value": 0.9, "unit": "1"}, '
        f'"rest": {{"value": {rest}, "unit": "1"}}}}, '
        '"memory": [{"name": "z", "unit": "1", "next": "z_now"}], '
        '"lines": [{"name": "z_now", "unit": "1", "terms": ['
        + (dead if dead_first else "")
        + '{"sign": 1, "coefficients": ["pole"], "of": "previous.z"}, '
        '{"sign": 1, "coefficients": ["rest"], "of": "previous.z"}]}, '
        '{"name": "command", "unit": "1", "terms": ['
        '{"sign": 1, "coefficients": ["g"], "of": "wheel_angle"}, '
        '{"sign": 1, "coefficients": ["kz"], "of": "previous.z"}]}], '
        '"command": "command"}}'
    ).encode()


def _modes(raw: bytes) -> Any:
    law = _answer().parse_answer(raw).controller
    values = {n: float(m.value) for n, m in law.coefficients.items()}
    return _law().held_modes(law, values, period=0.01, written=law.written)


def test_a_zero_weight_term_before_the_others_does_not_change_which_number_each_has() -> None:
    plain = _modes(_held_text(dead_first=False))
    assert plain != ()
    assert _modes(_held_text(dead_first=True)) == plain


def test_the_17_digit_decimal_of_the_second_term_is_the_second_term_s_wherever_it_stands() -> None:
    for dead_first in (False, True):
        assert _modes(_held_text(dead_first, rest="0.10000000000000001")) == ()
