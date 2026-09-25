"""The halt record, taken at a session's first hook, covers the code the rare paths load.

An ordinary hook no longer loads the validation library or the state package, so
the halt class, which watches the files of loaded code, would never have seen
them: the proposal hook and the node check load them only after the sentinel has
run. The first hook therefore records their files without importing them. This
test runs both rare paths as real processes, lists every file they loaded under
the hook installation, and requires each one to be in the record the first hook
took, so an import added upstream fails here instead of going unwatched.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from hook_helpers import SESSION
from hook_process import InstalledSession, hot_path_calls, proposal

#: Run in place of ``-m physgate.hooks``: run the module, then write down the file
#: of every module the process loaded.
PRELUDE = """
import atexit, json, sys
out, *rest = sys.argv[1:]

def dump():
    files = sorted({getattr(m, "__file__", None) or "" for m in list(sys.modules.values())})
    with open(out, "w") as handle:
        handle.write(json.dumps([f for f in files if f]))

atexit.register(dump)
import runpy
sys.argv = ["physgate.hooks", *rest]
runpy.run_module("physgate.hooks", run_name="__main__", alter_sys=True)
"""


def _loaded(session: InstalledSession, event: str, stdin: str, out: Path) -> tuple[int, set[str]]:
    interpreter, _, _, _, *args = session.commands[event]
    done = subprocess.run(
        [interpreter, "-I", "-c", PRELUDE, str(out), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, {os.path.realpath(f) for f in json.loads(out.read_text())}


def test_every_file_the_rare_paths_load_is_in_the_first_hooks_record(tmp_path: Path) -> None:
    session = InstalledSession(tmp_path / "session")
    first = session.run("SessionStart", session.event("SessionStart", source="startup"))
    assert first.returncode == 0, first.stderr
    session.read_everything()
    config = json.loads(
        next((tmp_path / "session" / "outside" / "session").glob("session-config.json")).read_text()
    )
    halt_roots = [
        os.path.realpath(r["path"]) for r in config["protected_roots"] if r["watch"] == "halt"
    ]

    def under_halt(files: set[str]) -> set[str]:
        return {
            f
            for f in files
            if any(f == r or f.startswith(r.rstrip("/") + "/") for r in halt_roots)
            and f.endswith((".py", ".so", ".pyd"))
        }

    rc, ordinary = _loaded(session, "PreToolUse", hot_path_calls(session)[0][2], tmp_path / "a")
    assert rc == 0
    rc, proposing = _loaded(session, "PreToolUse", proposal(session), tmp_path / "b")
    assert rc == 0
    session.orchestrator_writes_a_node()
    rc, checking = _loaded(session, "PreToolUse", hot_path_calls(session)[0][2], tmp_path / "c")
    assert rc == 0
    rare = under_halt(proposing | checking) - under_halt(ordinary)
    # Not vacuous: the rare paths do load code an ordinary hook does not.
    assert any("/pydantic/" in f for f in rare)
    assert any(f.endswith("physgate/state/schema.py") for f in rare)
    record = json.loads(
        (
            tmp_path
            / "session"
            / "outside"
            / "state"
            / "sessions"
            / SESSION
            / "sentinel"
            / "baseline.json"
        ).read_text()
    )["halt"]
    assert sorted(rare - set(record)) == []
