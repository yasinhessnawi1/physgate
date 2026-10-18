"""The emulator inside the OS layer: the sandbox runtime the role sessions' shells run under.

QEMU runs code a model wrote, so it is held like a role session's shell. It runs through
the sandbox runtime (``srt``, pinned in ``tools/srt`` to the version Claude Code 2.1.301
bundles), with settings generated from the OS layer's own policy (:mod:`physgate.oslayer.policy`)
for a raw-agent session whose worktree is the answer's scratch directory:

- **environment**: built from nothing (a search path, a home in the scratch, a fixed
  locale and time zone, and where the user's systemd manager listens); nothing of the
  harness's, its credentials among it, reaches the emulator;
- **writes** only to the scratch directory, which is watched: past its bound in bytes or
  entries the run is ended, as the answer's limit. The harness writes nothing there, and
  reads it only through descriptors opened without following a link or waiting on a FIFO
  (:func:`open_directory`): the scratch is the guest's to plant traps in;
- **reads**: never the user's home, the held-out tier (which every run must name), the
  harness checkout or anything the policy withholds, except the scratch directory and the
  emulator's own files, named;
- **network**: none at all. The serial line is the emulator's standard input and output
  (``-serial stdio``), so no port is needed, loopback included; no monitor, no debug stub;
- **limits**, set by the shell that then runs the emulator (``ulimit``): CPU seconds, file
  size, core size and address space;
- **processes and memory**: a systemd user scope with ``TasksMax`` and ``MemoryMax``,
  which the user's manager must delegate, or the firmware tier refuses;
- **the whole process group** is killed from the harness's side at the wall clock and
  however the run ends (:mod:`.guard`).

The firmware tier runs on Linux only. On macOS a descendant that leaves the process group
outlives the group's kill, and no address-space limit is applied, so the tier refuses
there rather than record limits the platform does not hold. Where the OS layer is absent
it refuses too: these are evaluation runs.

Only the machine's own signals can make a run the machine's (``infrastructure``, retried
under the evaluation's rules, never the answer's fail): before the emulator starts, the
same scope and sandbox run a check that contains no guest, and if the check does not exit
cleanly the run is refused as :class:`EmulatorInfrastructureError`. Once the guest runs,
nothing it can print, exit with or do to itself is read as the machine's: however it
ends, including on one of its own limits, the end is the answer's.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shlex
import shutil
import stat
import sys
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.firmware.guard import MAX_OUTPUT_BYTES, GuardedRun, guarded
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.orchestrator.invocation import claude_binary, session_search_path
from physgate.oslayer.policy import sandbox_policy
from physgate.oslayer.probe import Absent, judge_here

#: The harness checkout, withheld from the emulator.
CHECKOUT = Path(__file__).resolve().parents[5]
#: The pinned sandbox runtime: installed by ``npm ci`` in ``tools/srt``.
SRT = CHECKOUT / "tools" / "srt" / "node_modules" / ".bin" / "srt"
RUNTIME_PACKAGE = "@anthropic-ai/sandbox-runtime"
#: The version Claude Code 2.1.301 bundles. Fingerprinted from the binary's strings: of the
#: string literals in the runtime's ``dist/`` for 0.0.77 to 0.0.80, both literals found only
#: in 0.0.79 are in the 2.1.301 binary, and 2 of the 177 new in 0.0.80 are (both generic).
PINNED_RUNTIME = "0.0.79"
#: The sha256 of 0.0.79's ``dist/cli.js``, as the registry's tarball holds it.
PINNED_CLI_SHA256 = "3f5544de20b8a4bf9937b1ceaa59e18ca05758f0d6a18ee76e8273585e78817a"
#: Tasks the sandbox runtime itself runs in the capped scope (its runtime's threads, the
#: sandbox, its proxies): 21 measured on Oracle (aarch64, 0.0.79), rounded up. The emulator's
#: own allowance is added on top.
RUNTIME_TASKS = 32
#: Memory the sandbox runtime itself takes in the capped scope, above the emulator's own.
RUNTIME_MEMORY = 256 * 1024 * 1024
#: The version of the Claude Code binary whose OS layer the emulator is held to.
CLAUDE_VERSION = "2.1.301"
SYSTEM_PATH = ("/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
#: The most directories the scratch's walk holds open at once; deeper is past the bound.
MAX_OPEN_DIRECTORIES = 256
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class FirmwareTierRefusedError(PerRoleError):
    """The firmware tier cannot run here as an evaluation run must."""


class EmulatorInfrastructureError(PerRoleError):
    """The sandbox failed its check before the emulator ran: the machine's, not the answer's."""


@dataclass(frozen=True)
class EmulatorLimits:
    """Every bound on the emulator's process, and on what it may leave in its scratch."""

    wall_s: float
    cpu_s: int
    memory_bytes: int
    tasks: int
    scratch_bytes: int = 256 * 1024 * 1024
    scratch_files: int = 4096


