"""The emulator inside the OS layer: the sandbox runtime the role sessions' shells run under.

QEMU runs code a model wrote, so it is held like a role session's shell. It runs through
the sandbox runtime (``srt``, pinned in ``tools/srt`` to the version Claude Code 2.1.301
bundles), with settings generated from the OS layer's own policy (:mod:`physgate.oslayer.policy`)
for a raw-agent session whose worktree is the answer's scratch directory:

- **writes** only to the scratch directory;
- **reads**: never the user's home, the held-out tier, the harness checkout or anything the
  policy withholds, except the scratch directory and the emulator's own files, named;
- **network**: none at all. The serial line is the emulator's standard input and output
  (``-serial stdio``), so no port is needed, loopback included; no monitor, no debug stub;
- **limits**, set by the shell that then becomes the emulator (``ulimit`` before ``exec``):
  CPU seconds, file size, core size and, where the kernel enforces it, address space;
- **processes**: on Linux, a systemd user scope with ``TasksMax``, where the user's
  manager delegates the pids controller, and otherwise the firmware tier refuses; on macOS
  there is no such cap, and the run records that it ran without one;
- **the whole process group** is killed from the harness's side at the wall clock and
  however the run ends (:mod:`.guard`).

Where the OS layer is absent the firmware tier refuses: these are evaluation runs.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import sys
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

#: The pinned sandbox runtime: installed by ``npm ci`` in ``tools/srt``.
SRT = Path(__file__).resolve().parents[5] / "tools" / "srt" / "node_modules" / ".bin" / "srt"
#: The version of the Claude Code binary whose OS layer the emulator is held to.
CLAUDE_VERSION = "2.1.301"


class FirmwareTierRefusedError(PerRoleError):
    """The firmware tier cannot run here as an evaluation run must."""


@dataclass(frozen=True)
class EmulatorLimits:
    """Every bound on the emulator's process."""

    wall_s: float
    cpu_s: int
    memory_bytes: int | None
    tasks: int


@dataclass
class SandboxedEmulator:
    """A running emulator, its guard, and the record of how it was held."""

    run: GuardedRun
    record: dict[str, Any] = field(default_factory=dict)


def srt_settings(
    scratch: Path, readable: Sequence[Path], held_out: Sequence[str]
) -> dict[str, Any]:
    """The sandbox runtime's settings, generated from the OS layer's policy.

    The policy is asked for a raw-agent session whose worktree is ``scratch``, offline; its
    read and write denials are kept whole, the user's home is denied too, and only the
    scratch directory and ``readable`` (the emulator's own files) are opened again.
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
    opened = sorted({str(scratch), *(str(p) for p in readable)})
    return {
        "filesystem": {
            "denyRead": sorted({*filesystem["denyRead"], str(home), os.path.realpath(home)}),
            "allowRead": opened,
            "allowWrite": [str(scratch)],
            "denyWrite": filesystem["denyWrite"],
        },
        "network": {"allowedDomains": [], "deniedDomains": [], "strictAllowlist": True},
    }


def _limited(argv: Sequence[str], limits: EmulatorLimits) -> str:
    """A shell line that sets the emulator's limits, then becomes the emulator."""
    parts = [
        f"ulimit -t {limits.cpu_s}",
        f"ulimit -f {MAX_OUTPUT_BYTES // 1024}",
        "ulimit -c 0",
    ]
    if limits.memory_bytes is not None and sys.platform != "darwin":
        parts.append(f"ulimit -v {limits.memory_bytes // 1024}")
    return "; ".join(parts) + "; exec " + shlex.join(argv)


def _process_cap(limits: EmulatorLimits) -> tuple[list[str], str]:
    """The wrapper that caps the number of processes, and how the run records it.

    Raises:
        FirmwareTierRefusedError: on Linux, the user's manager cannot hold a scope to a cap.
    """
    if sys.platform == "darwin":
        return [], "none (macOS)"
    run = shutil.which("systemd-run")
    controllers = Path(
        f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/cgroup.controllers"
    )
    try:
        delegated = "pids" in controllers.read_text().split()
    except OSError:
        delegated = False
    if run is None or not delegated:
        msg = (
            "the user's systemd manager does not delegate a process cap; the firmware tier refuses"
        )
        raise FirmwareTierRefusedError(msg)
    wrapper = [
        run,
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        "-p",
        f"TasksMax={limits.tasks}",
        "--",
    ]
    return wrapper, f"TasksMax={limits.tasks}"


@contextlib.contextmanager
def sandboxed(
    argv: Sequence[str],
    *,
    scratch: Path,
    readable: Sequence[Path],
    limits: EmulatorLimits,
    held_out: Sequence[str] = (),
    srt: Path = SRT,
) -> Iterator[SandboxedEmulator]:
    """Run the emulator ``argv`` in ``scratch`` inside the OS layer; its serial line on its pipes.

    Raises:
        FirmwareTierRefusedError: the OS layer, the sandbox runtime or the process cap is
            not available here.
    """
    layer = judge_here(claude_version=CLAUDE_VERSION, search_path=session_search_path(_binary()))
    if isinstance(layer, Absent):
        msg = f"the OS layer is absent here ({layer.reason}); the firmware tier refuses"
        raise FirmwareTierRefusedError(msg)
    if not srt.is_file() or shutil.which("node") is None:
        msg = f"the sandbox runtime is not installed at {srt} (npm ci in tools/srt), or no node"
        raise FirmwareTierRefusedError(msg)
    wrapper, cap = _process_cap(limits)
    settings = scratch.parent / f"{scratch.name}.srt-settings.json"
    settings.write_text(json.dumps(srt_settings(scratch, readable, held_out), indent=1))
    command = [*wrapper, str(srt), "--settings", str(settings), "-c", _limited(argv, limits)]
    record = {
        "os_layer": layer.mechanism,
        "process_cap": cap,
        "sandbox_runtime": "@anthropic-ai/sandbox-runtime 0.0.79",
        "limits": {
            "wall_s": limits.wall_s,
            "cpu_s": limits.cpu_s,
            "memory_bytes": limits.memory_bytes,
        },
    }
    output = scratch.parent / f"{scratch.name}.stderr"
    # The outer limits bound the sandbox runtime itself; the emulator's own are set by the
    # shell that becomes it, inside the sandbox.
    with guarded(
        command,
        wall_s=limits.wall_s,
        cpu_s=limits.cpu_s + 30,
        memory_bytes=None,
        output=output,
        pipes=True,
        cwd=scratch,
    ) as run:
        yield SandboxedEmulator(run=run, record=record)


def _binary() -> str:
    try:
        return claude_binary()
    except Exception:  # noqa: BLE001 - only the search path's shape is needed here
        return "/usr/bin/true"


__all__ = [
    "EmulatorLimits",
    "FirmwareTierRefusedError",
    "SandboxedEmulator",
    "sandboxed",
    "srt_settings",
]
