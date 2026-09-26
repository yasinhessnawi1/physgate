"""Child process for the event log's kill test: emits events until it is killed."""

from __future__ import annotations

import sys
from pathlib import Path

from physgate.orchestrator.events import EventLog, RunStarted, StageEntered, SubtaskPlanned

STAGES = ("resolve", "spawn", "verify_reading", "implement", "gate", "review", "decide", "diff")


def main() -> None:
    """Emit a start, one plan line, then stage lines until killed."""
    log = EventLog(Path(sys.argv[1]), run_id="crash", gate_mode="on")
    log.emit(RunStarted, config_sha256="d" * 64)
    log.emit(SubtaskPlanned, subtask_id="s1", spec_path="p", assigned_role="r", module_dir="m")
    n = 0
    while True:
        log.emit(StageEntered, subtask_id="s1", attempt=1 + (n // 8) % 3, stage=STAGES[n % 8])
        n += 1


if __name__ == "__main__":
    main()
