"""A run stopped by a signal leaves no session's credential file behind (not yet implemented)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def track(process: subprocess.Popen[bytes]) -> None:
    """Not yet implemented."""
    del process


@contextmanager
def on_stop_signals() -> Iterator[None]:
    """Not yet implemented."""
    yield


def running_session_ids() -> frozenset[str]:
    """Not yet implemented."""
    return frozenset()


def remove_left_credentials(run_dir: Path) -> tuple[str, ...]:
    """Not yet implemented."""
    del run_dir
    return ()
