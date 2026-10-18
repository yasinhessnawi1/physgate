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

import contextlib
import json
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from physgate.evaluation.per_role.firmware.plant import Plant
from physgate.evaluation.per_role.firmware.spec import Scenario

ACT_LINE = re.compile(r"^ACT ([A-Z][A-Z0-9_]{0,31}) ([A-Z][A-Z0-9_]{0,31})\Z")
FAULT_FRAME = "FAULT SENSOR_TIMEOUT"
#: Bounds on everything the firmware under test can drive, counted on the bytes as they
#: arrive, before anything is decoded or split. Passing one ends the scenario as a fail for
#: the answer, recorded in the trace; it never grows the scorer's memory or stalls it.
MAX_LINE = 200
MAX_BYTES_PER_SCENARIO = 256 * 1024
MAX_LINES_PER_SCENARIO = 2_000
#: The most read from the line in one step, so a flood cannot hold a step past its time.
MAX_READ_PER_STEP = 16 * 1024
#: How long past the scenario's own length the harness's clock lets a run go.
GRACE_MS = 2000.0


class DeviceLimitError(Exception):
    """The device passed a bound on what it may send."""


@dataclass(frozen=True)
class Line:
    """One line on the serial line, framed by the plant's side: its number, when, which way.

    ``seq`` and ``direction`` are the runner's, never the device's: whatever a device
    prints is a ``from_device`` line's ``text`` and nothing else.
    """

    seq: int
    t_ms: float
    direction: Literal["to_device", "from_device"]
    text: str


@dataclass
class Trace:
    """Everything one scenario's run sent and received, and the plant's values at each step.

    ``limit`` names the bound the device passed, if it passed one; the answer then fails.
    """

    scenario: str
    lines: list[Line] = field(default_factory=list)
    samples: list[tuple[float, dict[str, float]]] = field(default_factory=list)
    limit: str | None = None

    def add(self, t_ms: float, direction: Literal["to_device", "from_device"], text: str) -> None:
        """Append one line, numbered next."""
        self.lines.append(Line(len(self.lines), t_ms, direction, text))


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
    """A device reached through a TCP socket: QEMU's serial line, as ``-serial tcp:…``.

    Every byte is counted as it arrives, before it is decoded or split: a line longer than
    :data:`MAX_LINE`, more than :data:`MAX_BYTES_PER_SCENARIO` bytes or more than
    :data:`MAX_LINES_PER_SCENARIO` lines raises :class:`DeviceLimitError`, so an endless
    line or a flood is a bounded fail, never a buffer that grows.
    """

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
        self._bytes = 0
        self._lines = 0

    def send(self, line: str, now_ms: float) -> None:
        """Write the line and its newline."""
        # A device that does not read its input is judged by what it then does.
        with contextlib.suppress(BlockingIOError):
            self._sock.sendall(line.encode("ascii") + b"\n")

    def receive(self, now_ms: float) -> list[tuple[float, str]]:
        """Every complete line that has arrived, stamped with the time it was read.

        Raises:
            DeviceLimitError: the device passed a bound.
        """
        taken = 0
        while taken < MAX_READ_PER_STEP:
            try:
                chunk = self._sock.recv(min(4096, MAX_READ_PER_STEP - taken))
            except BlockingIOError:
                break
            if not chunk:
                break
            taken += len(chunk)
            self._bytes += len(chunk)
            if self._bytes > MAX_BYTES_PER_SCENARIO:
                msg = f"the device sent more than {MAX_BYTES_PER_SCENARIO} bytes"
                raise DeviceLimitError(msg)
            self._pending += chunk
            if len(self._pending) > MAX_LINE and b"\n" not in self._pending[: MAX_LINE + 1]:
                msg = f"the device sent a line longer than {MAX_LINE} bytes"
                raise DeviceLimitError(msg)
        lines: list[tuple[float, str]] = []
        while b"\n" in self._pending:
            raw, self._pending = self._pending.split(b"\n", 1)
            if len(raw) > MAX_LINE:
                msg = f"the device sent a line longer than {MAX_LINE} bytes"
                raise DeviceLimitError(msg)
            self._lines += 1
            if self._lines > MAX_LINES_PER_SCENARIO:
                msg = f"the device sent more than {MAX_LINES_PER_SCENARIO} lines"
                raise DeviceLimitError(msg)
            text = raw.decode("ascii", errors="replace").removesuffix("\r")
            lines.append((self._clock(), text))
        if len(self._pending) > MAX_LINE:
            msg = f"the device sent a line longer than {MAX_LINE} bytes"
            raise DeviceLimitError(msg)
        return lines

    def close(self) -> None:
        """Close the line."""
        self._sock.close()


