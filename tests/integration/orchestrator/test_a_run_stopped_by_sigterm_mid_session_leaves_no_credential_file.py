"""A run stopped by SIGTERM mid-session ends its real session and leaves no credential file.

The run is sent SIGTERM while a real Claude Code session waits on a request the scripted endpoint
holds open. It ends that session and removes the session's credential files (here the api_key
mode's key and helper, the dummy key) before it ends by the signal; the resume then finds the
session gone and drives the run to its end as it would after a kill. No model is called, and no
credential is used: the endpoint is this process, and the key is a dummy. Only file names are
looked at, never a file's content.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest
from kill_cycles import SUBTASKS, Anchor, build, printed_step, session_of, session_script
from scripted_endpoint import DUMMY_KEY, serving
from test_a_resume_after_a_kill_mid_session_keeps_the_run_s_record import (
    HELD_REQUEST,
    OTHER_CREDENTIALS,
    _said,
    spawn,
)

from physgate.orchestrator.credentials import KEY_FILE, KEY_HELPER, LOGIN_FILE
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.processes import started_at

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

NAMES = frozenset({LOGIN_FILE, KEY_FILE, KEY_HELPER})


def credential_files(top: Path) -> list[str]:
    """Every file under ``top`` named as a credential is, by its path only; never read."""
    return sorted(
        os.path.join(where, name)
        for where, _dirs, files in os.walk(top)
        for name in files
        if name in NAMES
    )


def test_a_sigterm_mid_session_ends_the_session_and_removes_its_credential(
    tmp_path: Path,
) -> None:
    install = tmp_path / "install"
    prepare_install(install, Path(__file__).resolve().parents[3])
    run_dir = tmp_path / "run"
    anchor = Anchor()
    script = session_script()
    with serving(script) as (api, url):
        env = {
            **{k: v for k, v in os.environ.items() if k not in OTHER_CREDENTIALS},
            "ANTHROPIC_API_KEY": DUMMY_KEY,
            "ANTHROPIC_BASE_URL": url,
            "DISABLE_AUTOUPDATER": "1",
        }
        api.on_request = anchor
        build(tmp_path, url)
        subtask = SUBTASKS[0]
        anchor.arm(subtask, min(HELD_REQUEST, len(script.main)))
        proc = spawn(tmp_path, "run", env, str(install))
        deadline = time.monotonic() + 600
        while not anchor.fired.wait(timeout=0.05):
            assert proc.poll() is None, _said(tmp_path)
            assert time.monotonic() < deadline, "the held request was never reached"
        session = session_of(run_dir, subtask)
        assert session is not None
        pid, recorded = int(session["pid"]), session["started"]
        sdir = run_dir / "sessions" / str(session["session_id"])
        assert started_at(pid) == recorded, "the session was not running at the signal"
        assert credential_files(sdir), "the running session had no credential file"
        try:
            proc.send_signal(signal.SIGTERM)
            code = proc.wait(timeout=120)
        finally:
            anchor.arm("", 0)
            anchor.release.set()
        assert code == -signal.SIGTERM, _said(tmp_path)
        assert started_at(pid) != recorded, "the session outlived its run's SIGTERM"
        assert credential_files(run_dir) == []
        resume = spawn(tmp_path, "resume", env, str(install))
        try:
            resumed = resume.wait(timeout=900)
        except subprocess.TimeoutExpired:
            resume.kill()
            raise
    out = (tmp_path / "resume.out").read_text()
    assert resumed == 0 and printed_step(tmp_path / "resume.out") == "done", out
    assert credential_files(run_dir) == []
