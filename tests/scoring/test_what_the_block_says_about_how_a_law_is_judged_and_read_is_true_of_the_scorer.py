"""What the answer-form block says about how a law is judged and how its signals read is true.

Each sentence of the block that is more than the shape of an answer is held to the scorer here,
on the frozen plant, with an assertion that needs no tolerance:

- a memory state that adds up the wheel angle, the wheel speed or the command and that the
  command does not read is unstable; one the command reads is judged on its loop (a read
  integrator on the wheel angle with a small gain is not refused, and is stable at the nominal
  plant: its margin is a number);
- a state that keeps its value exactly is flagged and allowed; a leak a rounding error short of 1
  is judged unstable, and one a thousandth of a part in a million short of it is judged on its loop;
- the signs and the readings: a positive command accelerates the wheel angle and the wheel speed
  forward and the tilt backward, at every corner; the wheel angle is the travel less ``r`` times
  the tilt over ``r``; the tilt is read as the plant's own state; the wheel reference is zero in
  the judged loop and advances in the run at the commanded speed; reading it changes no verdict
  of the margins;
- the update rate and the period are two statements: the loop is analysed at the period alone;
- the four rules the block states and the scorer does not refuse are read as valid records, and a
  coefficient named as a state is valid.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit/evaluation/whole"))

from answer_form_cases import accepted_gaps, allowed, example  # noqa: E402
from test_a_whole_design_is_judged_never_on_an_unsourced_value import (  # noqa: E402
    COMPUTED_SPECS,
    STATIC_SPECS,
    _scenario_module,
    _task,
)

from physgate.evaluation.whole import dynamic as dynamic_module  # noqa: E402
from physgate.evaluation.whole import form  # noqa: E402
from physgate.evaluation.whole import law as law_module  # noqa: E402
from physgate.evaluation.whole import loop as loop_module  # noqa: E402
from physgate.evaluation.whole.plant import corners, nominal, parse_plant  # noqa: E402

_PLANT = Path(__file__).resolve().parents[2] / "src/physgate/evaluation/whole/plant_v0.json"
_MARGIN = [STATIC_SPECS[0], COMPUTED_SPECS[1]]
_RADIUS = 0.04
_GAINS = (1.6643, 0.191, 0.2853 * _RADIUS, 1.3421 * _RADIUS)


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _judge(tmp_path: Path, doc: dict[str, Any], specs: list[dict[str, Any]] = _MARGIN) -> Any:
    root = Path(os.path.realpath(tmp_path)) / "answers"
    root.mkdir()
    path = root / form.ANSWER_FILE
    path.write_bytes(json.dumps(doc).encode())
    scorer = _scenario_module().WholeDesignScenario(_task(specs), _PLANT.read_bytes(), root=root)
    return scorer.record(path)


def _row(record: dict[str, Any], name: str = "pm") -> dict[str, Any]:
    row: dict[str, Any] = next(r for r in record["specs"] if r["name"] == name)
    return row


def _law(
    coefficients: dict[str, Any] | None = None,
    memory: list[dict[str, Any]] | None = None,
    lines: list[dict[str, Any]] | None = None,
    terms: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The example's settings with a state feedback on the tilt, its rate and the wheels."""
    doc = copy.deepcopy(example())
    controller = doc["controller"]
    controller["coefficients"] = {
        "k_tilt": _m(_GAINS[0], "1/rad"),
        "k_rate": _m(_GAINS[1], "s/rad"),
        "k_wheel": _m(_GAINS[2], "1/rad"),
        "k_speed": _m(_GAINS[3], "s/rad"),
        **(coefficients or {}),
    }
    controller["memory"] = memory or []
    controller["lines"] = [
        *(lines or []),
        {
            "name": "command",
            "unit": "1",
            "terms": [
                {"sign": 1, "coefficients": ["k_tilt"], "of": "tilt"},
                {"sign": 1, "coefficients": ["k_rate"], "of": "tilt_rate"},
                {"sign": 1, "coefficients": ["k_wheel"], "of": "wheel_angle"},
                {"sign": 1, "coefficients": ["k_speed"], "of": "wheel_speed"},
                *(terms or []),
            ],
        },
    ]
    controller["command"] = "command"
    return doc


def _sum_of(signal: str, unit: str, leak: float, read: bool) -> dict[str, Any]:
    """A state that adds up ``signal`` each period with ``leak``; read by the command or not."""
    return _law(
        {"leak": _m(leak, "1"), "k_sum": _m(0.001, f"1/({unit})")},
        [{"name": "acc", "unit": unit, "next": "acc_now"}],
        [
            {
                "name": "acc_now",
                "unit": unit,
                "terms": [
                    {"sign": 1, "coefficients": ["leak"], "of": "previous.acc"},
                    {"sign": 1, "coefficients": ["period"], "of": signal},
                ],
            }
        ],
        [{"sign": 1, "coefficients": ["k_sum"], "of": "line.acc_now"}] if read else [],
    )


# ── the memory sentence ─────────────────────────────────────────────────────────────────────────