def run_scenario(scenario: Scenario, device: Device, clock: Clock) -> Trace:
    """Run ``scenario`` against ``device`` in closed loop; the trace it leaves.

    The scenario ends at its length, or at the harness's own clock :data:`GRACE_MS` later,
    whatever the device does, or at the first bound the device passes, which is recorded.
    """
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
    try:
        while t <= end:
            clock.wait_until(t)
            now = clock.now_ms()
            if now > end + GRACE_MS:
                trace.limit = "the run passed the harness's clock"
                break
            for at, text in device.receive(now):
                trace.add(at, "from_device", text)
                found = ACT_LINE.match(text)
                if found:
                    actuators[found[1]] = found[2]
            while pending_faults and float(pending_faults[0].at.value) <= t:
                fault = pending_faults.pop(0)
                if fault.kind in ("malformed", "fault_frame"):
                    text = fault.line if fault.kind == "malformed" and fault.line else FAULT_FRAME
                    device.send(text, now)
                    trace.add(now, "to_device", text)
            if t >= next_frame:
                if not any(start <= t < stop for start, stop in silences):
                    for text in plant.frames():
                        device.send(text, now)
                        trace.add(now, "to_device", text)
                next_frame += period
            plant.step(tick / 1000.0, actuators)
            trace.samples.append((t, dict(plant.values)))
            t += tick
        for at, text in device.receive(clock.now_ms()):
            trace.add(at, "from_device", text)
    except DeviceLimitError as exc:
        trace.limit = str(exc)
    return trace


def trace_bytes(trace: Trace) -> bytes:
    """The trace as framed records, one JSON object per line, the device's text a string."""
    records: list[dict[str, Any]] = [{"scenario": trace.scenario, "limit": trace.limit}]
    records += [
        {"seq": line.seq, "t_ms": line.t_ms, "direction": line.direction, "text": line.text}
        for line in trace.lines
    ]
    records += [{"sample_ms": t, "values": values} for t, values in trace.samples]
    return b"".join(json.dumps(r, sort_keys=True).encode() + b"\n" for r in records)


def read_trace(raw: bytes) -> Trace:
    """A trace from its framed records, refused unless every record is whole and in sequence.

    Raises:
        ValueError: a record is malformed, a line's number is out of sequence, or a field
            is not what the runner writes.
    """
    rows = [json.loads(line) for line in raw.splitlines()]
    head, rest = rows[0], rows[1:]
    trace = Trace(scenario=str(head["scenario"]), limit=head["limit"])
    for row in rest:
        if "seq" in row:
            if set(row) != {"seq", "t_ms", "direction", "text"} or row["seq"] != len(trace.lines):
                msg = f"a trace line is out of sequence or malformed: {row!r}"
                raise ValueError(msg)
            if row["direction"] not in ("to_device", "from_device") or len(row["text"]) > MAX_LINE:
                msg = f"a trace line is not one the runner writes: {row!r}"
                raise ValueError(msg)
            trace.lines.append(
                Line(row["seq"], float(row["t_ms"]), row["direction"], str(row["text"]))
            )
        elif set(row) == {"sample_ms", "values"}:
            trace.samples.append(
                (float(row["sample_ms"]), {k: float(v) for k, v in row["values"].items()})
            )
        else:
            msg = f"a trace record is neither a line nor a sample: {row!r}"
            raise ValueError(msg)
    return trace
