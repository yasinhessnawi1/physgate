"""A stand-in run process for the credential rows: one session spawned as the run spawns one.

``python credential_stop_child.py <session dir> <fake binary> <seeded> <on term>``. With
``seeded`` it first puts the credential where the harness puts it, in both modes' files; the fake
binary then starts a tool in a process group of its own (as the Bash tool runs a command),
writes its own login file in its configuration directory, says it is ready and runs until it is
stopped. ``on term`` is what the fake does on SIGTERM: ``default`` (it ends), ``ignore``, or
``rewrite`` (it writes its login file again, then ends); with ``survivor`` the fake ends as by
default, but the stop's probe is told the session's group never empties, as for a process no
signal reaches, and the stop's bound is half a second. The process waits on the session under
the run's stop-signal guard, as a run does, until a signal ends it. Every credential here is a
dummy: no real one is ever loaded.
"""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path

from physgate.orchestrator import stop_signals
from physgate.orchestrator.credentials import write_key_helper, write_login
from physgate.orchestrator.dispatch import spawn_held
from physgate.orchestrator.stop_signals import on_stop_signals

#: Fake content: no credential, only a stand-in for where one is put.
DUMMY = "dummy-not-a-credential"


def session_env(sdir: Path, *, on_term: str) -> dict[str, str]:
    """An environment the spawn accepts: a home and a ZDOTDIR no startup file is in."""
    home, zdotdir = sdir / "home", sdir.parent.parent / "zdotdir"
    (home / ".zshrc").mkdir(parents=True, exist_ok=True)
    zdotdir.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "ZDOTDIR": str(zdotdir),
        "CLAUDE_CONFIG_DIR": str(sdir / "config"),
        "READY": str(sdir / "ready"),
        "ON_TERM": on_term,
        "TOOL_PID": str(sdir / "tool.pid"),
        "WRITER_PID": str(sdir / "writer.pid"),
        "WRITER": str(sdir.parents[2] / "writer.sh"),
        "PY": sys.executable,
    }


def main(sdir: Path, fake: Path, *, seeded: bool, on_term: str) -> int:
    # As a run in the foreground of a terminal has them, whatever this test was started under.
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGHUP, signal.SIG_DFL)
    state, config = sdir / "state", sdir / "config"
    state.mkdir(parents=True, exist_ok=True)
    config.mkdir(parents=True, exist_ok=True)
    session_id = sdir.name
    if on_term == "survivor":
        # The probe stands in for the kernel's answer: a session no SIGKILL ends.
        vars(stop_signals).update(_group_left=lambda _pgid: True, REAP_S=0.5)
    with on_stop_signals():
        if seeded:
            write_login(config, DUMMY)
            write_key_helper(state, DUMMY)

        def while_held(pid: int, started: str) -> None:
            record = {"pid": pid, "started": started, "session_id": session_id}
            (sdir / "process.json").write_text(json.dumps(record))

        with (sdir / "stdout.jsonl").open("wb") as out, (sdir / "stderr.txt").open("wb") as err:
            process, _ = spawn_held(
                [str(fake), "--session-id", session_id],
                cwd=sdir,
                env=session_env(sdir, on_term=on_term),
                out=out,
                err=err,
                session_id=session_id,
                on_spawn=None,
                while_held=while_held,
                login_dir=config,
            )
            return process.wait()


if __name__ == "__main__":
    _sdir, _fake, _seeded, _on_term = sys.argv[1:5]
    sys.exit(main(Path(_sdir), Path(_fake), seeded=_seeded == "1", on_term=_on_term))
