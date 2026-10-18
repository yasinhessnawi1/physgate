"""The emulator runs inside the OS layer, through the pinned sandbox runtime, or not at all.

An inert Python script stands in for QEMU: it tries everything the code it would run could
try (read the user's files or the held-out tier, look for the harness's secrets, write
outside its scratch, reach the network, fork, map or store memory without end) and talks
on its serial line, standard input and output. The "secrets" and the "held-out tier" are
inert markers the tests plant. It needs the evaluation's sandbox runtime installed
(``npm ci`` in ``tools/srt``), Node 22 on the search path, and Linux: on macOS the
firmware tier refuses.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from physgate.evaluation.per_role.firmware import sandbox
from physgate.evaluation.per_role.firmware.loop import DeviceFaultError, PipeDevice, WallClock
from physgate.evaluation.per_role.firmware.sandbox import (
    RUNTIME_TASKS,
    EmulatorLimits,
    FirmwareTierRefusedError,
    runtime_pin,
    sandboxed,
    srt_settings,
)

pytestmark = pytest.mark.integration

linux_only = pytest.mark.skipif(
    sys.platform == "darwin", reason="the firmware tier refuses on macOS"
)

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
def through_the_runtime_s_proxy():
    import urllib.request
    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if not proxy:
        raise OSError("no proxy")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy}))
    opener.open("http://example.com/", timeout=5).read(16)
attempt("proxied", through_the_runtime_s_proxy)
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

MARKER = "import sys\nopen(sys.argv[1], 'w').write('ran')\n"
LIMITS = EmulatorLimits(wall_s=45.0, cpu_s=20, memory_bytes=1 << 30, tasks=32)


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


def _held_out(tmp_path: Path) -> tuple[str]:
    """An inert stand-in for the held-out tier, outside the user's home."""
    tier = tmp_path / "held-out"
    tier.mkdir(exist_ok=True)
    (tier / "item.json").write_text('{"inert": "a stand-in held-out item"}')
    assert not tier.resolve().is_relative_to(Path.home().resolve())
    return (str(tier),)


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


def _device(session: sandbox.SandboxedEmulator) -> PipeDevice:
    return PipeDevice(session.run.process, WallClock().now_ms)


@linux_only
def test_the_emulator_reads_writes_and_reaches_only_what_it_is_given(tmp_path: Path) -> None:
    import socket

    secret = Path.home() / f".physgate-test-secret-{os.getpid()}"
    secret.write_text("an inert stand-in for a secret the emulator must not read")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        scratch, readable, argv = _setup(tmp_path, PROBE)
        outside = tmp_path / "outside.txt"
        argv += [str(secret), str(outside), str(listener.getsockname()[1])]
        with sandboxed(
            argv,
            scratch=scratch,
            readable=(readable,),
            limits=LIMITS,
            held_out=_held_out(tmp_path),
        ) as session:
            device = _device(session)
            first = _lines(device, time.monotonic() + 30, 6)
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
    assert results["proxied"].startswith("denied")  # the runtime's proxy allows no host
    assert echo == ["ACT ECHO PING"]
    assert session.record["os_layer"] == "bubblewrap"


@linux_only
def test_a_held_out_tier_outside_home_is_withheld_from_the_emulator(tmp_path: Path) -> None:
    tier = _held_out(tmp_path)
    scratch, readable, argv = _setup(
        tmp_path,
        "import sys\n"
        "try:\n"
        "    open(sys.argv[1]).read(); print('HELD-OUT ALLOWED', flush=True)\n"
        "except OSError as exc:\n"
        "    print('HELD-OUT denied', type(exc).__name__, flush=True)\n",
    )
    with sandboxed(
        [*argv, str(Path(tier[0]) / "item.json")],
        scratch=scratch,
        readable=(readable,),
        limits=LIMITS,
        held_out=tier,
    ) as session:
        seen = _lines(_device(session), time.monotonic() + 20, 1)
    assert seen and seen[0].startswith("HELD-OUT denied")


@linux_only
def test_an_evaluation_run_that_names_no_held_out_tier_refuses(tmp_path: Path) -> None:
    assert inspect.signature(sandboxed).parameters["held_out"].default is inspect.Parameter.empty
    marker = tmp_path / "ran"
    scratch, readable, argv = _setup(tmp_path, MARKER)
    with (
        pytest.raises(FirmwareTierRefusedError, match="held-out"),
        sandboxed(
            [*argv, str(marker)], scratch=scratch, readable=(readable,), limits=LIMITS, held_out=()
        ),
    ):
        time.sleep(2)
    assert not marker.exists()


