"""A role session as its orchestrator left it: spawned on the record, its sentinel's record taken.

A resume honours a role session's process record only when the event log recorded that spawn,
and checks it again only against the sentinel's own record. A test that leaves a session for a
resume to find makes both, as a real run does: the spawn line through the loop's own writer,
and the sentinel's record through the generated SessionStart command.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from loop_fakes import Rig, plan

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install

#: The installation a resume's check runs from: this interpreter's environment, where the
#: hooks the tests install come from.
INSTALL_BIN = Path(sys.executable).parent / "physgate"


def spawn_logged(run_dir: Path, spawns: list[tuple[str, int, str]]) -> None:
    """Add a spawn line for each (session id, pid, start time) to the run's event log.

    The log is started first if it is new, as the loop's own writer starts it.
    """
    loop = Rig(run_dir).open()
    try:
        if not loop.record.log.events:
            loop.start(plan("s1"))
        for session_id, pid, started in spawns:
            loop._spawned(session_id, pid, started)
    finally:
        loop.close()


def sentinel_installed(sdir: Path, protected: Path) -> None:
    """The session's hooks installed in ``sdir`` and its sentinel's record taken.

    ``protected`` is the session's one put-back root.
    """
    worktree = sdir.parent.parent / "worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    protected.mkdir(parents=True, exist_ok=True)
    done = install(
        InstallRequest(
            profile="role",
            role="electrical",
            worktree=str(worktree),
            own_branch=None,
            store_root=None,
            state_dir=str(sdir / "state"),
            target_dir=str(sdir / "session"),
            claude_config_dir=str(sdir / "config"),
            user_home=str(sdir / "home"),
            token_ceiling=100_000,
            extra_protected=(str(protected),),
        ),
        REGISTRY,
    )
    settings = json.loads(done.settings_path.read_text())
    command = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    event = {"session_id": sdir.name, "cwd": str(worktree), "hook_event_name": "SessionStart"}
    subprocess.run(
        shlex.split(command), input=json.dumps(event), text=True, capture_output=True, check=True
    )
