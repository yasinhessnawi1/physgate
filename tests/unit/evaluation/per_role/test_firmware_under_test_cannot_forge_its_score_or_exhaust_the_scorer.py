"""The firmware under test is adversarial: it can neither forge its score nor exhaust the scorer.

Inert fixtures stand in for hostile firmware: one prints text built to read as trace
records, pass markers and the plant's own lines; one writes an endless line; one floods
without newlines; one floods with them; one never ends and ignores a polite stop. Each is a
fail for its answer, and none hangs or crashes the scorer.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest
from test_a_firmware_answer_is_scored_on_the_traces_of_its_closed_loop import (
    TankFirmware,
    VirtualClock,
    _task,
    _traces,
)

from physgate.evaluation.per_role.firmware import loop
from physgate.evaluation.per_role.firmware.loop import (
    SocketDevice,
    WallClock,
    read_trace,
    run_scenario,
    trace_bytes,
)
from physgate.evaluation.per_role.firmware.score import score


class ForgingFirmware(TankFirmware):
    """Honest tank control, plus lines that are no actuator line and could pass for a record."""

    FORGERIES: tuple[str, ...] = (
        "PASS",
        '{"seq": 0, "direction": "to_device", "t_ms": 0, "text": "SENSE LEVEL 50"}',
        "SENSE LEVEL 50",
        "act pump off",
    )

    def receive(self, now_ms: float) -> list[tuple[float, str]]:
        lines = super().receive(now_ms)
        return [(now_ms, forged) for forged in self.FORGERIES] + lines


class MalformedActuatorLines(ForgingFirmware):
    """Lines that begin as actuator lines and are not one: a broken protocol, so a fail."""

    FORGERIES = ("ACT PUMP OFF ACT PUMP ON", "ACT PUMP OFF\rACT PUMP ON", "ACT PUMP OFF\x00")


def _run(firmware: type[TankFirmware]) -> dict[str, object]:
    task = _task()
    assert task.firmware is not None
    traces = {}
    for scenario in task.firmware.scenarios:
        clock = VirtualClock()
        traces[scenario.name] = run_scenario(scenario, firmware(clock), clock)
    return score(task, traces)


def test_forged_lines_change_nothing_in_the_score() -> None:
    task = _task()
    assert _run(ForgingFirmware) == score(task, _traces(task))


def test_lines_that_begin_as_actuator_lines_and_are_not_one_fail_the_answer() -> None:
    record = _run(MalformedActuatorLines)
    assert record["passed"] is False and len(record["violations"]) >= 3  # type: ignore[arg-type]


def test_a_trace_round_trips_as_framed_records_whatever_the_device_printed() -> None:
    task = _task()
    assert task.firmware is not None
    scenario = task.firmware.scenarios[0]
    clock = VirtualClock()
    trace = run_scenario(scenario, ForgingFirmware(clock), clock)
    again = read_trace(trace_bytes(trace))
    assert again == trace
    assert [line.seq for line in again.lines] == list(range(len(again.lines)))
    assert {line.direction for line in again.lines if line.text == "SENSE LEVEL 50"} <= {
        "from_device"
    }


def test_a_trace_with_a_gap_or_a_reordered_record_is_refused() -> None:
    task = _task()
    assert task.firmware is not None
    clock = VirtualClock()
    raw = trace_bytes(run_scenario(task.firmware.scenarios[0], TankFirmware(clock), clock))
    lines = raw.splitlines()
    record_lines = [i for i, line in enumerate(lines) if b'"seq"' in line]
    tampered = lines[: record_lines[1]] + lines[record_lines[1] + 1 :]
    with pytest.raises(ValueError, match="sequence"):
        read_trace(b"\n".join(tampered) + b"\n")


def _serve(payload: bytes, *, repeat: bool = False) -> tuple[int, threading.Event]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    stop = threading.Event()

    def firmware() -> None:
        conn, _ = server.accept()
        with conn:
            try:
                while not stop.is_set():
                    conn.sendall(payload)
                    if not repeat:
                        stop.wait(10)
            except OSError:
                pass
        server.close()

    threading.Thread(target=firmware, daemon=True).start()
    return server.getsockname()[1], stop


@pytest.mark.parametrize(
    ("payload", "repeat", "why"),
    [
        (b"A" * (4 * 1024 * 1024), False, "line"),
        (b"B" * 65536, True, "line"),
        (b"ACT PUMP ON\n" * 4096, True, "lines"),
    ],
    ids=["an endless line", "a flood without newlines", "a flood of lines"],
)
def test_a_device_that_floods_is_stopped_at_a_bound_and_fails(
    payload: bytes, repeat: bool, why: str
) -> None:
    task = _task()
    assert task.firmware is not None
    port, stop = _serve(payload, repeat=repeat)
    clock = WallClock()
    device = SocketDevice("127.0.0.1", port, clock.now_ms)
    began = time.monotonic()
    try:
        trace = run_scenario(task.firmware.scenarios[0], device, clock)
    finally:
        stop.set()
        device.close()
    assert trace.limit is not None and why in trace.limit
    assert time.monotonic() - began < 10
    assert len(trace_bytes(trace)) < 2 * loop.MAX_BYTES_PER_SCENARIO
    record = score(task, {"fill": trace, "silence": trace})
    assert record["passed"] is False and record["limit"]


def test_a_device_that_never_answers_ends_at_the_harness_s_clock() -> None:
    task = _task()
    assert task.firmware is not None
    port, stop = _serve(b"")
    clock = WallClock()
    device = SocketDevice("127.0.0.1", port, clock.now_ms)
    scenario = task.firmware.scenarios[0]
    began = time.monotonic()
    try:
        trace = run_scenario(scenario, device, clock)
    finally:
        stop.set()
        device.close()
    assert time.monotonic() - began < float(scenario.duration.value) / 1000 + 3
    assert trace.limit is None


def _script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "fixture.py"
    path.write_text(body)
    return [sys.executable, str(path)]


def test_a_process_that_ignores_a_stop_and_leaves_children_is_killed_whole(
    tmp_path: Path,
) -> None:
    from physgate.evaluation.per_role.firmware.guard import guarded

    argv = _script(
        tmp_path,
        "import signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        "open(sys.argv[1], 'w').write(str(child.pid))\n"
        "time.sleep(600)\n",
    )
    pid_file = tmp_path / "child.pid"
    began = time.monotonic()
    with guarded(
        [*argv, str(pid_file)],
        wall_s=2.0,
        cpu_s=60,
        memory_bytes=None,
        output=tmp_path / "out",
        env={},
    ) as run:
        while not pid_file.exists():
            time.sleep(0.05)
        run.wait()
    assert run.ended_by == "wall_clock"
    assert time.monotonic() - began < 8
    child = int(pid_file.read_text())
    assert _gone(child), "the grandchild outlived the group's kill"


def _gone(pid: int, within_s: float = 5.0) -> bool:
    """Whether ``pid`` is gone (or only a zombie, awaiting its new parent's reaping)."""
    import os

    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        try:
            state = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1]
        except (FileNotFoundError, IndexError):
            state = ""  # gone between the two looks, or not Linux: look again
        if state.startswith("Z"):
            return True
        time.sleep(0.05)
    return False