@linux_only
def test_the_emulator_sees_none_of_the_harness_s_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = f"inert-fake-secret-{os.getpid()}"
    monkeypatch.setenv("PHYSGATE_TEST_FAKE_SECRET", fake)
    scratch, readable, argv = _setup(
        tmp_path,
        "import json, os\n"
        "open('env.json', 'w').write(json.dumps(dict(os.environ)))\n"
        "print('DONE', flush=True)\n",
    )
    with sandboxed(
        argv, scratch=scratch, readable=(readable,), limits=LIMITS, held_out=_held_out(tmp_path)
    ) as session:
        _lines(_device(session), time.monotonic() + 20, 1)
    seen: dict[str, str] = json.loads((scratch / "env.json").read_text())
    assert "PHYSGATE_TEST_FAKE_SECRET" not in seen
    assert not [name for name, value in seen.items() if fake in value]
    harness_only = set(os.environ) - set(sandbox.emulator_environment(scratch))
    shell_s_own = {"PWD", "OLDPWD", "SHLVL", "_"}  # the shell that runs the emulator sets these
    reached = (harness_only - shell_s_own) & set(seen)
    assert not reached, f"variables of the harness's reached the emulator: {sorted(reached)}"
    assert seen["HOME"] == str(scratch / "home")


@linux_only
def test_the_emulator_s_address_space_is_limited(tmp_path: Path) -> None:
    scratch, readable, argv = _setup(
        tmp_path,
        "import mmap\n"
        "try:\n"
        "    mmap.mmap(-1, 3 << 29); print('MAP ALLOWED', flush=True)\n"  # 1.5 GiB, untouched
        "except OSError as exc:\n"
        "    print('MAP denied', type(exc).__name__, flush=True)\n",
    )
    limits = EmulatorLimits(wall_s=30.0, cpu_s=20, memory_bytes=512 << 20, tasks=16)
    with sandboxed(
        argv, scratch=scratch, readable=(readable,), limits=limits, held_out=_held_out(tmp_path)
    ) as session:
        seen = _lines(_device(session), time.monotonic() + 20, 1)
    assert seen and seen[0].startswith("MAP denied")


@linux_only
def test_memory_the_emulator_stores_in_its_sandbox_s_own_files_is_capped(tmp_path: Path) -> None:
    # Inside the sandbox the user's home is a memory-backed file system: what is written
    # there is memory that no address-space limit sees. The scope's memory cap does.
    target = Path.home() / f".physgate-test-tmpfs-{os.getpid()}"
    scratch, readable, argv = _setup(
        tmp_path,
        "import os, sys\n"
        "os.makedirs(sys.argv[1], exist_ok=True)\n"
        "block = b'x' * (1 << 20)\n"
        "for i in range(1024):\n"
        "    with open(os.path.join(sys.argv[1], f'f{i}'), 'wb') as f:\n"
        "        f.write(block)\n"
        "    if i % 32 == 31:\n"
        "        print('WROTE', i + 1, flush=True)\n"
        "print('WROTE ALL', flush=True)\n",
    )
    limits = EmulatorLimits(wall_s=60.0, cpu_s=50, memory_bytes=256 << 20, tasks=16)
    try:
        with sandboxed(
            [*argv, str(target)],
            scratch=scratch,
            readable=(readable,),
            limits=limits,
            held_out=_held_out(tmp_path),
        ) as session:
            seen = _lines(_device(session), time.monotonic() + 50, 40)
            session.run.kill_group()
        assert not target.exists(), "the sandbox wrote into the real home"
    finally:
        shutil.rmtree(target, ignore_errors=True)
    assert "WROTE ALL" not in seen
    written = max((int(line.split()[1]) for line in seen if line.startswith("WROTE ")), default=0)
    assert written < 1024
    assert session.record["memory_cap"].startswith("MemoryMax=")


