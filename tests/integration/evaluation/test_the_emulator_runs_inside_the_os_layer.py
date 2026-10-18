"""The emulator runs inside the OS layer, through the pinned sandbox runtime, or not at all.

An inert Python script stands in for QEMU: it tries everything the code it would run could
try (read the user's files, write outside its scratch, reach the network, fork without end)
and talks on its serial line, standard input and output. It needs the evaluation's sandbox
runtime installed (``npm ci`` in ``tools/srt``) and Node 22 on the search path.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from physgate.evaluation.per_role.firmware.loop import DeviceFaultError, PipeDevice
from physgate.evaluation.per_role.firmware.sandbox import (
    EmulatorLimits,
    FirmwareTierRefusedError,
    sandboxed,
)

pytestmark = pytest.mark.integration

PROBE = """
import os, socket, subprocess, sys, time
def attempt(what, fn):
    try:
        fn(); print(what, "ALLOWED", flush=True)
    except Exception as exc:
        print(what, "denied", type(exc).__name__, flush=True)
attempt("read-secret", lambda: open(sys.argv[1]).read())
attempt("write-outside", lambda: open(sys.argv[2], "w").write("x"))
attempt("write-scratch", lambda: open(os.path.join(os.getcwd(), "ok.txt"), "w").write("x"))
attempt("network", lambda: socket.create_connection(("1.1.1.1", 80), timeout=3))
attempt("loopback", lambda: socket.create_connection(("127.0.0.1", int(sys.argv[3])), timeout=3))
line = sys.stdin.readline()
print("ACT ECHO " + line.strip(), flush=True)
"""

FORK_BOMB = """
import os, sys, time
children = 0
for _ in range(500):
    try:
        if os.fork() == 0:
            time.sleep(30)
            os._exit(0)
        children += 1
    except OSError:
        break
print("CHILDREN", children, flush=True)
time.sleep(30)
"""


def _setup(tmp_path: Path, body: str) -> tuple[Path, Path, list[str]]:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    script = scratch / "emulator.py"
    script.write_text(body)
    # The base interpreter, which the emulator's own files stand for: a virtual environment's
    # interpreter lives under the user's home, which the sandbox withholds.
    readable = Path(sys.base_prefix)
    interpreter = readable / "bin" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    return scratch, readable, [str(interpreter), "-I", str(script)]


def _lines(device: PipeDevice, until: float, want: int) -> list[str]:
    seen: list[str] = []
    while time.monotonic() < until and len(seen) < want:
        try:
            seen += [text for _, text in device.receive(0.0)]
        except DeviceFaultError as ended:  # the emulator exited: keep what it sent first
            seen += [text for _, text in ended.lines]
            break
        time.sleep(0.05)
    return seen


def test_the_emulator_reads_writes_and_reaches_only_what_it_is_given(tmp_path: Path) -> None:
    import socket

    secret = Path.home() / f".physgate-test-secret-{os.getpid()}"
    secret.write_text("a secret the emulator must not read")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        scratch, readable, argv = _setup(tmp_path, PROBE)
        outside = tmp_path / "outside.txt"
        argv += [str(secret), str(outside), str(listener.getsockname()[1])]
        limits = EmulatorLimits(wall_s=30.0, cpu_s=20, memory_bytes=1 << 30, tasks=32)
        with sandboxed(argv, scratch=scratch, readable=(readable,), limits=limits) as session:
            device = PipeDevice(session.run.process)
            first = _lines(device, time.monotonic() + 20, 5)
            device.send("PING", 0.0)
            echo = _lines(device, time.monotonic() + 10, 1)
            session.run.kill_group()
    finally:
        secret.unlink()
        listener.close()
    results = dict(line.split(" ", 1) for line in first)
    assert results["read-secret"].startswith("denied")
    assert results["write-outside"].startswith("denied") and not outside.exists()
    assert results["write-scratch"] == "ALLOWED"
    assert results["network"].startswith("denied")
    assert results["loopback"].startswith("denied")
    assert echo == ["ACT ECHO PING"]
    assert session.record["os_layer"] in ("seatbelt", "bubblewrap")


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS has no process cap; the run says so")
def test_a_fork_bomb_is_held_to_the_process_cap(tmp_path: Path) -> None:
    scratch, readable, argv = _setup(tmp_path, FORK_BOMB)
    limits = EmulatorLimits(wall_s=20.0, cpu_s=20, memory_bytes=1 << 30, tasks=16)
    with sandboxed(argv, scratch=scratch, readable=(readable,), limits=limits) as session:
        device = PipeDevice(session.run.process)
        lines = _lines(device, time.monotonic() + 15, 1)
        session.run.kill_group()
    count = int(lines[0].split()[1])
    assert count < 16
    assert session.record["process_cap"] == "TasksMax=16"


def test_on_macos_the_absent_process_cap_is_recorded(tmp_path: Path) -> None:
    if sys.platform != "darwin":
        pytest.skip("only macOS runs without a process cap")
    scratch, readable, argv = _setup(tmp_path, "print('ok', flush=True)\n")
    limits = EmulatorLimits(wall_s=20.0, cpu_s=20, memory_bytes=1 << 30, tasks=16)
    with sandboxed(argv, scratch=scratch, readable=(readable,), limits=limits) as session:
        session.run.wait()
    assert session.record["process_cap"] == "none (macOS)"


def test_where_the_os_layer_is_absent_the_firmware_tier_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.oslayer.probe import Absent

    monkeypatch.setattr(
        "physgate.evaluation.per_role.firmware.sandbox.judge_here",
        lambda **_k: Absent(reason="test: no sandbox", no_os_protection=False),
    )
    scratch, readable, argv = _setup(tmp_path, "print('ran', flush=True)\n")
    limits = EmulatorLimits(wall_s=5.0, cpu_s=5, memory_bytes=None, tasks=16)
    with (
        pytest.raises(FirmwareTierRefusedError, match="OS layer"),
        sandboxed(argv, scratch=scratch, readable=(readable,), limits=limits),
    ):
        pass
