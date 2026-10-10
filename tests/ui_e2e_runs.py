"""Build the runs the operator UI's browser tests read, under one root, and print that root.

Three runs made by the real loop with stand-in sessions and no model: gated on, observed and
clean (see ``ui_rig.real_runs``). Three more are the physics gate's three-mode plan, rebuilt
with the real gate in ``on``, ``observe`` and ``off`` (see ``ui_three_mode_rig``), so the gate's
own records, unchecked ones and a pass over nothing among them, reach the browser. One more,
``run-refused``, is a copy of the clean run whose ledger ends in a line no writer of this
package could have written, so the server refuses its ledger and the browser tests see the error
state render. Five more are copies of one run whose first subtask the loop escalated, for the
Queue view's tests (see ``QUEUE_RUNS``). The browser tests start ``physgate ui`` over the root
this prints, so what they check is the real server reading real records.

Usage: ``uv run python tests/ui_e2e_runs.py <directory>``. The directory is emptied first.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from ui_rig import escalated_run, real_runs
from ui_three_mode_rig import cut_after_first_gate_stage, three_mode_runs, two_domain_run

#: The escalated runs the Queue view's browser tests use, one per test that decides, so no test
#: depends on another's decision: shown and screenshot only; approved; decided on a view that
#: went stale; decided while a session's window is open; and the target of a forged request.
QUEUE_RUNS = (
    "run-esc-view",
    "run-esc-approve",
    "run-esc-stale",
    "run-esc-window",
    "run-esc-forged",
)


def escalated(out: Path, runs: Path) -> None:
    """One run the real loop escalated, copied once per queue test; the window run's log is cut."""
    made = escalated_run(out, "run-esc")
    for name in QUEUE_RUNS:
        shutil.copytree(
            made, runs / name, symlinks=True, ignore=shutil.ignore_patterns("worktrees")
        )
    shutil.rmtree(made)
    window = runs / "run-esc-window" / "events.jsonl"
    lines = window.read_bytes().splitlines(keepends=True)
    spawned = max(
        i
        for i, raw in enumerate(lines)
        if json.loads(raw).get("kind") == "stage_entered"
        and json.loads(raw).get("decisions_bytes") is not None
    )
    window.write_bytes(b"".join(lines[: spawned + 1]))


def main(argv: list[str]) -> int:
    """Build the runs under ``argv[1]`` and print the root that holds them."""
    out = Path(argv[1])
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    runs = real_runs(out)
    three_mode_runs(out, runs)
    two_domain_run(out, runs)
    cut_after_first_gate_stage(runs / "drive-on", runs / "drive-cut")
    refused = runs / "run-refused"
    shutil.copytree(runs / "run-clean", refused, symlinks=True)
    with (refused / "ledger.jsonl").open("ab") as ledger:
        ledger.write(b'{"not": "a ledger line"}\n')
    escalated(out, runs)
    print(runs, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
