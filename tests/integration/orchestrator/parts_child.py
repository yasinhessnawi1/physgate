"""Child process for the parts hold's kill test: one process of a run that asks about parts.

Modes, with the run directory first: ``open`` writes the run's opening and kills itself before
it lists a thing; ``drive`` runs the run to the step it ends at and prints what it found;
``drive-kill`` does the same but kills itself after the first decision it takes into the log.
Every kill is the signal no handler sees.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for where in (HERE.parents[1] / "unit" / "orchestrator", HERE.parents[1]):
    sys.path.insert(0, str(where))

import plan_hold_rig  # noqa: E402
from parts_rig import log_of, parts_items, rig, started  # noqa: E402
from plan_hold_rig import again  # noqa: E402

from physgate.orchestrator.events import Event  # noqa: E402
from physgate.orchestrator.loop import Loop  # noqa: E402


def _report(run_dir: Path, step: str) -> None:
    log = log_of(run_dir)
    kinds = [one["kind"] for one in log]
    taken = [one["item_id"] for one in log if one["kind"] == "decision_taken"]
    found = {
        "step": step,
        "items": [one.item_id for one in parts_items(run_dir)],
        "taken": taken,
        "dispatched": "stage_entered" in kinds,
    }
    print(json.dumps(found), flush=True)


def _drive_and_die(run_dir: Path) -> None:
    the_rig = rig(run_dir)
    loop: Loop = the_rig.open()
    plan_hold_rig.layer(loop)
    real = loop.record.emit

    def emit(event: Event) -> None:
        real(event)
        if event.kind == "decision_taken":
            os.kill(os.getpid(), signal.SIGKILL)

    loop.record.emit = emit  # type: ignore[method-assign]
    loop.run()


def main() -> None:
    run_dir, mode = Path(sys.argv[1]), sys.argv[2]
    if mode == "open":
        started(run_dir)
        os.kill(os.getpid(), signal.SIGKILL)
    elif mode == "drive":
        _report(run_dir, again(rig(run_dir)))
    elif mode == "drive-kill":
        _drive_and_die(run_dir)
    else:
        raise SystemExit(f"no mode {mode}")


if __name__ == "__main__":
    main()
