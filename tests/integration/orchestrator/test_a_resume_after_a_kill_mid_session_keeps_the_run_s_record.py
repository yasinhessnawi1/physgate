"""A resume after a kill mid-session keeps the run's record, with a real session's hooks.

The orchestrator is killed while a real Claude Code session waits on a request the scripted
endpoint holds open. The resume writes its first lines and then stops that session, whose
SessionEnd hook runs as the runtime ends it. That hook's sentinel once put the run's event log
back from its record of the session's start, on a new inode, while the resume went on appending
to the old one: everything the resume wrote was lost when it exited. Here the record on disk must
be the resume's, through to the run's end. No model is called: the endpoint is this process.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from kill_cycles import SUBTASKS, Anchor, build, child, printed_step, session_of, session_script
from scripted_endpoint import DUMMY_KEY, serving

from physgate.orchestrator.events import Incident, LeftoverStopped, read_events
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.processes import started_at

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

#: The request of the first subtask's session that is held open while the kill lands: the
#: Bash step, after the session's reading, so its hooks have taken their record.
HELD_REQUEST = 6
OTHER_CREDENTIALS = ("ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
HERE = Path(__file__).resolve().parent


def spawn(root: Path, mode: str, env: dict[str, str], install: str) -> subprocess.Popen[bytes]:
    """``physgate run`` or ``resume`` in a process of its own, which a test can kill."""
    with (root / f"{mode}.out").open("ab") as out:
        return subprocess.Popen(
            [sys.executable, str(Path(__file__)), "child", str(root), mode, install],
            stdout=out,
            stderr=out,
            env=env,
        )


def _said(root: Path) -> str:
    """What the run printed, and how its record ends: for a run that ended before the kill."""
    tail = [
        {
            k: v
            for k, v in e.model_dump(mode="json").items()
            if k in ("kind", "reason", "detail", "cause")
        }
        for e in read_events(root / "run" / "events.jsonl")[-6:]
    ]
    return (root / "run.out").read_text() + json.dumps(tail)


def test_a_resume_s_lines_stay_on_the_record_after_it_stops_a_real_leftover(tmp_path: Path) -> None:
    install = tmp_path / "install"
    prepare_install(install, Path(__file__).resolve().parents[3])
    run_dir = tmp_path / "run"
    events = run_dir / "events.jsonl"
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
        assert started_at(pid) == recorded, "the session was not running at the kill"
        proc.send_signal(signal.SIGKILL)
        proc.wait()
        assert started_at(pid) == recorded, "the session did not outlive its orchestrator"

        def release_once_gone() -> None:
            while started_at(pid) == recorded and not anchor.release.is_set():
                time.sleep(0.05)
            anchor.release.set()

        watcher = threading.Thread(target=release_once_gone, daemon=True)
        watcher.start()
        resume = spawn(tmp_path, "resume", env, str(install))
        try:
            code = resume.wait(timeout=900)
        except subprocess.TimeoutExpired:
            resume.kill()
            raise
        finally:
            anchor.arm("", 0)
            anchor.release.set()
            watcher.join(timeout=10)
    out = (tmp_path / "resume.out").read_text()
    sid = str(session["session_id"])
    hooks = run_dir / "sessions" / sid / "state" / "hooks.log.jsonl"
    put_back = [
        r
        for r in (json.loads(x) for x in hooks.read_text().splitlines())
        if r.get("decision") == "put back"
        and any(p.endswith(("events.jsonl", "ledger.jsonl", "queue.jsonl")) for p in r["paths"])
    ]
    assert put_back == [], "a leftover's hook put the run's own records back"
    recorded_events = read_events(events)
    stopped = [e for e in recorded_events if isinstance(e, LeftoverStopped) and e.session_id == sid]
    assert len(stopped) == 1, "the resume's own lines are not on the run's record"
    assert [e.cause for e in recorded_events if isinstance(e, Incident)] == []
    assert code == 0 and printed_step(tmp_path / "resume.out") == "done", out


if __name__ == "__main__" and sys.argv[1:2] == ["child"]:
    # The suite's stand-in roles, registered as the suite's own fixture registers them: the
    # shipped register dispatches control and firmware alone.
    sys.path.insert(0, str(HERE.parents[1]))
    from stand_in_roles import stand_in_roles

    from physgate import roles

    for _name, _role in stand_in_roles().items():
        roles.ROLES[_name] = _role
    _root, _mode, _install = sys.argv[2:5]
    sys.exit(child(Path(_root), "real", _mode, _install))
