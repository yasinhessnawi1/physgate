"""A scenario for the AVR simulator is read as data, bounded, and refused whole when it is wrong.

A session writes the scenario that drives a firmware run: how the body tilts, how the wheels
turn, which faults are injected when, where the main program stalls, which functions are
probed. Nothing in it runs. A field the reader does not know is refused rather than ignored, so a
misspelt fault can never pass as a scenario without it, and each refusal names where it is.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from avrsim_node import evaluate

READ = """
const { readScenario } = await import(`${SRC}/scenario.js`);
const text = %s;
try { out({ ok: readScenario(text) }); }
catch (e) { out({ refused: e.message, where: e.where ?? null }); }
"""


def _read(scenario: object) -> dict[str, Any]:
    text = scenario if isinstance(scenario, str) else json.dumps(scenario)
    result = evaluate(READ % json.dumps(text))
    assert isinstance(result, dict)
    return result


def _base(**more: object) -> dict[str, object]:
    return {"avrsim_scenario": 1, "duration_s": 1.0, **more}


def test_the_least_scenario_is_filled_in_with_a_still_board_and_nothing_injected() -> None:
    read = _read(_base())["ok"]
    assert read == {
        "duration_s": 1.0,
        "imu": {"pitch_rad": [[0, 0]], "pitch_rate_rad_s": None, "raw": []},
        "encoders": {"left": [[0, 0]], "right": [[0, 0]]},
        "faults": [],
        "buttons": [],
        "stalls": [],
        "usb_sof": False,
        "battery_v": 7.2,
        "probes": [],
        "markers": [],
        "trace": {"input_edges": False, "max_lines": 2_000_000},
        "bootloader": "a-star",
        "motors_off_hold_s": 0.02,
    }


def test_every_part_a_scenario_can_hold_is_read_as_given() -> None:
    scenario = _base(
        duration_s=2.0,
        imu={
            "pitch_rad": [[0, 0], [1, 0.5]],
            "pitch_rate_rad_s": [[0, 0.5]],
            "raw": [{"t_s": 1.5, "gyro": [1, -2, 3], "accel": [16384, 0, -1]}],
        },
        encoders={"left_rev_s": [[0, 5]], "right_rev_s": [[0, -2.5], [1, 0]]},
        faults=[
            {"kind": "nack", "device": "lsm6ds33", "start_s": 0.1, "end_s": 0.2},
            {"kind": "nack", "device": "lis3mdl", "start_s": 0.1, "end_s": 0.2},
            {"kind": "sda_held", "release": "scl_pulses", "start_s": 0.3, "end_s": 0.4},
            {"kind": "stale", "start_s": 0.15, "end_s": 0.5},
            {
                "kind": "saturated",
                "sensor": "both",
                "axes": ["z", "x"],
                "start_s": 0.6,
                "end_s": 0.7,
            },
        ],
        buttons=[
            {"button": "A", "start_s": 0.1, "end_s": 0.2},
            {"button": "A", "start_s": 0.2, "end_s": 0.3},
        ],
        stalls=[{"start_s": 0.8, "end_s": 0.9, "interrupts": False}],
        usb_sof=True,
        battery_v=6.0,
        probes=[{"symbol": "update", "period_s": 0.01}, {"symbol": "_Z4stepv"}],
        markers=[{"name": "tilt_beyond", "t_s": 1.2}],
        trace={"input_edges": True, "max_lines": 10},
        bootloader="none",
        motors_off_hold_s=0.005,
    )
    read = _read(scenario)["ok"]
    assert read["imu"]["raw"] == [{"t_s": 1.5, "gyro": [1, -2, 3], "accel": [16384, 0, -1]}]
    assert read["encoders"] == {"left": [[0, 5]], "right": [[0, -2.5], [1, 0]]}
    assert [f["kind"] for f in read["faults"]] == ["nack", "nack", "sda_held", "stale", "saturated"]
    assert read["faults"][2]["release"] == "scl_pulses"
    assert (read["faults"][4]["sensor"], read["faults"][4]["axes"]) == ("both", ["x", "z"])
    assert (read["bootloader"], read["motors_off_hold_s"]) == ("none", 0.005)
    assert read["stalls"] == [{"start_s": 0.8, "end_s": 0.9, "interrupts": False}]
    assert read["probes"] == [
        {"symbol": "update", "period_s": 0.01},
        {"symbol": "_Z4stepv", "period_s": None},
    ]
    assert (read["usb_sof"], read["battery_v"]) == (True, 6.0)
    assert read["trace"] == {"input_edges": True, "max_lines": 10}


def _many(n: int) -> list[dict[str, object]]:
    return [{"button": "B", "start_s": i / 2000, "end_s": (i + 0.5) / 2000} for i in range(n)]


#: Each wrong scenario, and where its refusal must say the fault lies.
REFUSED: list[tuple[str, object, str]] = [
    ("not JSON", "{", "the file"),
    ("too long", " " * ((1 << 20) + 1), "the file"),
    ("not an object", [1], "the scenario"),
    ("an unknown field", _base(fault=[]), "the scenario.fault"),
    ("no duration", {"avrsim_scenario": 1}, "the scenario.duration_s"),
    ("no version", {"duration_s": 1}, "the scenario.avrsim_scenario"),
    ("another version", _base(avrsim_scenario=2), "avrsim_scenario"),
    ("a duration of zero", _base(duration_s=0), "duration_s"),
    ("a duration past the bound", _base(duration_s=601), "duration_s"),
    ("a duration as text", _base(duration_s="1"), "duration_s"),
    ("an infinite duration", '{"avrsim_scenario": 1, "duration_s": 1e999}', "duration_s"),
    ("an empty profile", _base(imu={"pitch_rad": []}), "imu.pitch_rad"),
    ("a point of one number", _base(imu={"pitch_rad": [[0]]}), "imu.pitch_rad[0]"),
    ("times that do not rise", _base(imu={"pitch_rad": [[0, 0], [0, 1]]}), "imu.pitch_rad[1][0]"),
    ("a time past the end", _base(imu={"pitch_rad": [[0, 0], [2, 1]]}), "imu.pitch_rad[1][0]"),
    ("a pitch past its bound", _base(imu={"pitch_rad": [[0, 101]]}), "imu.pitch_rad[0][1]"),
    ("an unknown sensor field", _base(imu={"yaw_rad": [[0, 0]]}), "imu.yaw_rad"),
    (
        "raw counts of two axes",
        _base(imu={"raw": [{"t_s": 0, "gyro": [1, 2], "accel": [1, 2, 3]}]}),
        "imu.raw[0].gyro",
    ),
    (
        "raw counts past int16",
        _base(imu={"raw": [{"t_s": 0, "gyro": [0, 32768, 0], "accel": [0, 0, 0]}]}),
        "imu.raw[0].gyro[1]",
    ),
    (
        "raw counts that are not whole",
        _base(imu={"raw": [{"t_s": 0, "gyro": [0, 1.5, 0], "accel": [0, 0, 0]}]}),
        "imu.raw[0].gyro[1]",
    ),
    (
        "raw entries out of order",
        _base(
            imu={
                "raw": [
                    {"t_s": 0.5, "gyro": [0, 0, 0], "accel": [0, 0, 0]},
                    {"t_s": 0.2, "gyro": [0, 0, 0], "accel": [0, 0, 0]},
                ]
            }
        ),
        "imu.raw[1].t_s",
    ),
    (
        "a raw entry missing its accelerometer",
        _base(imu={"raw": [{"t_s": 0, "gyro": [0, 0, 0]}]}),
        "imu.raw[0].accel",
    ),
    ("an unknown encoder", _base(encoders={"left_rps": [[0, 1]]}), "encoders.left_rps"),
    (
        "an unknown fault",
        _base(faults=[{"kind": "brownout", "start_s": 0, "end_s": 1}]),
        "faults[0].kind",
    ),
    (
        "a NACK naming no device",
        _base(faults=[{"kind": "nack", "start_s": 0, "end_s": 1}]),
        "faults[0].device",
    ),
    (
        "a NACK of an unknown device",
        _base(faults=[{"kind": "nack", "device": "bmi160", "start_s": 0, "end_s": 1}]),
        "faults[0].device",
    ),
    (
        "a NACK given a sensor",
        _base(
            faults=[
                {"kind": "nack", "device": "lsm6ds33", "sensor": "gyro", "start_s": 0, "end_s": 1}
            ]
        ),
        "faults[0].sensor",
    ),
    (
        "a fault that ends before it starts",
        _base(faults=[{"kind": "stale", "start_s": 0.5, "end_s": 0.5}]),
        "faults[0].end_s",
    ),
    (
        "a fault past the end",
        _base(faults=[{"kind": "stale", "start_s": 0.5, "end_s": 1.5}]),
        "faults[0].end_s",
    ),
    (
        "two stale faults at once",
        _base(
            faults=[
                {"kind": "stale", "start_s": 0.1, "end_s": 0.5},
                {"kind": "stale", "start_s": 0.4, "end_s": 0.6},
            ]
        ),
        "faults[1]",
    ),
    (
        "a held bus with no release",
        _base(faults=[{"kind": "sda_held", "start_s": 0, "end_s": 1}]),
        "faults[0].release",
    ),
    (
        "a held bus with an unknown release",
        _base(faults=[{"kind": "sda_held", "release": "reset", "start_s": 0, "end_s": 1}]),
        "faults[0].release",
    ),
    (
        "a saturation of an unknown sensor",
        _base(
            faults=[
                {"kind": "saturated", "sensor": "magnet", "axes": ["y"], "start_s": 0, "end_s": 1}
            ]
        ),
        "faults[0].sensor",
    ),
    # An over-range clips the axis that is over its range (LSM6DS33 datasheet, FS): a saturation
    # names its axes.
    (
        "a saturation naming no axes",
        _base(faults=[{"kind": "saturated", "sensor": "gyro", "start_s": 0, "end_s": 1}]),
        "faults[0].axes",
    ),
    (
        "a saturation of an empty list of axes",
        _base(
            faults=[{"kind": "saturated", "sensor": "gyro", "axes": [], "start_s": 0, "end_s": 1}]
        ),
        "faults[0].axes",
    ),
    (
        "a saturation of an unknown axis",
        _base(
            faults=[
                {"kind": "saturated", "sensor": "gyro", "axes": ["w"], "start_s": 0, "end_s": 1}
            ]
        ),
        "faults[0].axes[0]",
    ),
    (
        "a saturation naming an axis twice",
        _base(
            faults=[
                {
                    "kind": "saturated",
                    "sensor": "gyro",
                    "axes": ["y", "y"],
                    "start_s": 0,
                    "end_s": 1,
                }
            ]
        ),
        "faults[0].axes",
    ),
    ("an unknown bootloader", _base(bootloader="caterina"), "bootloader"),
    ("a hold of zero", _base(motors_off_hold_s=0), "motors_off_hold_s"),
    ("a hold past the run", _base(motors_off_hold_s=2), "motors_off_hold_s"),
    (
        "too many faults",
        _base(
            faults=[
                {"kind": "stale", "start_s": i / 2000, "end_s": (i + 0.5) / 2000}
                for i in range(1001)
            ]
        ),
        "faults",
    ),
    (
        "a fourth button",
        _base(buttons=[{"button": "D", "start_s": 0, "end_s": 1}]),
        "buttons[0].button",
    ),
    (
        "a press held over another",
        _base(
            buttons=[
                {"button": "A", "start_s": 0, "end_s": 0.5},
                {"button": "A", "start_s": 0.4, "end_s": 0.6},
            ]
        ),
        "buttons[1]",
    ),
    ("too many presses", _base(buttons=_many(1001)), "buttons"),
    (
        "a stall that does not say about interrupts",
        _base(stalls=[{"start_s": 0, "end_s": 1}]),
        "stalls[0].interrupts",
    ),
    (
        "a stall's interrupts as text",
        _base(stalls=[{"start_s": 0, "end_s": 1, "interrupts": "on"}]),
        "stalls[0].interrupts",
    ),
    (
        "two stalls at once",
        _base(
            stalls=[
                {"start_s": 0, "end_s": 0.5, "interrupts": True},
                {"start_s": 0.2, "end_s": 0.3, "interrupts": False},
            ]
        ),
        "stalls[1]",
    ),
    ("start-of-frame as text", _base(usb_sof="true"), "usb_sof"),
    ("a battery past its bound", _base(battery_v=16), "battery_v"),
    ("a probe that is no symbol", _base(probes=[{"symbol": "a b"}]), "probes[0].symbol"),
    ("a probe beginning with a digit", _base(probes=[{"symbol": "1update"}]), "probes[0].symbol"),
    (
        "a probe named twice",
        _base(probes=[{"symbol": "update"}, {"symbol": "update"}]),
        "probes[1].symbol",
    ),
    (
        "a probe with a period of zero",
        _base(probes=[{"symbol": "update", "period_s": 0}]),
        "probes[0].period_s",
    ),
    ("too many probes", _base(probes=[{"symbol": f"f{i}"} for i in range(17)]), "probes"),
    (
        "a marker with no plain name",
        _base(markers=[{"name": "tilt beyond", "t_s": 0.5}]),
        "markers[0].name",
    ),
    ("a marker past the end", _base(markers=[{"name": "late", "t_s": 1.5}]), "markers[0].t_s"),
    (
        "a marker named twice",
        _base(markers=[{"name": "m", "t_s": 0.1}, {"name": "m", "t_s": 0.2}]),
        "markers[1].name",
    ),
    ("a trace bound of zero", _base(trace={"max_lines": 0}), "trace.max_lines"),
    ("a trace bound past the most", _base(trace={"max_lines": 20_000_001}), "trace.max_lines"),
    ("input edges as text", _base(trace={"input_edges": "yes"}), "trace.input_edges"),
    ("an unknown trace field", _base(trace={"pins": "all"}), "trace.pins"),
]


@pytest.mark.parametrize(("why", "scenario", "where"), REFUSED, ids=[r[0] for r in REFUSED])
def test_a_wrong_scenario_is_refused_where_it_is_wrong(
    why: str, scenario: object, where: str
) -> None:
    result = _read(scenario)
    assert "ok" not in result, f"{why}: read as {result.get('ok')}"
    assert result["where"] == where, result["refused"]
    assert result["refused"].startswith(f"the scenario is refused at {where}: ")


def test_faults_of_different_kinds_may_overlap_and_presses_of_different_buttons_too() -> None:
    read = _read(
        _base(
            faults=[
                {"kind": "stale", "start_s": 0.1, "end_s": 0.5},
                {
                    "kind": "saturated",
                    "sensor": "gyro",
                    "axes": ["y"],
                    "start_s": 0.2,
                    "end_s": 0.6,
                },
                {"kind": "nack", "device": "lsm6ds33", "start_s": 0.2, "end_s": 0.6},
                {"kind": "nack", "device": "lis3mdl", "start_s": 0.3, "end_s": 0.7},
            ],
            buttons=[
                {"button": "A", "start_s": 0, "end_s": 0.5},
                {"button": "C", "start_s": 0.1, "end_s": 0.2},
            ],
        )
    )
    assert len(read["ok"]["faults"]) == 4
    assert len(read["ok"]["buttons"]) == 2


PROFILE = """
const { profileAt, slopeAt } = await import(`${SRC}/scenario.js`);
const p = [[0.5, 1], [1.5, 3], [2.5, 3]];
out([0, 0.5, 1, 1.5, 2, 3].map((t) => [profileAt(p, t), slopeAt(p, t)]));
"""


def test_a_profile_is_held_before_its_first_point_and_after_its_last_and_linear_between() -> None:
    assert evaluate(PROFILE) == [[1, 0], [1, 2], [2, 2], [3, 0], [3, 0], [3, 0]]
