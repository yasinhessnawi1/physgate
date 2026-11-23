"""What the command line says of a run waiting for the account's usage limit.

A run halted on the limit prints its own step, ``waiting_for_limit``, in place of ``halted``,
with the kind of limit (``limit_type``: ``five_hour``, ``seven_day`` days later, or a kind the
stream named that is not known here; ``null`` where it named none), the reset as the stream gave
it, its instant where it was read, and ``resume_after``: the instant after which a resume goes
on. It exits :data:`EXIT_WAITING_FOR_LIMIT`. A resume asked before then is refused before
anything is stopped, written or started, with the same step and instant on standard error and
the same exit status, so a script can wait and try again. A run that ends escalated with a
person's sign-off owed (ARCH-130) names each such module and its latest item under
``sign_offs_owed``. A run started under ``wait_cycle: release_2`` that ends with subtasks that
never ran prints the step ``unrun``, with each such subtask under ``never_ran`` (why, and the
readers that merged without it), and exits 1. Every other step prints and exits as before.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from physgate.orchestrator.closing_wait import closing_waits
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.replay import RunState, replay
from physgate.orchestrator.usage_limit import resume_after, resume_refusal
from physgate.orchestrator.wait_cycle import never_ran

#: The exit status of ``run`` and ``resume`` for a run waiting for the account's usage limit,
#: halted on it or refused a resume before it may go on: try again after ``resume_after``.
EXIT_WAITING_FOR_LIMIT = 75
#: The step printed for a run halted on the account's usage limit, in place of ``halted``.
WAITING_FOR_LIMIT = "waiting_for_limit"


def printed_step(kind: str, state: RunState) -> tuple[dict[str, object], int]:
    """The step ``run`` and ``resume`` print for where the run stopped, and their exit status."""
    halted = state.halted
    if kind == "halted" and halted is not None and halted.reason == "usage_limit":
        limit = halted.usage_limit
        printed: dict[str, object] = {
            "step": WAITING_FOR_LIMIT,
            "limit_type": limit.limit_type if limit is not None else None,
            "resets": limit.resets if limit is not None else None,
            "resets_at": limit.resets_at if limit is not None else None,
            "resume_after": resume_after(halted.ts, limit),
        }
        return printed, EXIT_WAITING_FOR_LIMIT
    printed = {"step": kind}
    # Sizing's closing pass held while a domain module has not settled, with the modules it
    # waits for; left out where none is held, so every other step prints as it always has.
    printed |= closing_waits(state)
    if kind == "unrun":
        # A run that ended with subtasks that never ran says which, why, and what ran without them.
        printed["never_ran"] = never_ran(state)
    owed = state.sign_offs_open() if kind == "escalated" else []
    if owed:
        # Each module not complete for a person's sign-off, and the item that asks for it.
        printed["sign_offs_owed"] = ", ".join(
            f"{module} (item {state.sign_offs_of(module)[-1].item_id})"
            if state.sign_offs_of(module)
            else module
            for module in owed
        )
    return printed, 0 if kind == "done" else 1


def limit_wait(run_dir: Path, now: datetime, *, limit_reset: bool) -> dict[str, str] | None:
    """Why a resume of the run in ``run_dir`` is refused now, as printed; ``None`` if it goes on.

    Read from the run's log alone. A log that is missing or cannot be read is no wait: the
    resume goes on to find it as it always has.
    """
    log = run_dir / "events.jsonl"
    try:
        halted = replay(read_events(log)).halted if log.is_file() else None
    except (OrchestratorError, ValueError):
        return None
    if halted is None or halted.reason != "usage_limit":
        return None
    why = resume_refusal(halted.ts, halted.usage_limit, now, limit_reset=limit_reset)
    if why is None:
        return None
    return {
        "error": why,
        "step": WAITING_FOR_LIMIT,
        "resume_after": resume_after(halted.ts, halted.usage_limit),
    }