@dataclass
class SandboxedEmulator:
    """A running emulator, its guard, and the record of how it was held and how it ended.

    The record's ending (``ended_by``, ``limit``, ``scratch``, and ``infrastructure``,
    which is always ``None`` for a run whose guest started) is filled in once the block
    has ended.
    """

    run: GuardedRun
    record: dict[str, Any] = field(default_factory=dict)


def _platform() -> str:
    return sys.platform


def emulator_environment(scratch: Path) -> dict[str, str]:
    """The emulator's whole environment, built from nothing: never the harness's.

    The search path holds the system's directories and those of the tools the sandbox
    runtime needs (Node, bubblewrap, socat, ripgrep). The two systemd locations are where
    the user's manager listens, for the scope that caps the emulator; they are paths, not
    credentials, and the sandbox reaches no socket.
    """
    tools = (shutil.which(name) for name in ("node", "bwrap", "socat", "rg"))
    found = [str(Path(tool).parent) for tool in tools if tool is not None]
    uid = os.getuid()
    return {
        "PATH": ":".join(dict.fromkeys([*found, *SYSTEM_PATH])),
        "HOME": str(scratch / "home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "XDG_RUNTIME_DIR": f"/run/user/{uid}",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
    }


def srt_settings(
    scratch: Path, readable: Sequence[Path], held_out: Sequence[str]
) -> dict[str, Any]:
    """The sandbox runtime's settings, generated from the OS layer's policy.

    The policy is asked for a raw-agent session whose worktree is ``scratch``, offline; its
    read and write denials are kept whole, the user's home and the harness checkout are
    denied too, and only the scratch directory and ``readable`` (the emulator's own files)
    are opened again.
    """
    home = Path.home()
    request = InstallRequest(
        profile="baseline",
        role=None,
        worktree=str(scratch),
        own_branch=None,
        store_root=None,
        state_dir=str(scratch.parent / f"{scratch.name}.state"),
        target_dir=str(scratch.parent / f"{scratch.name}.session"),
        claude_config_dir=str(scratch.parent / f"{scratch.name}.config"),
        user_home=str(scratch / "home"),
        token_ceiling=1,
        held_out=tuple(held_out),
    )
    config = build_config(request, current_installation())
    policy = sandbox_policy(
        config, home=str(scratch / "home"), temp_dir=str(scratch / "tmp"), network="none"
    )
    filesystem = policy.settings["sandbox"]["filesystem"]
    # The runtime's own package (its seccomp helper among it) must stay readable inside the
    # sandbox it builds, wherever it is installed.
    runtime = SRT.parent.parent / "@anthropic-ai" / "sandbox-runtime"
    opened = sorted({str(scratch), str(runtime.resolve()), *(str(p) for p in readable)})
    withheld = {str(home), os.path.realpath(home), str(CHECKOUT), os.path.realpath(CHECKOUT)}
    return {
        "filesystem": {
            "denyRead": sorted({*filesystem["denyRead"], *withheld}),
            "allowRead": opened,
            "allowWrite": [str(scratch)],
            "denyWrite": filesystem["denyWrite"],
        },
        "network": {"allowedDomains": [], "deniedDomains": [], "strictAllowlist": True},
    }


def runtime_pin(srt: Path) -> dict[str, str]:
    """The sandbox runtime as installed: its version, the lockfile's integrity, its CLI's hash.

    Read from disk, never assumed: the installed package must be the version the lockfile
    locks, which must be the pinned one, and its CLI must be the pinned file.

    Raises:
        FirmwareTierRefusedError: the pin cannot be read, or what is installed is not it.
    """
    modules = srt.parent.parent
    package = modules / "@anthropic-ai" / "sandbox-runtime"
    try:
        installed = str(json.loads((package / "package.json").read_text())["version"])
        lock = json.loads((modules.parent / "package-lock.json").read_text())
        locked = lock["packages"][f"node_modules/{RUNTIME_PACKAGE}"]
        cli = hashlib.sha256((package / "dist" / "cli.js").read_bytes()).hexdigest()
        version, integrity = str(locked["version"]), str(locked["integrity"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        msg = f"the sandbox runtime's pin cannot be read: {exc!r}"
        raise FirmwareTierRefusedError(msg) from exc
    if version != PINNED_RUNTIME:
        msg = f"the lockfile locks the sandbox runtime {version}, not the pinned {PINNED_RUNTIME}"
        raise FirmwareTierRefusedError(msg)
    if installed != version:
        msg = f"the installed sandbox runtime is {installed}, the lockfile's is {version}"
        raise FirmwareTierRefusedError(msg)
    if cli != PINNED_CLI_SHA256:
        msg = f"the installed sandbox runtime's CLI has sha256 {cli}, not the pinned file's"
        raise FirmwareTierRefusedError(msg)
    return {
        "package": RUNTIME_PACKAGE,
        "version": installed,
        "integrity": integrity,
        "cli_sha256": cli,
    }


def _limited(argv: Sequence[str], limits: EmulatorLimits) -> str:
    """A shell line that sets the emulator's limits, then becomes the emulator."""
    parts = [
        f"ulimit -t {limits.cpu_s}",
        f"ulimit -f {MAX_OUTPUT_BYTES // 1024}",
        "ulimit -c 0",
        f"ulimit -v {limits.memory_bytes // 1024}",
    ]
    return "; ".join(parts) + "; exec " + shlex.join(argv)


def _process_cap(limits: EmulatorLimits) -> tuple[list[str], str, str]:
    """The scope that caps processes and memory, and how the run records each cap.

    Raises:
        FirmwareTierRefusedError: the user's manager cannot hold a scope to these caps.
    """
    run = shutil.which("systemd-run")
    controllers = Path(
        f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/cgroup.controllers"
    )
    try:
        delegated = {"pids", "memory"} <= set(controllers.read_text().split())
    except OSError:
        delegated = False
    if run is None or not delegated:
        msg = (
            "the user's systemd manager does not delegate a process and memory cap; "
            "the firmware tier refuses"
        )
        raise FirmwareTierRefusedError(msg)
    total = RUNTIME_TASKS + limits.tasks
    memory = RUNTIME_MEMORY + limits.memory_bytes
    wrapper = [
        run,
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        "-p",
        f"TasksMax={total}",
        "-p",
        f"MemoryMax={memory}",
        "-p",
        "MemorySwapMax=0",
        "--",
    ]
    tasks = f"TasksMax={total} ({limits.tasks} above the runtime's {RUNTIME_TASKS})"
    return wrapper, tasks, f"MemoryMax={memory} (the runtime's {RUNTIME_MEMORY} included)"


def open_directory(name: str, dir_fd: int | None = None) -> int:
    """A descriptor on the directory ``name`` (under ``dir_fd``), never through a link.

    The open neither follows a link nor waits on a FIFO, and what it opened is checked to be
    a directory before it is used.

    Raises:
        OSError: ``name`` is a link, a FIFO, a file or anything but a directory.
    """
    fd = os.open(name, _DIRECTORY, dir_fd=dir_fd)
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        msg = f"{name!r} is not a directory"
        raise NotADirectoryError(msg)
    return fd


def scratch_usage(scratch: Path, most_files: int) -> tuple[int, int]:
    """The bytes on disk and the entries under ``scratch``, read through checked descriptors.

    Nothing is followed and nothing is opened but directories (:func:`open_directory`).
    Counting stops past ``most_files``; a tree the walk cannot hold or open (too deep, or a
    directory it may not read) counts as past the bound.
    """
    over = (0, most_files + 1)
    try:
        root = open_directory(str(scratch))
    except OSError:
        return over
    used, entries, stack = 0, 0, [root]
    try:
        while stack:
            fd = stack.pop()
            try:
                for entry in os.scandir(fd):
                    entries += 1
                    if entries > most_files:
                        return used, entries
                    try:
                        info = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    used += info.st_blocks * 512
                    if stat.S_ISDIR(info.st_mode):
                        if len(stack) >= MAX_OPEN_DIRECTORIES:
                            return over
                        try:
                            stack.append(open_directory(entry.name, fd))
                        except (FileNotFoundError, NotADirectoryError):
                            continue  # replaced since it was listed: not followed
            except OSError:
                return over
            finally:
                os.close(fd)
    finally:
        for fd in stack:
            os.close(fd)
    return used, entries


def _watch_scratch(
    scratch: Path, limits: EmulatorLimits, run: GuardedRun, stop: threading.Event, over: list[str]
) -> None:
    while not stop.wait(0.2):
        used, entries = scratch_usage(scratch, limits.scratch_files)
        if used > limits.scratch_bytes or entries > limits.scratch_files:
            over.append(
                f"the emulator passed its scratch bound: {used} bytes in {entries} entries, "
                f"at most {limits.scratch_bytes} bytes in {limits.scratch_files}"
            )
            run.kill_group()
            return


def _check(command: Sequence[str], env: dict[str, str], scratch: Path) -> None:
    """Run the scope and sandbox with no guest in them; refuse the run unless they work.

    Raises:
        EmulatorInfrastructureError: the check did not exit cleanly.
    """
    output = scratch.parent / f"{scratch.name}.check.stderr"
    with guarded(
        command, wall_s=60.0, cpu_s=60, memory_bytes=None, output=output, env=env, cwd=scratch
    ) as check:
        ended = check.wait()
    if ended == "exited" and check.process.returncode == 0:
        return
    try:
        said = output.read_bytes()[-400:].decode("utf-8", errors="replace").strip()
    except OSError:
        said = ""
    msg = (
        f"the sandbox failed its check before the emulator ran ({ended}, "
        f"status {check.process.returncode}): {said!r}"
    )
    raise EmulatorInfrastructureError(msg)


def _ending(run: GuardedRun, over: list[str]) -> dict[str, Any]:
    """How the run ended, from the harness's own records: the answer's end, however it came."""
    limit = over[0] if over else None
    if limit is None and run.ended_by == "limit":
        limit = "the sandbox passed the guard's outer bounds"
    return {"ended_by": run.ended_by, "limit": limit, "infrastructure": None}


@contextlib.contextmanager
def sandboxed(
    argv: Sequence[str],
    *,
    scratch: Path,
    readable: Sequence[Path],
    limits: EmulatorLimits,
    held_out: Sequence[str],
    srt: Path = SRT,
) -> Iterator[SandboxedEmulator]:
    """Run the emulator ``argv`` in ``scratch`` inside the OS layer; its serial line on its pipes.

    ``held_out`` names the held-out tier's roots, withheld from the emulator; an evaluation
    run always has one.

    Raises:
        FirmwareTierRefusedError: this is macOS, no held-out tier is named, or the OS
            layer, the pinned sandbox runtime or the scope's caps are not available here.
        EmulatorInfrastructureError: the scope and sandbox failed their check, with no
            guest in them, before the emulator ran.
    """
    if _platform() == "darwin":
        msg = (
            "the firmware tier runs on Linux only: on macOS a descendant that leaves the "
            "process group outlives its kill, and no address-space limit is applied"
        )
        raise FirmwareTierRefusedError(msg)
    if not held_out:
        msg = "an evaluation run names the held-out tier to withhold from the emulator"
        raise FirmwareTierRefusedError(msg)
    layer = judge_here(claude_version=CLAUDE_VERSION, search_path=session_search_path(_binary()))
    if isinstance(layer, Absent):
        msg = f"the OS layer is absent here ({layer.reason}); the firmware tier refuses"
        raise FirmwareTierRefusedError(msg)
    if not srt.is_file() or shutil.which("node") is None:
        msg = f"the sandbox runtime is not installed at {srt} (npm ci in tools/srt), or no node"
        raise FirmwareTierRefusedError(msg)
    pin = runtime_pin(srt)
    wrapper, cap, memory_cap = _process_cap(limits)
    settings = scratch.parent / f"{scratch.name}.srt-settings.json"
    settings.write_text(json.dumps(srt_settings(scratch, readable, held_out), indent=1))
    env = emulator_environment(scratch)
    sandbox_command = [*wrapper, str(srt), "--settings", str(settings), "-c"]
    _check([*sandbox_command, "exit 0"], env, scratch)
    command = [*sandbox_command, _limited(argv, limits)]
    record: dict[str, Any] = {
        "os_layer": layer.mechanism,
        "process_cap": cap,
        "memory_cap": memory_cap,
        "sandbox_runtime": pin,
        "limits": {
            "wall_s": limits.wall_s,
            "cpu_s": limits.cpu_s,
            "memory_bytes": limits.memory_bytes,
            "scratch_bytes": limits.scratch_bytes,
            "scratch_files": limits.scratch_files,
        },
    }
    output = scratch.parent / f"{scratch.name}.stderr"
    stop = threading.Event()
    over: list[str] = []
    session: SandboxedEmulator | None = None
    watcher: threading.Thread | None = None
    try:
        # The outer limits bound the sandbox runtime itself; the emulator's own are set by
        # the shell that runs it, inside the sandbox.
        with guarded(
            command,
            wall_s=limits.wall_s,
            cpu_s=limits.cpu_s + 30,
            memory_bytes=None,
            output=output,
            env=env,
            pipes=True,
            cwd=scratch,
        ) as run:
            session = SandboxedEmulator(run=run, record=record)
            watcher = threading.Thread(
                target=_watch_scratch, args=(scratch, limits, run, stop, over), daemon=True
            )
            watcher.start()
            yield session
    finally:
        stop.set()
        if watcher is not None:
            watcher.join(timeout=5.0)
        if session is not None:
            record.update(_ending(session.run, over))
            used, entries = scratch_usage(scratch, limits.scratch_files)
            record["scratch"] = {"bytes": used, "files": entries}


def _binary() -> str:
    try:
        return claude_binary()
    except Exception:  # noqa: BLE001 - only the search path's shape is needed here
        return "/usr/bin/true"


__all__ = [
    "EmulatorInfrastructureError",
    "EmulatorLimits",
    "FirmwareTierRefusedError",
    "SandboxedEmulator",
    "emulator_environment",
    "open_directory",
    "runtime_pin",
    "sandboxed",
    "scratch_usage",
    "srt_settings",
]
