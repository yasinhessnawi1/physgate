"""Whatever the guest does on its line, its answer fails on the record and the scorer goes on.

Inert fixtures: a device that hangs up at once, one that resets the line, one that names an
actuator the protocol does not have, one that leaves half a line, one whose line raises
something unexpected. Each is a recorded fail for its answer; scoring the next answer goes
on. And the emulator's process is tracked by the handle that spawned it: nothing reaps it
behind the guard's back, and a state the guard cannot read counts as a limit passed.
"""

from __future__ import annotations

import os
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from test_a_firmware_answer_is_scored_on_the_traces_of_its_closed_loop import (
    TankFirmware,
    VirtualClock,
    _task,
    _traces,
)

from physgate.evaluation.per_role.firmware.loop import SocketDevice, WallClock, run_scenario
from physgate.evaluation.per_role.firmware.score import safe_score, score


def _serve(behave: Any) -> int:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def run() -> None:
        conn, _ = server.accept()
        behave(conn)
        server.close()

    threading.Thread(target=run, daemon=True).start()
    port: int = server.getsockname()[1]
    return port


def _hang_up(conn: socket.socket) -> None:
    conn.close()


def _reset(conn: socket.socket) -> None:
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    conn.close()


def _half_a_line(conn: socket.socket) -> None:
    conn.sendall(b"ACT PUMP ON\nACT PU")
    time.sleep(5)
    conn.close()


@pytest.mark.parametrize(
    ("behave", "why"),
    [(_hang_up, "closed"), (_reset, "closed"), (_half_a_line, "partial")],
    ids=["hangs up", "resets", "half a line"],
)
def test_a_line_that_ends_or_breaks_early_is_a_recorded_fail(behave: Any, why: str) -> None:
    task = _task()
    assert task.firmware is not None
    port = _serve(behave)
    clock = WallClock()
    device = SocketDevice("127.0.0.1", port, clock.now_ms)
    scenario = task.firmware.scenarios[0].model_copy(
        update={"duration": task.firmware.scenarios[0].tick.model_copy(update={"value": 500})}
    )
    try:
        trace = run_scenario(scenario, device, clock)
    finally:
        device.close()
    assert trace.limit is not None and why in trace.limit


class UnknownActuator(TankFirmware):
    def receive(self, now_ms: float) -> list[tuple[float, str]]:
        return [(now_ms, "ACT VALVE OPEN"), *super().receive(now_ms)]


def test_an_actuator_or_state_off_the_protocol_is_a_fail() -> None:
    task = _task()
    assert task.firmware is not None
    traces = {}
    for scenario in task.firmware.scenarios:
        clock = VirtualClock()
        traces[scenario.name] = run_scenario(scenario, UnknownActuator(clock), clock)
    record = score(task, traces)
    assert record["passed"] is False
    assert any("VALVE" in v for v in record["violations"])


class Exploding(TankFirmware):
    def receive(self, now_ms: float) -> list[tuple[float, str]]:
        raise RuntimeError("the line raised something nobody expected")


def test_a_device_that_raises_anything_is_a_recorded_fail() -> None:
    task = _task()
    assert task.firmware is not None
    clock = VirtualClock()
    trace = run_scenario(task.firmware.scenarios[0], Exploding(clock), clock)
    assert trace.limit is not None and "failed the run" in trace.limit


def test_one_answer_that_breaks_the_scorer_fails_alone_and_the_next_is_scored() -> None:
    task = _task()
    broken = safe_score(task, {"fill": object()})  # type: ignore[dict-item]
    assert broken["passed"] is False and broken["error"]
    assert safe_score(task, _traces(task))["passed"] is True


def _script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "fixture.py"
    path.write_text(body)
    return [sys.executable, str(path)]


def test_nothing_reaps_the_emulator_behind_the_guard_s_back(tmp_path: Path) -> None:
    from physgate.evaluation.per_role.firmware.guard import guarded

    with guarded(
        _script(tmp_path, "pass\n"), wall_s=5.0, cpu_s=5, memory_bytes=None, output=tmp_path / "o"
    ) as run:
        time.sleep(0.5)  # it has exited; the watchdog has looked at it many times
        assert run.process.returncode is None  # still the guard's to reap, its pid still held
        assert run.wait() == "exited"


def test_a_state_the_guard_cannot_read_counts_as_a_limit_passed(tmp_path: Path) -> None:
    from physgate.evaluation.per_role.firmware.guard import guarded

    with guarded(
        _script(tmp_path, "pass\n"), wall_s=5.0, cpu_s=5, memory_bytes=None, output=tmp_path / "o"
    ) as run:
        time.sleep(0.3)
        os.waitpid(run.process.pid, 0)  # reaped by someone else: its end can no longer be read
        assert run.wait() == "limit"