def test_the_feedback_every_row_here_adds_a_state_to_is_judged_at_the_nominal_plant(
    tmp_path: Path,
) -> None:
    row = _row(_judge(tmp_path, _law()))
    assert row["measured"] is not None, row["reason"]


def _unread_sum(signal: str, unit: str) -> dict[str, Any]:
    """A leak-1 state adding up ``signal`` (read from its line, after the command) nothing reads."""
    doc = _law(
        {"leak": _m(1, "1")},
        [{"name": "acc", "unit": unit, "next": "acc_now"}],
    )
    doc["controller"]["lines"].append(
        {
            "name": "acc_now",
            "unit": unit,
            "terms": [
                {"sign": 1, "coefficients": ["leak"], "of": "previous.acc"},
                {"sign": 1, "coefficients": ["period"], "of": signal},
            ],
        }
    )
    return doc


@pytest.mark.parametrize(
    ("signal", "unit"),
    [("wheel_angle", "rad*s"), ("wheel_speed", "rad"), ("line.command", "s")],
    ids=["the wheel angle", "the wheel speed", "the command"],
)
def test_an_unread_state_that_adds_up_the_wheels_or_the_command_is_unstable(
    tmp_path: Path, signal: str, unit: str
) -> None:
    record = _judge(tmp_path, _unread_sum(signal, unit))
    assert record["answer_valid"] is True, record.get("refusal")
    row = _row(record)
    assert row["verdict"] == "fail" and row["measured"] is None
    assert row["corners"]["unstable"] == row["corners"]["count"]
    assert record["unit_circle"]["at_one_not_set_aside"] >= 1


def test_a_read_integrator_on_the_wheel_angle_is_not_refused_and_is_judged_on_its_loop(
    tmp_path: Path,
) -> None:
    record = _judge(tmp_path, _sum_of("wheel_angle", "rad*s", 1.0, read=True))
    assert record["answer_valid"] is True and "refusal" not in record
    row = _row(record)
    # stable at the nominal plant: a margin exists only for a loop that is
    assert row["measured"] is not None, row["reason"]
    assert row["corners"]["unstable"] < row["corners"]["count"]
    assert record["unit_circle"]["at_one_not_set_aside"] == 0
    assert record["held_state_flags"] == []


# ── the held state ──────────────────────────────────────────────────────────────────────────────


def test_a_read_state_of_the_wheel_angle_with_a_leak_of_exactly_1_is_judged_and_not_reported_apart(
    tmp_path: Path,
) -> None:
    doc = _sum_of("wheel_angle", "rad*s", 1.0, read=True)
    doc["controller"]["coefficients"]["k_sum"] = _m(0.002, "1/(rad*s)")
    record = _judge(tmp_path, doc)
    assert record["answer_valid"] is True and "refusal" not in record
    assert record["held_state_flags"] == []
    assert _row(record)["measured"] is not None


def test_a_state_fed_by_the_tilt_and_not_read_is_not_reported_apart(tmp_path: Path) -> None:
    record = _judge(tmp_path, _unread_sum("tilt", "rad*s"))
    assert record["answer_valid"] is True and record["held_state_flags"] == []


def _held(leak: float) -> dict[str, Any]:
    """A tilt estimate from the rate with ``leak``, read by the command in place of the tilt."""
    doc = _sum_of("tilt_rate", "rad", leak, read=True)
    terms = doc["controller"]["lines"][-1]["terms"]
    terms[:] = [t for t in terms if t["of"] != "tilt"]
    doc["controller"]["coefficients"]["k_sum"] = _m(_GAINS[0], "1/rad")
    return doc


def test_a_state_that_keeps_its_value_exactly_is_allowed_and_the_answer_is_reported_apart(
    tmp_path: Path,
) -> None:
    record = _judge(tmp_path, _held(1.0))
    assert record["answer_valid"] is True and "refusal" not in record
    assert record["held_state_flags"] == [law_module.HELD_STATE_FLAG]
    assert _row(record)["measured"] is not None


def test_a_leak_a_rounding_error_short_of_1_is_judged_unstable(tmp_path: Path) -> None:
    record = _judge(tmp_path, _held(1 - 1e-13))
    row = _row(record)
    assert record["answer_valid"] is True and record["held_state_flags"] == []
    assert row["verdict"] == "fail" and row["measured"] is None
    assert row["corners"]["unstable"] == row["corners"]["count"]


def test_a_leak_a_billionth_short_of_1_is_judged_on_its_loop(tmp_path: Path) -> None:
    record = _judge(tmp_path, _held(1 - 1e-9))
    row = _row(record)
    assert record["answer_valid"] is True and record["held_state_flags"] == []
    assert row["measured"] is not None, row["reason"]
    assert row["corners"]["unstable"] < row["corners"]["count"]


# ── the signs and the readings ──────────────────────────────────────────────────────────────────


