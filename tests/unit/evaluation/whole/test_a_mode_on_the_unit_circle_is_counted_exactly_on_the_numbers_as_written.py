"""An eigenvalue at exactly 1 not set aside, or at exactly -1, is counted exactly, not by a float.

The count is made in rational arithmetic on the decimals as written: ``0.9`` and ``0.1`` are
tenths, so two states that each carry ``0.9`` of themselves and ``0.1`` of the other are held at
exactly 1 whatever a float eigenvalue of the closed loop comes out as (the fifth review's pair
fed by the wheel angle came back at ``1 - 2.5e-12``). A mode the set-aside rule sets aside is not
counted; a mode at exactly -1 never is set aside. A pole that is not exactly 1 or -1, however near,
is no count: it is judged in floating point by the loop.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

modes: Any = importlib.import_module(
    "test_a_mode_is_set_aside_only_where_the_wheels_return_and_on_the_numbers_as_written"
)
_term = modes._term
_state = modes._state
HOLD = modes.HOLD


def _circle(
    memory: list[tuple[str, str]],
    lines: list[dict[str, Any]],
    command: list[Any],
    values: dict[str, float],
) -> Any:
    law = modes._law()
    return law.unit_circle(modes._body(memory, lines, command), values, period=0.01)


def _pair(a: float, b: float, *fed: tuple[str, str]) -> tuple[Any, Any]:
    """Two unread states, each ``a`` of itself and ``b`` of the other, fed by ``fed`` terms."""
    memory = [("s0", "s0_now"), ("s1", "s1_now")]
    lines = [
        _state("s0", _term("previous.s0", "a"), _term("previous.s1", "b"), *_feeds(fed, 0)),
        _state("s1", _term("previous.s1", "a"), _term("previous.s0", "b"), *_feeds(fed, 1)),
    ]
    return memory, lines


def _feeds(fed: tuple[tuple[str, str], ...], at: int) -> list[dict[str, Any]]:
    return [_term(of, f"k{at}") for of, _ in fed]


VALUES = {"g": 0.3, "k0": -1.625, "k1": -2.867}


@pytest.mark.parametrize("fed", ["wheel_angle", "wheel_speed"])
def test_the_reviewer_s_pair_at_nine_tenths_and_one_tenth_has_one_eigenvalue_at_exactly_one(
    fed: str,
) -> None:
    memory, lines = _pair(0.9, 0.1, (fed, ""))
    circle = _circle(memory, lines, HOLD, {**VALUES, "a": 0.9, "b": 0.1})
    assert (circle.at_one, circle.at_minus_one) == (1, 0)
    assert circle.unstable
    assert "exactly 1" in circle.reason()


def test_the_pair_fed_by_the_tilt_is_set_aside_and_is_no_count() -> None:
    memory, lines = _pair(0.9, 0.1, ("tilt", ""))
    circle = _circle(memory, lines, HOLD, {**VALUES, "a": 0.9, "b": 0.1})
    assert (circle.at_one, circle.at_minus_one) == (0, 0)
    assert not circle.unstable
    assert circle.reason() == ""


def test_a_pair_at_exactly_minus_one_is_counted_and_never_set_aside() -> None:
    memory, lines = _pair(-0.9, -0.1, ("tilt", ""))
    circle = _circle(memory, lines, HOLD, {**VALUES, "a": -0.9, "b": -0.1})
    assert (circle.at_one, circle.at_minus_one) == (0, 1)
    assert "exactly -1" in circle.reason()
    law = modes._law()
    held = law.held_modes(
        modes._body(memory, lines, HOLD), {**VALUES, "a": -0.9, "b": -0.1}, period=0.01
    )
    assert held == ()


def test_a_state_at_minus_one_that_the_command_reads_is_no_exact_eigenvalue_of_the_loop() -> None:
    """Read by the command it moves the plant: the mode is not a memory vector the plant ignores."""
    memory = [("z", "z_now")]
    lines = [_state("z", _term("previous.z", "m"))]
    command = [*HOLD, _term("previous.z", "c")]
    circle = _circle(memory, lines, command, {"g": 0.3, "m": -1.0, "c": 0.5})
    assert (circle.at_one, circle.at_minus_one) == (0, 0)


def test_a_single_state_at_minus_one_that_nothing_reads_is_counted() -> None:
    memory = [("z", "z_now")]
    lines = [_state("z", _term("previous.z", "m"))]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "m": -1.0})
    assert (circle.at_one, circle.at_minus_one) == (0, 1)


@pytest.mark.parametrize("pole", [-0.999999999, -1.0000000000001, -0.9999999999999, 0.5, -0.5])
def test_a_pole_that_is_not_exactly_minus_one_is_no_count(pole: float) -> None:
    memory = [("z", "z_now")]
    lines = [_state("z", _term("previous.z", "m"))]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "m": pole})
    assert circle.at_minus_one == 0


@pytest.mark.parametrize("pole", [0.999999999, 0.9999999999999, 1.0000000000001, 1.000001])
def test_an_integrator_of_the_wheel_angle_at_a_pole_that_is_not_exactly_one_is_no_count(
    pole: float,
) -> None:
    memory = [("z", "z_now")]
    lines = [_state("z", _term("previous.z", "m"), _term("wheel_angle", "k"))]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "m": pole, "k": 0.4})
    assert (circle.at_one, circle.at_minus_one) == (0, 0)


def test_an_integrator_of_the_wheel_angle_at_exactly_one_is_counted() -> None:
    memory = [("z", "z_now")]
    lines = [_state("z", _term("previous.z", "m"), _term("wheel_angle", "k"))]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "m": 1.0, "k": 0.4})
    assert (circle.at_one, circle.at_minus_one) == (1, 0)


def test_a_law_that_reads_the_wheel_angle_nowhere_has_the_travel_counted_at_one() -> None:
    law = modes._law()
    body = modes._body([], [], [_term("tilt", "g")])
    assert law.unit_circle(body, {"g": 0.3}, period=0.01).at_one == 1
    assert (
        law.unit_circle(
            modes._body([], [], [_term("wheel_angle", "g")]), {"g": 0.3}, period=0.01
        ).at_one
        == 0
    )


def test_the_leak_free_form_s_offset_is_set_aside_and_is_no_count() -> None:
    lines = [_state("a", _term("previous.a", "one"), _term("tilt_rate", "period"))]
    command = [
        _term("previous.u", "one"),
        _term("line.a_now", "kangle"),
        _term("wheel_angle", "g"),
    ]
    memory = [("a", "a_now"), ("u", "command")]
    circle = _circle(memory, lines, command, {"one": 1.0, "kangle": 0.14, "g": 0.17})
    assert (circle.at_one, circle.at_minus_one) == (0, 0)


def test_two_independent_held_vectors_none_set_aside_are_both_counted() -> None:
    memory = [("u", "u_now"), ("v", "v_now")]
    lines = [
        _state("u", _term("previous.u", "one"), _term("wheel_speed", "k")),
        _state("v", _term("previous.v", "one"), _term("wheel_angle", "k")),
    ]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "one": 1.0, "k": 0.4})
    assert circle.at_one == 2


def test_the_count_is_made_on_the_decimals_as_written_not_on_their_binary_forms() -> None:
    """0.9 and 0.1 are tenths: floats sum to 1.0000000000000000 only by luck, tenths exactly."""
    for a, b in ((0.9, 0.1), (0.7, 0.3), (0.6, 0.4), (0.3, 0.7), (0.55, 0.45)):
        memory, lines = _pair(a, b, ("wheel_angle", ""))
        circle = _circle(memory, lines, HOLD, {**VALUES, "a": a, "b": b})
        assert circle.at_one == 1, (a, b)


# ── what a mode set aside is fed by and read by, as the record says it, and the flag ──


def _report(
    memory: list[tuple[str, str]],
    lines: list[dict[str, Any]],
    command: list[Any],
    values: dict[str, float],
) -> tuple[Any, ...]:
    law = modes._law()
    return tuple(law.held_report(modes._body(memory, lines, command), values, period=0.01))


def _flags(held: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(modes._law().held_state_flags(held))


def test_a_term_of_weight_zero_is_no_feeder_of_the_mode_it_sits_in() -> None:
    memory = [("z", "z_now")]
    lines = [_state("z", _term("previous.z", "one"), _term("tilt", "off"))]
    held = _report(memory, lines, HOLD, {"g": 0.3, "one": 1.0, "off": 0.0})
    assert len(held) == 1
    assert held[0].fed_by_signals == ()
    assert _flags(held) == ()


def test_a_mode_fed_by_the_wheel_reference_says_so_in_its_record() -> None:
    memory = [("z", "z_now")]
    lines = [_state("z", _term("previous.z", "one"), _term("wheel_reference", "k"))]
    held = _report(memory, lines, HOLD, {"g": 0.3, "one": 1.0, "k": 0.4})
    assert len(held) == 1
    assert held[0].fed_by_signals == ("wheel_reference",)
    assert held[0].as_record()["fed_by_the_reference"] is True
    plain = _report(
        memory,
        [_state("z", _term("previous.z", "one"), _term("tilt", "k"))],
        HOLD,
        {"g": 0.3, "one": 1.0, "k": 0.4},
    )
    assert plain[0].as_record()["fed_by_the_reference"] is False


def test_a_held_state_is_flagged_only_when_a_signal_feeds_it_and_the_command_reads_it() -> None:
    values = {"g": 0.3, "one": 1.0, "k": 0.4, "c": 0.5}
    memory = [("z", "z_now")]
    # fed by the tilt, read by nothing: no flag
    fed = _report(
        memory, [_state("z", _term("previous.z", "one"), _term("tilt", "k"))], HOLD, values
    )
    assert len(fed) == 1
    assert (fed[0].fed_by_signals, fed[0].read_by_command) == (("tilt",), False)
    assert _flags(fed) == ()
    # read by the command, fed by nothing (it carries itself): no flag
    read_command = [*HOLD, _term("previous.z", "c")]
    read = _report(memory, [_state("z", _term("previous.z", "one"))], read_command, values)
    assert len(read) == 1
    assert (read[0].fed_by_signals, read[0].read_by_command) == ((), True)
    assert _flags(read) == ()
    # both: flagged
    both = _report(
        memory, [_state("z", _term("previous.z", "one"), _term("tilt", "k"))], read_command, values
    )
    assert len(both) == 1
    assert (both[0].fed_by_signals, both[0].read_by_command) == (("tilt",), True)
    assert _flags(both) == (modes._law().HELD_STATE_FLAG,)


def _with_two_numbers(second: str) -> bytes:
    """A state that carries itself by two numbers written as text: ``0.9`` and ``second``."""
    raw: bytes = modes._bytes(
        '{"structure": "sampled_law", "period": {"value": 0.01, "unit": "s"}, '
        '"command_limit": {"value": 0.75, "unit": "1"}, '
        '"sensor_delay": {"value": 0.0048, "unit": "s"}, '
        '"compute_delay": {"value": 0.004, "unit": "s"}, '
        '"coefficients": {"g": {"value": 0.3, "unit": "1/rad"}}, '
        '"memory": [{"name": "z", "unit": "1", "next": "z_now"}], '
        '"lines": [{"name": "z_now", "unit": "1", "terms": ['
        '{"sign": 1, "number": 0.9, "of": "previous.z"}, '
        f'{{"sign": 1, "number": {second}, "of": "previous.z"}}]}}, '
        '{"name": "command", "unit": "1", "terms": ['
        '{"sign": 1, "coefficients": ["g"], "of": "wheel_angle"}]}], "command": "command"}'
    )
    return raw


def test_a_term_s_number_is_decided_on_as_the_text_wrote_it() -> None:
    answer_module = importlib.import_module("physgate.evaluation.whole.answer")
    law = modes._law()
    held = {}
    for second in ("0.1", "0.10000000000000001"):
        answer = answer_module.parse_answer(_with_two_numbers(second))
        controller = answer.controller
        values = {n: float(m.value) for n, m in controller.coefficients.items()}
        held[second] = law.held_modes(controller, values, period=0.01, written=controller.written)
    assert held["0.1"], "0.9 and 0.1 are tenths: held"
    assert held["0.10000000000000001"] == (), "as written the two do not sum to 1"
