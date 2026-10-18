"""The emulator's process, bounded from the harness's side: it cannot outrun its limits.

QEMU runs the firmware under test, so its process is as adversarial as the firmware. It is
started as the leader of a process group of its own, with resource limits set before it
runs anything: CPU seconds, the size of any file it writes (its output is a file of
bounded size), and, where the kernel enforces it, its address space. A thread of the
harness's, on the harness's clock, kills the whole group at the wall-clock bound; the group
is killed again however the run ends. None of this asks the process to cooperate.
"""

from __future__ import annotations

import contextlib
import os
import resource
import signal
import subprocess
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal

#: The most the process may write to its output file.
MAX_OUTPUT_BYTES = 1024 * 1024

Ending = Literal["exited", "wall_clock", "limit"]


class GuardedRun:
    """A bounded process: how it ended, once it has, judged from the harness's side."""

    def __init__(self, process: subprocess.Popen[bytes], *, output: Path, cpu_s: int, memory: bool):
        """Watch ``process``, the leader of its own group."""
        self.process = process
        self.ended_by: Ending | None = None
        self._output, self._cpu_s, self._memory = output, cpu_s, memory
        self._deadline_hit = threading.Event()

    def kill_group(self) -> None:
        """Kill the process's whole group, whatever it is doing."""
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.process.pid, signal.SIGKILL)

    def wait(self) -> Ending:
        """Wait for the process to end, and say what ended it.

        A limit is read from what the harness can see, never from what the process says: the
        signal that ended it, the CPU time the kernel charged it, the size of its output
        file, and, with a memory limit set, any failed exit.
        """
        if self.ended_by is not None:
            return self.ended_by
        try:
            _, status, usage = os.wait4(self.process.pid, 0)
            self.process.returncode = os.waitstatus_to_exitcode(status)
            cpu = usage.ru_utime + usage.ru_stime
        except ChildProcessError:
            self.process.wait()
            cpu = 0.0
        code = self.process.returncode
        limited = (
            (code < 0 and -code in (signal.SIGXCPU, signal.SIGXFSZ))
            or cpu >= self._cpu_s - 0.05
            or (self._output.exists() and self._output.stat().st_size >= MAX_OUTPUT_BYTES)
            or (self._memory and code != 0)
        )
        if self._deadline_hit.is_set():
            self.ended_by = "wall_clock"
        elif limited:
            self.ended_by = "limit"
        else:
            self.ended_by = "exited"
        return self.ended_by


def _limits(cpu_s: int, memory_bytes: int | None) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if memory_bytes is not None:
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


@contextlib.contextmanager
def guarded(
    argv: Sequence[str],
    *,
    wall_s: float,
    cpu_s: int,
    memory_bytes: int | None,
    output: Path,
) -> Iterator[GuardedRun]:
    """Run ``argv`` bounded on every side; its whole group is killed when the block ends."""
    with output.open("wb") as out:
        process = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=lambda: _limits(cpu_s, memory_bytes),  # noqa: PLW1509 - limits must precede the program
        )
    run = GuardedRun(process, output=output, cpu_s=cpu_s, memory=memory_bytes is not None)

    def watchdog() -> None:
        deadline = time.monotonic() + wall_s
        while process.poll() is None:
            if time.monotonic() >= deadline:
                run._deadline_hit.set()  # noqa: SLF001 - the run's own watchdog
                run.kill_group()
                return
            time.sleep(0.05)

    thread = threading.Thread(target=watchdog, daemon=True)
    thread.start()
    try:
        yield run
    finally:
        run.kill_group()
        run.wait()
        thread.join(timeout=1.0)