def _readings(values: dict[str, float]) -> Any:
    """The law's signals (tilt, its rate, wheel angle, wheel speed) from ``[θ, θ̇, x, v]``."""
    reads = loop_module._law_reads(values["wheel_radius"])  # noqa: SLF001
    return reads @ loop_module.measurement(values)


def _every_plant_point() -> list[dict[str, float]]:
    plant = parse_plant(_PLANT.read_bytes())
    return [nominal(plant), *corners(plant, tuple(nominal(plant)))]


def test_a_positive_command_drives_the_wheels_forward_and_the_body_back_at_every_plant_point() -> (
    None
):
    points = _every_plant_point()
    assert len(points) > 1000
    for values in points:
        _, b = loop_module.continuous(values)
        pushed = _readings(values) @ b  # the signals' acceleration under a unit command
        assert pushed[3, 0] > 0, "the wheel speed rises under a positive command"
        assert pushed[1, 0] < 0, "the tilt rate falls: the body leans back as the wheels go forward"


def test_the_wheel_angle_is_the_travel_less_r_times_the_tilt_over_r_at_every_plant_point() -> None:
    for values in _every_plant_point():
        r = values["wheel_radius"]
        read = _readings(values)
        assert np.allclose(read[2], [-1.0, 0.0, 1.0 / r, 0.0], rtol=0, atol=1e-12)
        assert np.allclose(read[3], [0.0, -1.0, 0.0, 1.0 / r], rtol=0, atol=1e-12)


def test_the_tilt_and_its_rate_are_read_as_the_plant_s_own_states() -> None:
    for values in _every_plant_point()[:8]:
        read = _readings(values)
        assert list(read[0]) == [1.0, 0.0, 0.0, 0.0]
        assert list(read[1]) == [0.0, 1.0, 0.0, 0.0]


def test_the_wheel_reference_is_not_among_the_signals_of_the_judged_loop() -> None:
    assert "wheel_reference" in law_module.SIGNALS
    assert "wheel_reference" not in law_module.LOOP_SIGNALS
    assert set(law_module.LOOP_SIGNALS) == set(law_module.SIGNALS) - {"wheel_reference"}


def test_the_wheel_reference_advances_at_the_commanded_speed_in_the_run() -> None:
    assert dynamic_module.reference_position(0.0) == 0.0
    late = (
        dynamic_module.REST_TIME
        + 10 * dynamic_module.DEMAND_SPEED / dynamic_module.RAMP_ACCELERATION
    )
    step = dynamic_module.reference_position(late + 1.0) - dynamic_module.reference_position(late)
    assert step == pytest.approx(dynamic_module.DEMAND_SPEED, rel=1e-12)


def test_a_law_that_reads_the_wheel_reference_has_the_same_margins(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    (tmp_path / "reads").mkdir()
    plain = _judge(tmp_path / "plain", _law())
    reading = _judge(
        tmp_path / "reads",
        _law(
            {"k_ref": _m(0.5, "1/rad")},
            terms=[{"sign": -1, "coefficients": ["k_ref"], "of": "wheel_reference"}],
        ),
    )
    assert reading["answer_valid"] is True
    assert _row(reading)["measured"] == _row(plain)["measured"]
    assert _row(reading)["corners"] == _row(plain)["corners"]


# ── the update rate and the period ──────────────────────────────────────────────────────────────


def test_the_update_rate_and_the_period_are_two_statements_and_the_loop_is_at_the_period(
    tmp_path: Path,
) -> None:
    rows = [STATIC_SPECS[1], STATIC_SPECS[2], COMPUTED_SPECS[1]]
    first, second = _law(), _law()
    first["parameters"]["update_rate"] = _m(50, "Hz")
    second["parameters"]["update_rate"] = _m(200, "Hz")
    for doc in (first, second):
        doc["controller"]["period"] = _m(0.01, "s")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    one, two = _judge(tmp_path / "a", first, rows), _judge(tmp_path / "b", second, rows)
    assert one["answer_valid"] is True and two["answer_valid"] is True
    assert _row(one, "rate")["measured"]["value"] == 50
    assert _row(two, "rate")["measured"]["value"] == 200
    assert _row(one, "period")["measured"]["value"] == pytest.approx(100.0)
    assert _row(two, "period")["measured"]["value"] == pytest.approx(100.0)
    assert _row(one)["measured"] == _row(two)["measured"]
    assert _row(one)["corners"] == _row(two)["corners"]


# ── what the scorer reads and the block does not call refused ─────────────────────────────────


@pytest.mark.parametrize("case", [*accepted_gaps(), *allowed()], ids=lambda c: c.label)
def test_a_rule_stated_and_not_refused_by_the_scorer_gives_a_valid_record(
    tmp_path: Path, case: Any
) -> None:
    root = Path(os.path.realpath(tmp_path)) / "answers"
    root.mkdir()
    path = root / form.ANSWER_FILE
    path.write_bytes(case.data)
    scorer = _scenario_module().WholeDesignScenario(_task(_MARGIN), _PLANT.read_bytes(), root=root)
    record = scorer.record(path)
    assert record["answer_valid"] is True and "refusal" not in record, record