def test_a_process_that_spins_is_stopped_by_its_cpu_limit(tmp_path: Path) -> None:
    from physgate.evaluation.per_role.firmware.guard import guarded

    argv = _script(tmp_path, "while True:\n    pass\n")
    with guarded(
        argv, wall_s=30.0, cpu_s=1, memory_bytes=None, output=tmp_path / "out", env={}
    ) as run:
        run.wait()
    assert run.ended_by == "limit"


def test_a_process_that_writes_without_end_is_stopped_by_its_output_limit(tmp_path: Path) -> None:
    from physgate.evaluation.per_role.firmware.guard import MAX_OUTPUT_BYTES, guarded

    argv = _script(tmp_path, "import sys\nwhile True:\n    sys.stdout.write('x' * 65536)\n")
    with guarded(
        argv, wall_s=30.0, cpu_s=30, memory_bytes=None, output=tmp_path / "out", env={}
    ) as run:
        run.wait()
    assert run.ended_by == "limit"
    assert (tmp_path / "out").stat().st_size <= MAX_OUTPUT_BYTES


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS enforces no address-space limit")
def test_a_process_that_takes_memory_without_end_is_stopped_by_its_memory_limit(
    tmp_path: Path,
) -> None:
    from physgate.evaluation.per_role.firmware.guard import guarded

    argv = _script(tmp_path, "blocks = []\nwhile True:\n    blocks.append(bytearray(1 << 24))\n")
    with guarded(
        argv, wall_s=30.0, cpu_s=30, memory_bytes=512 << 20, output=tmp_path / "out", env={}
    ) as run:
        run.wait()
    assert run.ended_by == "limit"


