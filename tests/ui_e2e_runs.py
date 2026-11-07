"""Build the runs the operator UI's browser tests read, under one root, and print that root.

Three runs made by the real loop with stand-in sessions and no model: gated on, observed and
clean (see ``ui_rig.real_runs``). Three more are the physics gate's three-mode plan, rebuilt
with the real gate in ``on``, ``observe`` and ``off`` (see ``ui_three_mode_rig``), so the gate's
own records, unchecked ones and a pass over nothing among them, reach the browser. One more,
``run-refused``, is a copy of the clean run whose ledger ends in a line no writer of this
package could have written, so the server refuses its ledger and the browser tests see the error
state render. Five more are copies of one run whose first subtask the loop escalated, for the
Queue view's tests (see ``QUEUE_RUNS``), and one more run that acts on decisions,
``run-esc-act``, whose item says what each verb will do. Two more record the OS layer and a
network with none requested, for the Settings view's tests (see ``SETTINGS_RUNS``): the layer
present, so the request is enforced, and the layer absent, so it is not. Beside the runs, never
inside them, ``knowledge`` is a curated library holding every state a library file can be in
(see ``ui_library_rig``), with two files a reader refuses: a skill file that is a link inside the
library, and a staged file not named as staging names a candidate. The browser tests start
``physgate ui`` over the root this prints, with that library, so what they check is the real
server reading real records.

Usage: ``uv run python tests/ui_e2e_runs.py <directory>``. The directory is emptied first.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from stand_in_roles import register
from ui_library_rig import build_library
from ui_rig import escalated_run, evaluation_rig, real_runs
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
    # One run that acts on decisions, so its item says what approve and reject will do.
    escalated_run(out, "run-esc-act", acts=True)


#: The runs the Settings view's browser tests read, beside the ones made above: the OS layer
#: present with no network requested, which the layer enforces, and absent, where nothing does.
SETTINGS_RUNS = ("set-present-none", "set-absent-none")


def settings_runs(out: Path, runs: Path) -> None:
    """Two real-loop runs that record the OS layer and a network with none requested."""
    from physgate.oslayer.probe import Absent, Present  # noqa: PLC0415 - as the rig imports it

    rig = evaluation_rig()
    present, absent = SETTINGS_RUNS
    rig.fake_run(
        runs,
        present,
        rig.target_repo(out / present),
        overrides={
            "os_layer": Present(mechanism="seatbelt", claude_version="2.1.301"),
            "network": "none",
            "network_enforced": True,
        },
    )
    rig.fake_run(
        runs,
        absent,
        rig.target_repo(out / absent),
        overrides={
            "os_layer": Absent(reason="macOS: sandbox-exec is missing"),
            "network": "none",
            "network_enforced": False,
        },
    )


def library(out: Path) -> Path:
    """The fixture library beside the runs, with a row each listing must keep as an error."""
    root = build_library(out).root
    # A skill file that links to another file of the library: refused, never followed.
    (root / "electrical" / "skill.md").symlink_to(Path("..") / "control" / "skill.md")
    # A staged file whose name is not a candidate's: its own row, never the whole list.
    (root / "staging" / "standards" / "bad name.json").write_text("{}\n")
    return root


def main(argv: list[str]) -> int:
    """Build the runs under ``argv[1]`` and print the root that holds them."""
    # The runs plan the suite's stand-in roles, which the shipped register does not hold.
    register()
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
    settings_runs(out, runs)
    library(out)
    print(runs, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
