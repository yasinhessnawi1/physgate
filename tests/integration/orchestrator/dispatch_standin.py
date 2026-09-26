"""A stand-in orchestrator process: dispatches one attempt, and is killed while it waits."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from physgate.orchestrator.dispatch import ClaudeDispatcher
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
        api_key=spec["api_key"],
    )
    dispatcher.run(SessionRequest.model_validate_json(json.dumps(spec["request"])))


if __name__ == "__main__":
    main()
