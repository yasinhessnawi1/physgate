"""A firmware answer, run in closed loop with a plant, is scored on its traces alone.

The device here is a stand-in for firmware in QEMU: a tank controller written in Python,
reached on a virtual clock so the runs are exact. The plant, the scenarios, the probes and
the score are the real ones; only the serial line and the clock are stood in for.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.per_role.firmware.loop import run_scenario
from physgate.evaluation.per_role.firmware.plant import Plant
from physgate.evaluation.per_role.firmware.score import score, verdict
from physgate.evaluation.per_role.task import Task, parse_task


class VirtualClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now_ms(self) -> float:
        return self.t

    def wait_until(self, t_ms: float) -> None:
        self.t = max(self.t, t_ms)


class TankFirmware:
    """Pump on below 30, off above 80, holds between; off on a malformed line or 1 s of silence.

    The silence is counted from the last frame, which came one frame period before the
    fault's start, so the reaction to the fault is a little under the timeout.
    """

    def __init__(self, clock: VirtualClock, *, latency_ms: float = 5.0, timeout: bool = True):
        self.clock, self.latency, self.timeout = clock, latency_ms, timeout
        self.out: list[tuple[float, str]] = []
        self.pump: str | None = None
        self.last_frame = 0.0

    def _set(self, state: str, at: float) -> None:
        if state != self.pump:
            self.pump = state
            self.out.append((at + self.latency, f"ACT PUMP {state}"))

    def send(self, line: str, now_ms: float) -> None:
        parts = line.split()
        if len(parts) == 3 and parts[:2] == ["SENSE", "LEVEL"] and parts[2].isdigit():
            self.last_frame = now_ms
            level = int(parts[2])
            if level < 30:
                self._set("ON", now_ms)
            elif level > 80:
                self._set("OFF", now_ms)
        else:
            self._set("OFF", now_ms)

    def receive(self, now_ms: float) -> list[tuple[float, str]]:
        if self.timeout and self.pump == "ON" and now_ms - self.last_frame > 1000:
            self._set("OFF", now_ms)
        ready = [(t, s) for t, s in self.out if t <= now_ms]
        self.out = [(t, s) for t, s in self.out if t > now_ms]
        return ready


def _ms(v: float) -> dict[str, Any]:
    return {"value": v, "unit": "ms"}


def _pct(name: str, v: float, unit: str = "percent") -> dict[str, Any]:
    return {"name": name, "value": v, "unit": unit}


PLANT = [
    _pct("level_rate_pump_on", 60.0, "percent/s"),
    _pct("level_leak", 0.0, "1/s"),
    _pct("level_rest", 0.0),
    _pct("level_min", 0.0),
    _pct("level_max", 100.0),
]


def _task() -> Task:
    scenario = {
        "plant": "integrator",
        "params": PLANT,
        "initial": [_pct("level", 10.0)],
        "tick": _ms(50),
        "frame_period": _ms(100),
    }
    task = {
        "id": "firmware.tank",
        "role": "firmware",
        "tier": "visible",
        "source": {"kind": "own"},
        "brief": "Keep the tank between 30 and 80 and fail safe.",
        "answer": {"path": "firmware", "form": "espidf_project"},
        "specs": [
            {
                "name": "fails_safe_in_time",
                "metric": "silence_reaction",
                "op": "in",
                "bound": [_ms(900), _ms(1200)],
                "composes": ["timeout_policy"],
            },
            {
                "name": "never_overfills",
                "metric": "peak_level",
                "op": "<=",
                "bound": {"value": 95, "unit": "percent"},
                "composes": ["fill_control"],
            },
        ],
        "scorer": {"id": "firmware", "version": "1.0.0"},
        "firmware": {
            "protocol": {"sensors": ["LEVEL"], "actuators": {"PUMP": ["ON", "OFF"]}},
            "scenarios": [
                {**scenario, "name": "fill", "duration": _ms(3000)},
                {
                    **scenario,
                    "name": "silence",
                    "initial": [_pct("level", 10.0)],
                    "duration": _ms(2500),
                    "faults": [
                        {
                            "name": "frames_stop",
                            "kind": "silence",
                            "at": _ms(200),
                            "length": _ms(5000),
                        }
                    ],
                },
            ],
            "probes": [
                {
                    "name": "silence_reaction",
                    "scenario": "silence",
                    "kind": "reaction",
                    "fault": "frames_stop",
                    "actuator": "PUMP",
                    "state": "OFF",
                },
                {
                    "name": "peak_level",
                    "scenario": "fill",
                    "kind": "plant_peak",
                    "variable": "level",
                },
            ],
        },
    }
    return parse_task(json.dumps(task).encode())


def _traces(task: Task, **firmware: Any) -> dict[str, Any]:
    assert task.firmware is not None
    traces = {}
    for scenario in task.firmware.scenarios:
        clock = VirtualClock()
        traces[scenario.name] = run_scenario(scenario, TankFirmware(clock, **firmware), clock)
    return traces


def test_firmware_that_meets_its_specs_passes_and_scores_the_same_every_time() -> None:
    task = _task()
    first, second = score(task, _traces(task)), score(task, _traces(task))
    assert first == second and first["passed"]
    reaction = first["specs"][0]["measured"]
    assert reaction["unit"] == "ms" and 900 <= reaction["value"] <= 1200


def test_firmware_that_never_times_out_fails_its_reaction_and_nothing_else() -> None:
    task = _task()
    record = score(task, _traces(task, timeout=False))
    assert [row["passed"] for row in record["specs"]] == [False, True]
    assert record["specs"][0]["measured"] is None


def test_a_slow_reaction_is_measured_and_fails_its_window() -> None:
    task = _task()
    record = score(task, _traces(task, latency_ms=400))
    assert record["specs"][0]["measured"]["value"] > 1200 and not record["passed"]


def test_three_runs_that_disagree_are_flaky_and_never_a_pass() -> None:
    passing, failing = {"passed": True}, {"passed": False}
    assert verdict([passing] * 3) == "pass"
    assert verdict([failing] * 3) == "fail"
    assert verdict([passing, passing, failing]) == "flaky"
    with pytest.raises(ValueError, match="3 runs"):
        verdict([passing, passing])


def test_the_plant_is_an_integrator_clamped_to_its_range() -> None:
    task = _task()
    assert task.firmware is not None
    scenario = task.firmware.scenarios[0]
    plant = Plant(scenario.params, scenario.initial)
    plant.step(1.0, {"PUMP": "ON"})
    assert plant.values["level"] == pytest.approx(70.0)
    plant.step(1.0, {"PUMP": "ON"})
    assert plant.values["level"] == 100.0 and plant.frames() == ["SENSE LEVEL 100"]


def test_a_spec_bounding_no_probe_or_in_another_unit_is_refused() -> None:
    raw = json.loads(_task().model_dump_json())
    raw["specs"][1]["metric"] = "no_such_probe"
    with pytest.raises(TaskFormatError, match="no probe"):
        score(parse_task(json.dumps(raw).encode()), {})
    raw = json.loads(_task().model_dump_json())
    raw["specs"][0]["bound"] = [{"value": 1, "unit": "s"}, {"value": 2, "unit": "s"}]
    with pytest.raises(TaskFormatError, match="another unit"):
        score(parse_task(json.dumps(raw).encode()), {})


def test_the_serial_line_is_a_socket_read_line_by_line_with_arrival_times() -> None:
    import socket
    import threading

    from physgate.evaluation.per_role.firmware.loop import SocketDevice, WallClock

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def firmware() -> None:
        conn, _ = server.accept()
        buffer = b""
        with conn:
            while b"SENSE LEVEL" not in buffer:
                buffer += conn.recv(1024)
            conn.sendall(b"ACT PUMP ON\r\nACT PU")  # a line, and half of another
            conn.sendall(b"MP OFF\n")

    thread = threading.Thread(target=firmware)
    thread.start()
    clock = WallClock()
    device = SocketDevice("127.0.0.1", port, clock.now_ms)
    try:
        task = _task()
        assert task.firmware is not None
        short = task.firmware.scenarios[0].model_copy(
            update={"duration": task.firmware.scenarios[0].tick}
        )
        trace = run_scenario(short, device, clock)
        deadline = clock.now_ms() + 2000
        received = [line.text for line in trace.lines if line.direction == "from_device"]
        while len(received) < 2 and clock.now_ms() < deadline:
            received += [text for _, text in device.receive(clock.now_ms())]
    finally:
        device.close()
        thread.join()
        server.close()
    assert received == ["ACT PUMP ON", "ACT PUMP OFF"]


def test_a_state_set_before_the_fault_is_no_reaction_to_it() -> None:
    task = _task()
    assert task.firmware is not None
    silence = task.firmware.scenarios[1]
    full = silence.model_copy(
        update={"initial": tuple(m.model_copy(update={"value": 90.0}) for m in silence.initial)}
    )
    clock = VirtualClock()
    trace = run_scenario(full, TankFirmware(clock), clock)  # OFF at 5 ms, the fault at 200 ms
    record = score(task, {"silence": trace, "fill": _traces(task)["fill"]})
    assert record["specs"][0]["measured"] is None
