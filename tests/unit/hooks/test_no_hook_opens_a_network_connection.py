"""No hook opens a network connection, on any event, on the ordinary path or the rare ones.

A hook is deterministic and makes no network call: the token count is an
offline bound for exactly this reason. This test holds the hooks to it. Each
generated hook command runs as a real process with an audit hook installed
before the hook package loads, and the audit hook blocks every socket
operation. It blocks starting another process too, because a hook that ran a
program could reach the network where no audit hook in this interpreter would
see it. What it blocks it also writes down, so the test asserts on a record,
not on the absence of an error.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from hook_process import InstalledSession, hot_path_calls, proposal

#: Run in place of ``-m physgate.hooks``: install the blocking audit hook, then
#: run the module (or, for the control, a script) with the hook's own arguments.
PRELUDE = """
import sys
record, target, *rest = sys.argv[1:]
BLOCKED = (
    "socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
    "os.fork", "os.forkpty", "pty.spawn", "ctypes.", "urllib.", "http.client.",
    "ftplib.", "smtplib.", "poplib.", "imaplib.", "nntplib.", "telnetlib.", "webbrowser.",
)

def audit(event, args):
    if event.startswith(BLOCKED):
        with open(record, "a") as handle:
            handle.write(event + "\\n")
        raise PermissionError("blocked by the network test: " + event)

sys.addaudithook(audit)
import runpy
sys.argv = [target, *rest]
if target == "physgate.hooks":
    runpy.run_module(target, run_name="__main__", alter_sys=True)
else:
    runpy.run_path(target, run_name="__main__")
"""


@pytest.fixture
def session(tmp_path: Path) -> InstalledSession:
    return InstalledSession(tmp_path / "session")


def _blocked(record: Path) -> list[str]:
    return record.read_text().splitlines() if record.exists() else []


def _hook(session: InstalledSession, record: Path, event: str, stdin: str) -> tuple[int, str]:
    """Run the generated command for ``event`` with the blocking audit hook in front."""
    interpreter, _, _, _, *args = session.commands[event]
    done = subprocess.run(
        [interpreter, "-I", "-c", PRELUDE, str(record), "physgate.hooks", *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def test_the_blocking_hook_sees_and_stops_a_connection(
    session: InstalledSession, tmp_path: Path
) -> None:
    # The control: the same prelude around a script that does connect. Without
    # it, a prelude that blocked nothing would let every assertion below pass.
    script = tmp_path / "connects.py"
    script.write_text("import socket\nsocket.create_connection(('127.0.0.1', 9), timeout=0.2)\n")
    record = tmp_path / "blocked.txt"
    done = subprocess.run(
        [session.commands["PreToolUse"][0], "-I", "-c", PRELUDE, str(record), str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0
    assert "blocked by the network test" in done.stderr
    assert any(event.startswith("socket.") for event in _blocked(record))


def test_no_hook_opens_a_connection_or_starts_a_process(
    session: InstalledSession, tmp_path: Path
) -> None:
    record = tmp_path / "blocked.txt"
    outcomes: dict[str, int] = {}
    outcomes["SessionStart"], out = _hook(
        session, record, "SessionStart", session.event("SessionStart", source="startup")
    )
    assert outcomes["SessionStart"] == 0, out[-2000:]
    session.read_everything()
    for label, event, stdin in hot_path_calls(session):
        outcomes[label], out = _hook(session, record, event, stdin)
        assert outcomes[label] == 0, (label, out[-2000:])
    # The rare paths, which load the validation library and the state package.
    outcomes["legal proposal"], out = _hook(session, record, "PreToolUse", proposal(session))
    assert outcomes["legal proposal"] == 0, out[-2000:]
    outcomes["refused proposal"], out = _hook(
        session, record, "PreToolUse", proposal(session, owner="mechanical")
    )
    assert outcomes["refused proposal"] == 2
    assert "blocked by the network test" not in out
    session.orchestrator_writes_a_node()
    outcomes["node check"], out = _hook(
        session, record, "PreToolUse", hot_path_calls(session)[0][2]
    )
    assert outcomes["node check"] == 0, out[-2000:]
    gate = session.worktree / "src" / "physgate" / "gate" / "check.py"
    write_to_gate = session.event(
        "PreToolUse", tool_name="Write", tool_input={"file_path": str(gate), "content": ""}
    )
    outcomes["refused write"], out = _hook(session, record, "PreToolUse", write_to_gate)
    assert outcomes["refused write"] == 2
    assert "blocked by the network test" not in out
    assert _blocked(record) == [], json.dumps(outcomes)
    assert len(outcomes) >= 12
