"""A builder the account's usage limit cut mid-work goes on, on resume, in the worktree it left.

A role session can write files and then end on the limit before its work is done. Nothing it
wrote is committed then: an attempt is committed only at a session's completed end. Its worktree
is kept as it was, and the session that goes on after the reset runs in it, as the same attempt
with the same number, so the attempt count does not move. That session's completed end commits
everything the worktree holds, the files written before the limit among them, and the attempt's
commit is then scanned and gated as any is.

Here a stand-in binary plays two sessions of one attempt in the real dispatcher and the real
worktree: the first writes a file and ends on the limit, in the shape a live stream gave it; the
second writes another file and completes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from test_a_role_session_leaves_nothing_running_before_the_orchestrator_s_git import (
    GITENV,
    SESSION,
    Session,
)

from physgate.orchestrator.budget import SessionEnd

#: The stand-in for both sessions; the prelude of the other module's stand-in is prepended. The
#: first call writes ``half.py`` and ends on the limit; the next writes ``rest.py`` and completes.
CUT_THEN_DONE = r"""
import json, os, shlex, subprocess, sys

argv = sys.argv[1:]
if argv == ["--version"]:
    print("2.1.272 (Claude Code)")
    sys.exit(0)
settings = json.load(open(argv[argv.index("--settings") + 1]))
session_id = argv[argv.index("--session-id") + 1]


def hook(event):
    command = settings["hooks"][event][0]["hooks"][0]["command"]
    body = json.dumps({"session_id": session_id, "cwd": os.getcwd(), "hook_event_name": event})
    subprocess.run(shlex.split(command), input=body.encode(), capture_output=True, check=False)


cut = not os.path.exists(os.path.join(FLAGS, "cut"))
hook("SessionStart")
os.makedirs("modules/power", exist_ok=True)
if cut:
    open("modules/power/half.py", "w").write("y = 1\n")
    open(os.path.join(FLAGS, "cut"), "w").close()
else:
    open("modules/power/rest.py", "w").write("z = 2\n")
hook("SessionEnd")
said = "You've hit your session limit · resets 1:20pm (Europe/Oslo)"
usage = {"input_tokens": 3, "output_tokens": 5}
if cut:
    info = {"status": "rejected", "resetsAt": 1794572400, "rateLimitType": "five_hour"}
    message = {"id": "m0", "model": "<synthetic>", "role": "assistant", "type": "message",
               "content": [{"type": "text", "text": said}]}
    lines = [
        {"type": "rate_limit_event", "rate_limit_info": info},
        {"type": "assistant", "message": message, "error": "rate_limit"},
        {"type": "result", "is_error": True, "terminal_reason": "api_error",
         "api_error_status": 429, "result": said},
    ]
else:
    lines = [
        {"type": "assistant", "message": {"id": "m1", "model": MODEL_NAME, "usage": usage}},
        {"type": "result", "is_error": False, "terminal_reason": "completed",
         "modelUsage": {MODEL_NAME: {"inputTokens": 3, "outputTokens": 5}}},
    ]
sys.stdout.write("".join(json.dumps(line) + "\n" for line in lines))
sys.stdout.flush()
sys.exit(1 if cut else 0)
"""


def _files(worktree: Path, *args: str) -> list[str]:
    shown = subprocess.run(
        ["git", *args], cwd=worktree, env=GITENV, capture_output=True, text=True, check=True
    )
    return sorted(shown.stdout.split())


def test_files_written_before_the_limit_stay_uncommitted_and_the_attempt_s_end_commits_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = Session(tmp_path, "plain", pause=0.0, wall_clock_s=60.0)
    written = session.binary.read_text()
    session.binary.write_text(written[: written.index(SESSION)] + CUT_THEN_DONE)
    dispatcher = session.dispatcher(monkeypatch)
    worktree = session.run.subtask_worktree("s1")

    cut = dispatcher.run(session.request(), session.spawned)
    assert cut.end == SessionEnd(outcome="infrastructure", cause="usage_limit")
    assert cut.usage_limit is not None and cut.usage_limit.limit_type == "five_hour"
    assert (cut.attempt_commit, session.at_first_git) == (None, None), "nothing is committed"
    # The worktree is kept as the session left it: its file is there, and in no commit.
    assert (worktree / "modules/power/half.py").read_text() == "y = 1\n"
    assert _files(worktree, "ls-files", "--others", "--exclude-standard") == [
        "modules/power/half.py"
    ]

    # After the reset, the same attempt, by its same number, goes on in the same worktree.
    done = dispatcher.run(session.request(), session.spawned)
    assert done.end == SessionEnd(outcome="completed", cause=None)
    assert done.attempt_commit is not None
    assert Path(str(done.worktree)) == worktree
    committed = _files(worktree, "show", "--name-only", "--format=", done.attempt_commit)
    assert committed == ["modules/power/half.py", "modules/power/rest.py"]
    message = _files(worktree, "log", "-1", "--format=%s", done.attempt_commit)
    assert message == ["1", "Attempt", "of", "s1", "subtask"]
    assert _files(worktree, "status", "--porcelain") == []
