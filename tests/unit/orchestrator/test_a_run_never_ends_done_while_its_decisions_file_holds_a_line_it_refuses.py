"""A run never ends ``done`` while its decisions file holds a line its reader refuses.

A person's line can land in the decisions file while the last session runs, or after the run is
done, when the operator runs it again. The file is read before the run is ended: a line its reader
refuses is one incident and a halt, and the drive returns that halt, so what the command prints and
what the log records agree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loop_fakes import Rig, plan
from test_a_session_end_s_findings_are_recorded_before_its_incidents_and_a_kill_writes_the_rest import (  # noqa: E501
    kinds,
    lines,
    outcome,
)

from physgate.orchestrator.events import read_events
from physgate.orchestrator.queue import DECISIONS_NAME
from physgate.orchestrator.replay import replay

BROKEN = b'{"kind": "decision", "item_id": "nothing like a decision"}\n'


def _ends(rig: Rig) -> tuple[list[str], str]:
    rows = lines(rig)
    return kinds(rows), replay(read_events(rig.run_dir / "events.jsonl")).next_step().kind


def test_a_line_landing_during_the_last_session_halts_the_drive_it_ends(tmp_path: Path) -> None:
    rig = Rig(tmp_path / "run")
    loop = rig.open()
    loop.start(plan("s1"))
    real = rig.dispatcher.run

    def run(request: Any, on_spawn: Any = None) -> Any:  # noqa: ANN401 - the port's own
        (rig.run_dir / DECISIONS_NAME).write_bytes(BROKEN)
        return real(request, on_spawn)

    rig.dispatcher.run = run  # type: ignore[method-assign]
    said = outcome(loop.run)
    loop.close()
    written, replayed = _ends(rig)
    assert written[-2:] == ["incident", "halted"]
    assert said == "halted", f"the drive said {said} where the log ends halted"
    assert replayed == "halted"


@pytest.mark.parametrize("command", ["run", "resume"])
def test_a_line_landing_after_done_halts_the_next_drive(tmp_path: Path, command: str) -> None:
    rig = Rig(tmp_path / "run")
    loop = rig.open()
    loop.start(plan("s1"))
    assert outcome(loop.run) == "done"
    loop.close()
    (rig.run_dir / DECISIONS_NAME).write_bytes(BROKEN)
    again = rig.open()
    said = outcome(again.run if command == "run" else again.resume)
    again.close()
    written, replayed = _ends(rig)
    assert written[-2:] == ["incident", "halted"]
    assert said == "halted", f"the drive said {said} where the log ends halted"
    assert replayed == "halted"