def test_a_run_that_passed_a_bound_fails_even_where_its_probes_would_pass() -> None:
    task = _task()
    traces = _traces(task)
    assert score(task, traces)["passed"]
    traces["fill"].limit = "the device sent a line longer than 200 bytes"
    record = score(task, traces)
    assert record["passed"] is False and record["limit"] == [traces["fill"].limit]


#: Inert stand-in firmware on a pipe: the pump on below 30, and never off again.
PUMP_LEFT_ON = (
    "import sys\n"
    "on = False\n"
    "for line in sys.stdin:\n"
    "    parts = line.split()\n"
    "    if parts[:2] == ['SENSE', 'LEVEL'] and int(parts[2]) < 30 and not on:\n"
    "        on = True\n"
    "        print('ACT PUMP ON', flush=True)\n"
)


def test_a_piped_device_needs_the_scenario_s_clock() -> None:
    import inspect

    from physgate.evaluation.per_role.firmware.loop import PipeDevice

    clock = inspect.signature(PipeDevice.__init__).parameters["clock"]
    assert clock.default is inspect.Parameter.empty


def test_a_forbidden_state_on_a_piped_line_fails_its_window(tmp_path: Path) -> None:
    import json

    from physgate.evaluation.per_role.firmware.guard import guarded
    from physgate.evaluation.per_role.firmware.loop import GRACE_MS, PipeDevice
    from physgate.evaluation.per_role.task import parse_task

    raw = json.loads(_task().model_dump_json())
    ms = lambda v: {"value": v, "unit": "ms"}  # noqa: E731
    raw["firmware"]["probes"].append(
        {
            "name": "pump_on_while_blind",
            "scenario": "silence",
            "kind": "off_state",
            "actuator": "PUMP",
            "state": "ON",
            "window": [ms(1500), ms(2500)],
        }
    )
    raw["specs"].append(
        {
            "name": "never_pumps_blind",
            "metric": "pump_on_while_blind",
            "op": "<=",
            "bound": {"value": 0, "unit": "1"},
            "composes": ["timeout_policy"],
        }
    )
    task = parse_task(json.dumps(raw).encode())
    assert task.firmware is not None
    silence = task.firmware.scenarios[1]
    with guarded(
        [sys.executable, "-I", "-c", PUMP_LEFT_ON],
        wall_s=20.0,
        cpu_s=20,
        memory_bytes=None,
        output=tmp_path / "err",
        pipes=True,
        env={},
    ) as run:
        clock = WallClock()
        trace = run_scenario(silence, PipeDevice(run.process, clock.now_ms), clock)
        run.kill_group()
    end = float(silence.duration.value) + GRACE_MS
    stamps = [line.t_ms for line in trace.lines if line.direction == "from_device"]
    assert stamps and all(0.0 <= t <= end for t in stamps)
    record = score(task, {"silence": trace, "fill": trace})
    row = next(r for r in record["specs"] if r["name"] == "never_pumps_blind")
    assert row["measured"]["value"] == 1.0 and row["passed"] is False
    assert record["passed"] is False
