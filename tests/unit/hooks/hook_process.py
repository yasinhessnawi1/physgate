"""A session installed by the real generator, and its hook commands run as real processes.

The import audit and the network test both need what Claude Code runs: the
command the settings file names, in a fresh interpreter, on a session whose
protected paths, store and reading set exist. The trampoline is left out, so a
flag can be put in front of the module; everything after it is the generated
command, byte for byte.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from hook_helpers import SESSION, make_store, node

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install


class InstalledSession:
    """One session's files, and the generated hook command for each event."""

    def __init__(self, tmp: Path) -> None:
        """Lay out a worktree, a store and a reading set, and install the hooks for them."""
        self.worktree = tmp / "worktree"
        gate = self.worktree / "src" / "physgate" / "gate"
        gate.mkdir(parents=True)
        (gate / "check.py").write_text("CHECK = True\n")
        (self.worktree / "src" / "physgate" / "electrical").mkdir(parents=True)
        self.store = tmp / "outside" / "store"
        make_store(self.store, node("electrical.motor"), node("mechanical.frame", "mechanical"))
        docs = tmp / "docs"
        docs.mkdir()
        self.reading = []
        for name in ("standards.md", "spec.md"):
            (docs / name).write_text("A line of required reading.\n" * 20)
            self.reading.append(str(docs / name))
        done = install(
            InstallRequest(
                profile="role",
                role="electrical",
                worktree=str(self.worktree),
                own_branch="subtask/electrical-1",
                store_root=str(self.store),
                state_dir=str(tmp / "outside" / "state"),
                target_dir=str(tmp / "outside" / "session"),
                claude_config_dir=str(tmp / "outside" / "cfg"),
                user_home=str(tmp / "outside" / "home"),
                token_ceiling=100_000,
                required_reading=tuple(self.reading),
                always_loaded=tuple(self.reading),
            ),
            REGISTRY,
        )
        settings = json.loads(done.settings_path.read_text())
        self.commands: dict[str, list[str]] = {}
        for event, groups in settings["hooks"].items():
            argv = shlex.split(groups[0]["hooks"][0]["command"])
            # /bin/sh <trampoline> <watchdog> <interpreter> -I -m physgate.hooks ...
            assert argv[4:7] == ["-I", "-m", "physgate.hooks"], argv
            self.commands[event] = argv[3:]

    def event(self, name: str, **fields: Any) -> str:  # noqa: ANN401 - event fields
        """The event description Claude Code would send for this session."""
        return json.dumps(
            {"session_id": SESSION, "cwd": str(self.worktree), "hook_event_name": name} | fields
        )

    def run(
        self, name: str, stdin: str, *, flags: tuple[str, ...] = (), prelude: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run the generated command for ``name``.

        ``flags`` go to the interpreter before the module. ``prelude`` replaces
        ``-m physgate.hooks`` with ``-c <prelude>``, which receives the hook's own
        arguments and is expected to run the module itself.
        """
        interpreter, _, _, _, *args = self.commands[name]
        if prelude is None:
            argv = [interpreter, *flags, "-I", "-m", "physgate.hooks", *args]
        else:
            argv = [interpreter, *flags, "-I", "-c", prelude, *args]
        return subprocess.run(argv, input=stdin, capture_output=True, text=True, check=False)

    def read_everything(self) -> None:
        """Record every required file as read in full, through the real hook."""
        for path in self.reading:
            lines = len(Path(path).read_text().splitlines()) + 1
            response = {
                "type": "text",
                "file": {"filePath": path, "numLines": lines, "startLine": 1, "totalLines": lines},
            }
            done = self.run(
                "PostToolUse",
                self.event(
                    "PostToolUse",
                    tool_name="Read",
                    tool_input={"file_path": path},
                    tool_response=response,
                ),
            )
            assert done.returncode == 0, done.stderr

    def orchestrator_writes_a_node(self) -> None:
        """Change the store the way the orchestrator does, so the node check has work to do."""
        from physgate.state.store import Store

        store = Store(self.store)
        try:
            payload = node("electrical.driver")
            assert store.write_node(payload, "electrical").accepted
        finally:
            store.close()


def hot_path_calls(session: InstalledSession) -> list[tuple[str, str, str]]:
    """(label, event, stdin) for every call an ordinary session makes, allowed each time."""
    bash = {"command": "python3 -m pytest -q tests/", "description": "run the tests"}
    driver = str(session.worktree / "src" / "physgate" / "electrical" / "driver.py")
    e = session.event
    return [
        ("PreToolUse Bash", "PreToolUse", e("PreToolUse", tool_name="Bash", tool_input=bash)),
        (
            "PreToolUse Write",
            "PreToolUse",
            e("PreToolUse", tool_name="Write", tool_input={"file_path": driver, "content": "x\n"}),
        ),
        (
            "PreToolUse Edit",
            "PreToolUse",
            e(
                "PreToolUse",
                tool_name="Edit",
                tool_input={"file_path": driver, "old_string": "x", "new_string": "y"},
            ),
        ),
        (
            "PreToolUse Read",
            "PreToolUse",
            e("PreToolUse", tool_name="Read", tool_input={"file_path": session.reading[0]}),
        ),
        (
            "PostToolUse Bash",
            "PostToolUse",
            e("PostToolUse", tool_name="Bash", tool_input=bash, tool_response={"stdout": ""}),
        ),
        (
            "PostToolUseFailure Bash",
            "PostToolUseFailure",
            e(
                "PostToolUseFailure",
                tool_name="Bash",
                tool_input=bash,
                error="Exit code 1",
                is_interrupt=False,
            ),
        ),
        ("Stop", "Stop", e("Stop", stop_hook_active=False)),
        ("SessionEnd", "SessionEnd", e("SessionEnd", reason="other")),
    ]


def proposal(session: InstalledSession, owner: str = "electrical") -> str:
    """A Write of a node proposal, legal when ``owner`` is the session's role."""
    path = session.worktree / ".physgate" / "proposals" / "electrical.encoder.json"
    content = json.dumps(node("electrical.encoder", owner))
    return session.event(
        "PreToolUse", tool_name="Write", tool_input={"file_path": str(path), "content": content}
    )
