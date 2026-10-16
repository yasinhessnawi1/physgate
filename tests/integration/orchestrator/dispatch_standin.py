"""A stand-in orchestrator process: dispatches one attempt, and is killed while it waits."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.events import EventLog, RunStarted, SessionSpawned
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import RunConfig


def main() -> None:
    """Run the attempt described by the JSON file named on the command line."""
    spec = json.loads(Path(sys.argv[1]).read_text())
    config = RunConfig.model_validate_json(json.dumps(spec["config"]))
    run = RunGit(repo=Path(spec["repo"]), run_dir=Path(spec["run_dir"]), run_id=config.run_id)
    dispatcher = ClaudeDispatcher(
        config=config,
        run=run,
        store_root=Path(spec["store_root"]),
        install_bin=Path(spec["install_bin"]),
        binary=claude_binary(),
        base_url=spec["base_url"],
        credential=Credential(**spec["credential"]),
        review_root=Path("/nonexistent/review-scratch"),
    )
    # The loop's own record of the spawn, which a resume holds the process record to.
    log = EventLog(run.run_dir / "events.jsonl", run_id=config.run_id, gate_mode=config.gate_mode)
    if not log.events:
        log.append(RunStarted(**log.envelope(), config_sha256="0" * 64))

    def spawned(session_id: str, pid: int, started: str) -> None:
        log.append(
            SessionSpawned(**log.envelope(), session_id=session_id, pid=pid, started=started)
        )

    dispatcher.run(SessionRequest.model_validate_json(json.dumps(spec["request"])), spawned)


if __name__ == "__main__":
    main()
