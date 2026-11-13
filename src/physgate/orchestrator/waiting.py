"""What the command line says of a run waiting for the account's usage limit.

Not yet implemented: the names the rows hold the command line to.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from physgate.orchestrator.replay import RunState

#: The exit status of ``run`` and ``resume`` for a run waiting for the account's usage limit,
#: halted on it or refused a resume before it may go on: try again after ``resume_after``.
EXIT_WAITING_FOR_LIMIT = 75
#: The step printed for a run halted on the account's usage limit, in place of ``halted``.
WAITING_FOR_LIMIT = "waiting_for_limit"


def printed_step(kind: str, state: RunState) -> tuple[dict[str, str | None], int]:
    """The step ``run`` and ``resume`` print for where the run stopped, and their exit status."""
    del state
    return {"step": kind}, 0 if kind == "done" else 1


def limit_wait(run_dir: Path, now: datetime, *, limit_reset: bool) -> dict[str, str] | None:
    """Why a resume of the run in ``run_dir`` is refused now, as printed; ``None`` if it goes on."""
    del run_dir, now, limit_reset
    return None
