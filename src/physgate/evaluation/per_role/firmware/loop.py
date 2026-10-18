"""One scenario run in closed loop against a device on a serial line, and the trace it leaves.

The device is the firmware under test: in a run, QEMU's emulated UART reached through a
local socket; in the tests, a stand-in written in Python. Each step of the scenario's time
step, the plant advances under the actuator states the device last set; at each frame
period the plant's sensor frames are sent, unless a silence fault holds them back; at each
fault's start its line (a malformed one, or ``FAULT SENSOR_TIMEOUT``) is sent; every line
the device sends is received with the time it arrived. The trace is everything sent and
received, with its times, and the plant's values at every step; the score is a pure
function of it (:mod:`.score`).

Time is a clock the runner is given: the wall clock in a run, a virtual one in the tests.
"""

from __future__ import annotations

import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from physgate.evaluation.per_role.firmware.plant import Plant
from physgate.evaluation.per_role.firmware.spec import Scenario

ACT_LINE = re.compile(r"^ACT ([A-Z][A-Z0-9_]{0,31}) ([A-Z][A-Z0-9_]{0,31})$")
FAULT_FRAME = "FAULT SENSOR_TIMEOUT"
#: The longest line the runner reads from a device; anything longer is cut and kept as is.
MAX_LINE = 200


@dataclass(frozen=True)
class Line:
    """One line on the serial line: when, which way, what."""

    t_ms: float
    direction: Literal["to_device", "from_device"]
    text: str


@dataclass
class Trace:
    """Everything one scenario's run sent and received, and the plant's values at each step."""

    scenario: str
    lines: list[Line] = field(default_factory=list)
    samples: list[tuple[float, dict[str, float]]] = field(default_factory=list)


class Device(Protocol):
    """The firmware under test, as seen from the plant's side of the line."""

    def send(self, line: str, now_ms: float) -> None:
        """Send one line to the device."""

    def receive(self, now_ms: float) -> list[tuple[float, str]]:
        """Every complete line the device has sent since the last call, each with its time."""


class Clock(Protocol):
    """Milliseconds since the scenario began, and a way to wait until a later time."""

    def now_ms(self) -> float:
        """The time now."""

    def wait_until(self, t_ms: float) -> None:
        """Return at ``t_ms`` or later."""


class WallClock:
    """The machine's monotonic clock."""

    def __init__(self) -> None:
        """Start now."""
        self._start = time.monotonic()

    def now_ms(self) -> float:
        """Milliseconds since start."""
        return (time.monotonic() - self._start) * 1000.0

    def wait_until(self, t_ms: float) -> None:
        """Sleep until ``t_ms``."""
        delay = t_ms - self.now_ms()
        if delay > 0:
            time.sleep(delay / 1000.0)


class SocketDevice:
    """A device reached through a TCP socket: QEMU's serial line, as ``-serial tcp:…``."""

    def __init__(self, host: str, port: int, clock: Callable[[], float], connect_s: float = 10.0):
        """Connect, retrying until ``connect_s`` has passed (QEMU listens before it boots)."""
        deadline = time.monotonic() + connect_s
        while True:
            try:
                self._sock = socket.create_connection((host, port), timeout=1.0)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        self._sock.setblocking(False)
        self._clock = clock
        self._pending = b""

    def send(self, line: str, now_ms: float) -> None:
        """Write the line and its newline."""
        self._sock.sendall(line.encode("ascii") + b"\n")

    def receive(self, now_ms: float) -> list[tuple[float, str]]:
        """Every complete line that has arrived, stamped with the time it was read."""
        while True:
            try:
                chunk = self._sock.recv(4096)
            except BlockingIOError:
                break
            if not chunk:
                break
            self._pending += chunk
        lines: list[tuple[float, str]] = []
        while b"\n" in self._pending:
            raw, self._pending = self._pending.split(b"\n", 1)
            text = raw[:MAX_LINE].decode("ascii", errors="replace").rstrip("\r")
            lines.append((self._clock(), text))
        return lines

    def close(self) -> None:
        """Close the line."""
        self._sock.close()


def run_scenario(scenario: Scenario, device: Device, clock: Clock) -> Trace:
    """Run ``scenario`` against ``device`` in closed loop; the trace it leaves."""
    plant = Plant(scenario.params, scenario.initial)
    trace = Trace(scenario=scenario.name)
    tick = float(scenario.tick.value)
    period = float(scenario.frame_period.value)
    end = float(scenario.duration.value)
    actuators: dict[str, str] = {}
    pending_faults = sorted(scenario.faults, key=lambda f: float(f.at.value))
    silences = [
        (float(f.at.value), float(f.at.value) + float(f.length.value))
        for f in scenario.faults
        if f.kind == "silence" and f.length is not None
    ]
    next_frame = 0.0
    t = 0.0
    while t <= end:
        clock.wait_until(t)
        now = clock.now_ms()
        for at, text in device.receive(now):
            trace.lines.append(Line(at, "from_device", text))
            found = ACT_LINE.match(text)
            if found:
                actuators[found[1]] = found[2]
        while pending_faults and float(pending_faults[0].at.value) <= t:
            fault = pending_faults.pop(0)
            if fault.kind in ("malformed", "fault_frame"):
                text = fault.line if fault.kind == "malformed" and fault.line else FAULT_FRAME
                device.send(text, now)
                trace.lines.append(Line(now, "to_device", text))
        if t >= next_frame:
            if not any(start <= t < stop for start, stop in silences):
                for text in plant.frames():
                    device.send(text, now)
                    trace.lines.append(Line(now, "to_device", text))
            next_frame += period
        plant.step(tick / 1000.0, actuators)
        trace.samples.append((t, dict(plant.values)))
        t += tick
    for at, text in device.receive(clock.now_ms()):
        trace.lines.append(Line(at, "from_device", text))
    return trace