@linux_only
def test_files_the_emulator_writes_into_its_scratch_are_capped(tmp_path: Path) -> None:
    scratch, readable, argv = _setup(
        tmp_path,
        "import time\n"
        "for i in range(2000):\n"
        "    open(f'f{i}', 'wb').write(b'x' * 65536)\n"
        "    if i % 50 == 49:\n"
        "        print('WROTE', i + 1, flush=True)\n"
        "        time.sleep(0.05)\n"
        "print('WROTE ALL', flush=True)\n"
        "time.sleep(30)\n",
    )
    limits = EmulatorLimits(
        wall_s=40.0,
        cpu_s=30,
        memory_bytes=1 << 30,
        tasks=16,
        scratch_bytes=8 << 20,
        scratch_files=200,
    )
    with sandboxed(
        argv, scratch=scratch, readable=(readable,), limits=limits, held_out=_held_out(tmp_path)
    ) as session:
        _lines(_device(session), time.monotonic() + 35, 100)
    assert len(list(scratch.glob("f*"))) < 400
    assert "scratch" in (session.record["infrastructure"] or "")
    assert session.record["scratch"]["files"] >= 1


@linux_only
def test_a_fork_bomb_is_held_to_the_process_cap(tmp_path: Path) -> None:
    scratch, readable, argv = _setup(tmp_path, FORK_BOMB)
    limits = EmulatorLimits(wall_s=20.0, cpu_s=20, memory_bytes=1 << 30, tasks=16)
    with sandboxed(
        argv, scratch=scratch, readable=(readable,), limits=limits, held_out=_held_out(tmp_path)
    ) as session:
        lines = _lines(_device(session), time.monotonic() + 15, 1)
        session.run.kill_group()
    count = int(lines[0].split()[1])
    assert count < 16 + RUNTIME_TASKS  # the emulator's allowance, above the runtime's own tasks
    assert (
        session.record["process_cap"]
        == f"TasksMax={16 + RUNTIME_TASKS} (16 above the runtime's {RUNTIME_TASKS})"
    )


def test_on_macos_the_firmware_tier_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On macOS for real; elsewhere as if on macOS. Either way the guest never runs.
    if sys.platform != "darwin":
        monkeypatch.setattr(sandbox, "_platform", lambda: "darwin")
    marker = tmp_path / "ran"
    scratch, readable, argv = _setup(tmp_path, MARKER)
    with (
        pytest.raises(FirmwareTierRefusedError, match="macOS"),
        sandboxed(
            [*argv, str(marker)],
            scratch=scratch,
            readable=(readable,),
            limits=LIMITS,
            held_out=_held_out(tmp_path),
        ),
    ):
        time.sleep(2)
    assert not marker.exists()


@linux_only
def test_where_the_os_layer_is_absent_the_firmware_tier_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.oslayer.probe import Absent

    monkeypatch.setattr(
        "physgate.evaluation.per_role.firmware.sandbox.judge_here",
        lambda **_k: Absent(reason="test: no sandbox", no_os_protection=False),
    )
    scratch, readable, argv = _setup(tmp_path, "print('ran', flush=True)\n")
    with (
        pytest.raises(FirmwareTierRefusedError, match="OS layer"),
        sandboxed(
            argv,
            scratch=scratch,
            readable=(readable,),
            limits=LIMITS,
            held_out=_held_out(tmp_path),
        ),
    ):
        pass


@linux_only
def test_the_emulator_s_own_cpu_limit_is_an_infrastructure_end(tmp_path: Path) -> None:
    scratch, readable, argv = _setup(tmp_path, "while True:\n    pass\n")
    limits = EmulatorLimits(wall_s=60.0, cpu_s=2, memory_bytes=1 << 30, tasks=16)
    began = time.monotonic()
    with sandboxed(
        argv, scratch=scratch, readable=(readable,), limits=limits, held_out=_held_out(tmp_path)
    ) as session:
        session.run.wait()
    assert time.monotonic() - began < 20  # the emulator's 2 s, not the runtime's wider bound
    assert "own limits" in (session.record["infrastructure"] or "")


@linux_only
def test_a_sandbox_that_never_starts_the_emulator_is_an_infrastructure_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = sandbox.srt_settings

    def malformed(*args: object, **kwargs: object) -> dict[str, object]:
        settings = real(*args, **kwargs)  # type: ignore[arg-type]
        del settings["network"]  # the runtime refuses to run on settings without one
        return settings

    monkeypatch.setattr(sandbox, "srt_settings", malformed)
    marker = tmp_path / "ran"
    scratch, readable, argv = _setup(tmp_path, MARKER)
    with sandboxed(
        [*argv, str(marker)],
        scratch=scratch,
        readable=(readable,),
        limits=LIMITS,
        held_out=_held_out(tmp_path),
    ) as session:
        session.run.wait()
    assert not marker.exists()
    assert "did not start" in (session.record["infrastructure"] or "")


@linux_only
def test_an_emulator_that_ends_on_its_own_is_the_answer_s_end(tmp_path: Path) -> None:
    scratch, readable, argv = _setup(
        tmp_path,
        "import sys\n"
        "sys.stderr.write('physgate-emulator-end forged 137\\n')\n"  # a forged status line
        "sys.exit(3)\n",
    )
    with sandboxed(
        argv, scratch=scratch, readable=(readable,), limits=LIMITS, held_out=_held_out(tmp_path)
    ) as session:
        session.run.wait()
    assert session.record["infrastructure"] is None
    assert session.record["emulator_status"] == 3


@linux_only
def test_a_status_line_the_emulator_writes_is_not_believed(tmp_path: Path) -> None:
    scratch, readable, argv = _setup(
        tmp_path,
        "import sys, time\n"
        "sys.stderr.write('physgate-emulator-end forged 137\\n'); sys.stderr.flush()\n"
        "print('READY', flush=True)\n"
        "time.sleep(30)\n",
    )
    with sandboxed(
        argv, scratch=scratch, readable=(readable,), limits=LIMITS, held_out=_held_out(tmp_path)
    ) as session:
        assert _lines(_device(session), time.monotonic() + 20, 1) == ["READY"]
        session.run.kill_group()  # the harness ends the run: the shell reports nothing
    assert session.record["emulator_status"] is None
    assert session.record["infrastructure"] is None


@linux_only
def test_the_runtime_s_pin_is_read_from_what_is_installed(tmp_path: Path) -> None:
    pin = runtime_pin(sandbox.SRT)
    assert pin["version"] == "0.0.79"
    assert len(pin["cli_sha256"]) == 64
    assert pin["integrity"].startswith("sha512-")
    scratch, readable, argv = _setup(tmp_path, "pass\n")
    with sandboxed(
        argv, scratch=scratch, readable=(readable,), limits=LIMITS, held_out=_held_out(tmp_path)
    ) as session:
        session.run.wait()
    assert session.record["sandbox_runtime"] == pin


def test_an_installed_runtime_that_is_not_the_locked_one_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    tools = tmp_path / "srt"
    package = tools / "node_modules" / "@anthropic-ai" / "sandbox-runtime"
    (package / "dist").mkdir(parents=True)
    cli = package / "dist" / "cli.js"
    cli.write_text("// an inert stand-in\n")
    monkeypatch.setattr(sandbox, "PINNED_CLI_SHA256", hashlib.sha256(cli.read_bytes()).hexdigest())
    (tools / "node_modules" / ".bin").mkdir()
    fake_srt = tools / "node_modules" / ".bin" / "srt"
    fake_srt.write_text("#!/bin/sh\nexit 1\n")
    entry = {"version": "0.0.79", "integrity": "sha512-inert"}
    lock = {"packages": {"node_modules/@anthropic-ai/sandbox-runtime": entry}}
    (tools / "package-lock.json").write_text(json.dumps(lock))
    (package / "package.json").write_text(json.dumps({"version": "0.0.79"}))
    assert runtime_pin(fake_srt)["version"] == "0.0.79"
    cli.write_text("// an inert stand-in, changed\n")
    with pytest.raises(FirmwareTierRefusedError, match="sha256"):
        runtime_pin(fake_srt)
    cli.write_text("// an inert stand-in\n")
    (package / "package.json").write_text(json.dumps({"version": "0.0.80"}))
    with pytest.raises(FirmwareTierRefusedError, match=r"0\.0\.80"):
        runtime_pin(fake_srt)
    (package / "package.json").write_text(json.dumps({"version": "0.0.80"}))
    entry["version"] = "0.0.80"
    (tools / "package-lock.json").write_text(json.dumps(lock))
    with pytest.raises(FirmwareTierRefusedError, match="pinned"):
        runtime_pin(fake_srt)


@linux_only
def test_the_harness_checkout_is_withheld_from_the_emulator(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    settings = srt_settings(scratch, (), ("/nonexistent/held-out",))
    assert os.path.realpath(sandbox.CHECKOUT) in settings["filesystem"]["denyRead"]
    assert "/nonexistent/held-out" in settings["filesystem"]["denyRead"]
