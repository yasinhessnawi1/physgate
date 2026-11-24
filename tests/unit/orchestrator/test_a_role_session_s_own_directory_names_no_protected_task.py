"""A role session's own directory names no protected task: after its start, its end and a resume.

The hook sentinel records, at a session's first hook, every entry beneath the session's protected
roots, a held-out task's directory (its id) and file, with the file's digest, among them. Resume
reads that record (the end check of a session found running, and what the run's held records
held at the session's start), so it is kept, not removed. A session's own directory is kept from
every session of its run, but it can lie later where people and other sessions read: the part
of the record that names the protected entries is kept in the run's own place apart, which no
session reads or writes on any layer, and read from there by every check, the resume's among
them. What it catches is unchanged. A run installed before that place existed keeps the record
whole in the session's directory, and still resumes as it did.

The rig is the one the held records' rows use: stand-in sessions that run the real hook chain,
installed by the dispatcher's own installer, here with a held-out root holding one stand-in task.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import test_a_session_s_hooks_never_fork_the_run_s_own_records as base
from loop_fakes import Rig
from orch_helpers import make_config
from test_a_session_s_hooks_never_fork_the_run_s_own_records import (
    FACTS,
    INSTALL_BIN,
    MODEL,
    SESSION,
    Run,
    _orchestrator_dies,
    _resume,
    _settle,
    leftovers,
)

from physgate.hooks.settings import CONFIG_NAME, InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.knowledge import loader
from physgate.orchestrator import dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.processes import started_at
from physgate.orchestrator.run_config import RunBounds

__all__ = ["leftovers"]

TASK_ID = "control.held-out-stand-in-3e8c51"
FILE_NAME = "brief-71d0aa.json"
BYTES = b'{"stand-in": "a held-out brief"}\n'
DIGEST = hashlib.sha256(BYTES).hexdigest()

#: One more stand-in: it writes to the held-out file, as a shell the hooks could not see would,
#: then ends through its SessionEnd hook.
CHANGES = """
if MODE == "changes-held-out":
    with open(HELD, "ab") as out:
        out.write(b"changed\\n")
"""


class HeldOutRun(Run):
    """The rig's run with a held-out root holding one stand-in task."""

    def __init__(self, tmp_path: Path, mode: str) -> None:
        super().__init__(tmp_path, mode)
        self.held_out = tmp_path / "tier" / "held_out"
        task = self.held_out / TASK_ID
        task.mkdir(parents=True)
        self.held_file = task / FILE_NAME
        self.held_file.write_bytes(BYTES)
        prelude = f"FLAGS = {str(self.flags)!r}\nMODE = {mode!r}\nMODEL_NAME = {MODEL!r}\n"
        prelude += f"HELD = {str(self.held_file)!r}\n"
        marker = 'os.makedirs("modules/power", exist_ok=True)'
        assert marker in SESSION
        script = SESSION.replace(marker, CHANGES + marker, 1)
        self.binary.write_text(f"#!{sys.executable}\n{prelude}{script}")
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)

    def dispatcher(self, monkeypatch: pytest.MonkeyPatch) -> ClaudeDispatcher:
        bounds = RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        )
        config = make_config(
            bounds=bounds,
            os_layer_absent="allow",
            held_out=(str(self.held_out),),
            held_out_sha256=("0" * 64,),
        )
        monkeypatch.setattr(ClaudeDispatcher, "environment", lambda _self: FACTS)
        monkeypatch.setattr(ClaudeDispatcher, "_contracts", lambda _self, _request: ())
        monkeypatch.setattr(dispatch, "binary_version", lambda _binary: config.claude_version)
        monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
        monkeypatch.setattr(loader, "required_reading", lambda *_a, **_k: ())
        monkeypatch.setattr(loader, "always_loaded", lambda *_a, **_k: ())
        return ClaudeDispatcher(
            config=config,
            run=self.run,
            store_root=self.store_root,
            install_bin=INSTALL_BIN,
            binary=str(self.binary),
            base_url=None,
            credential=Credential(mode="api_key", secret="not-a-key"),
            review_root=Path("/nonexistent/review-scratch"),
        )


def _holders(where: Path) -> list[str]:
    """Every file under ``where`` that names the protected task, its file or its digest."""
    found = []
    for path in sorted(where.rglob("*")):
        if any(m in path.name for m in (TASK_ID, FILE_NAME)):
            found.append(str(path))
        elif path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            if any(m.encode() in data for m in (TASK_ID, FILE_NAME, DIGEST)):
                found.append(str(path))
    return found


def _recorded(run: HeldOutRun) -> None:
    """Not vacuous: the sentinel recorded the protected entries somewhere in the run."""
    assert _holders(run.run.run_dir), "the sentinel recorded no protected entry"


def _clean(run: HeldOutRun) -> None:
    _recorded(run)
    sdir = run.session_dir()
    assert _holders(sdir) == [], "the session's own directory names a protected task"


def _left(run: HeldOutRun, monkeypatch: pytest.MonkeyPatch, pids: list[int]) -> None:
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    pids.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))


def _no_place_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    """The installer called as before the place apart existed: with no place for it."""
    real = subprocess.run

    def install(argv: Any, *a: Any, **k: Any) -> Any:  # noqa: ANN401
        if isinstance(argv, list) and argv[1:3] == ["hooks", "install"]:
            at = [i for i, w in enumerate(argv) if w == "--sentinel-apart"]
            argv = [w for i, w in enumerate(argv) if not any(i in (j, j + 1) for j in at)]
        return real(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", install)


def test_after_its_start_the_session_s_own_directory_names_no_protected_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = HeldOutRun(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    _clean(run)


def test_after_its_end_check_the_session_s_own_directory_names_no_protected_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = HeldOutRun(tmp_path, "writes-module")
    loop = Rig(run.run.run_dir).open()
    try:
        run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
    finally:
        loop.close()
    _clean(run)


def test_after_a_resume_the_session_s_own_directory_names_no_protected_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = HeldOutRun(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        assert (run.flags / "session-end-ran").exists(), "the leftover never ran its end hook"
        assert loop.state.halted is None
    finally:
        loop.close()
    _clean(run)


def test_a_protected_file_changed_during_the_session_is_caught_at_its_end_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = HeldOutRun(tmp_path, "changes-held-out")
    loop = Rig(run.run.run_dir).open()
    raised: InvocationError | None = None
    try:
        run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
    except InvocationError as exc:
        raised = exc
    finally:
        loop.close()
    assert raised is not None, "a changed held-out file went unrefused"
    # By the sentinel's check after the stop, or the dispatcher's own record of the roots.
    assert raised.context.get("check") or raised.context.get("changed"), raised.context


#: A label in a protected path's place: the kind of protection, then twelve hex digits.
LABEL = re.compile(r"held-out entry [0-9a-f]{12}")


def test_a_protected_file_changed_during_the_session_is_named_by_no_path_where_its_end_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal, the hook log and the end record name a label where the path was."""
    run = HeldOutRun(tmp_path, "changes-held-out")
    loop = Rig(run.run.run_dir).open()
    raised: InvocationError | None = None
    try:
        run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
    except InvocationError as exc:
        raised = exc
    finally:
        loop.close()
    assert raised is not None, "a changed held-out file went unrefused"
    sdir = run.session_dir()
    assert (sdir / "after_stop.json").exists(), "the session's end left no record of its check"
    kept = {
        "the refusal": f"{raised} {json.dumps(raised.context)}",
        "after_stop.json": (sdir / "after_stop.json").read_text(),
        "the hook log": "".join(p.read_text() for p in sdir.rglob("hooks.log.jsonl")),
    }
    needles = (str(run.held_out), TASK_ID, FILE_NAME, DIGEST)
    named = {where: [n for n in needles if n in text] for where, text in kept.items()}
    assert named == dict.fromkeys(kept, []), f"where the protected material is, named: {named}"
    assert LABEL.search(kept["after_stop.json"]), kept["after_stop.json"]


@pytest.mark.parametrize("place", ["the run's own", "open to others"])
def test_a_held_out_file_with_a_second_name_before_the_commit_is_named_by_its_label(
    tmp_path: Path, place: str
) -> None:
    """What the commit's tripwire finds goes into the run's incident: its label, not its path.

    A place apart that no key can be had from gives labels all the same, never a raise in the
    incident's place.
    """
    task = tmp_path / "held_out" / TASK_ID
    task.mkdir(parents=True)
    (task / FILE_NAME).write_bytes(BYTES)
    (tmp_path / "worktree").mkdir()
    os.link(task / FILE_NAME, tmp_path / "worktree" / "copy")
    apart = dispatch.place_apart(tmp_path / "run")
    request = InstallRequest(
        profile="role",
        role="electrical",
        worktree=str(tmp_path / "worktree"),
        own_branch=None,
        store_root=None,
        state_dir=str(tmp_path / "outside" / "state"),
        target_dir=str(tmp_path / "outside" / "session"),
        claude_config_dir=str(tmp_path / "outside" / "cfg"),
        user_home=str(tmp_path / "outside" / "home"),
        token_ceiling=1000,
        held_out=(str(tmp_path / "held_out"),),
        sentinel_apart=str(apart),
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(build_config(request, installation()).model_dump_json())
    if place == "open to others":
        apart.chmod(0o755)
    try:
        found = dispatch.withheld_before_commit(config_path)
    except (OSError, ValueError) as exc:
        pytest.fail(f"the commit's tripwire raised in the incident's place: {exc!r}")
    assert found is not None and "has more than one name (2)" in found, found
    needles = (str(tmp_path / "held_out"), TASK_ID, FILE_NAME)
    assert [n for n in needles if n in found] == [], found
    assert LABEL.search(found), found


def _changed_while_gone(run: HeldOutRun, monkeypatch: pytest.MonkeyPatch, pids: list[int]) -> str:
    """The session exits with no end hook; a held-out file changes; what the resume's check says."""
    _left(run, monkeypatch, pids)
    assert _settle(lambda: started_at(pids[-1]) is None, 20.0)
    run.held_file.write_bytes(b"changed\n")
    loop = _resume(run, monkeypatch)
    try:
        with pytest.raises(InvocationError) as raised:
            loop._stop_leftovers()
    finally:
        loop.close()
    return raised.value.context.get("check", "")


def test_a_protected_file_changed_before_a_resume_is_caught_by_its_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = HeldOutRun(tmp_path, "gone")
    assert _changed_while_gone(run, monkeypatch, leftovers), "the resume's check refused nothing"


def test_a_run_installed_before_the_place_apart_existed_resumes_as_it_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """Its sessions' records are whole, in their own directories, and read there."""
    _no_place_apart(monkeypatch)
    run = HeldOutRun(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    assert _holders(run.session_dir()), "not a record taken as before: it is not whole"
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        assert loop.state.halted is None
    finally:
        loop.close()


def test_a_run_installed_before_the_place_apart_existed_still_catches_a_change_at_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    _no_place_apart(monkeypatch)
    run = HeldOutRun(tmp_path, "gone")
    assert _changed_while_gone(run, monkeypatch, leftovers), "the resume's check refused nothing"


def test_the_place_apart_is_the_run_s_own_and_no_session_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = HeldOutRun(tmp_path, "writes-module")
    loop = Rig(run.run.run_dir).open()
    try:
        run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
    finally:
        loop.close()
    sdir = run.session_dir()
    config = json.loads((sdir / "session" / CONFIG_NAME).read_text())
    named = [r for r in config["protected_roots"] if r["path"].startswith(str(run.run.run_dir))]
    places = [r for r in named if _holders(Path(r["path"]))]
    assert len(places) == 1, named
    (place,) = places
    assert place["reads"] == "denied" and place["watch"] == "none", place
    assert not Path(place["path"]).is_relative_to(run.run.run_dir / "sessions"), place
    assert stat.S_IMODE(Path(place["path"]).stat().st_mode) == 0o700


def _apart(run: HeldOutRun) -> Path:
    return run.run.run_dir / dispatch.SENTINEL_APART_DIR


def _made_wrong(run: HeldOutRun, how: str) -> None:
    """The run's place apart there before the install, as something else than the run's own."""
    apart, elsewhere = _apart(run), run.run.run_dir.parent / "apart-elsewhere"
    apart.parent.mkdir(parents=True, exist_ok=True)
    if how == "a link":
        elsewhere.mkdir(mode=0o700)
        apart.symlink_to(elsewhere)
    elif how == "open to others":
        apart.mkdir(mode=0o700)
        apart.chmod(0o755)
    else:
        apart.write_text("not a directory\n")


@pytest.mark.parametrize("how", ["a link", "open to others", "a file"])
def test_a_place_apart_that_is_not_the_run_s_own_directory_refuses_the_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    run = HeldOutRun(tmp_path, "writes-module")
    _made_wrong(run, how)
    loop = Rig(run.run.run_dir).open()
    raised: Exception | None = None
    try:
        run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
    except Exception as exc:  # noqa: BLE001 - the row holds what was raised
        raised = exc
    finally:
        loop.close()
    assert raised is not None, f"a session was installed with a place apart that is {how}"
    assert "place apart" in str(raised), raised
    assert not (run.flags / "session-end-ran").exists(), "the session ran"


@pytest.mark.parametrize("how", ["a link", "open to others"])
def test_a_place_apart_changed_before_a_resume_refuses_its_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int], how: str
) -> None:
    run = HeldOutRun(tmp_path, "gone")
    _left(run, monkeypatch, leftovers)
    assert _settle(lambda: started_at(leftovers[-1]) is None, 20.0)
    apart = _apart(run)
    if how == "a link":
        moved = apart.parent / "apart-moved"
        apart.rename(moved)
        apart.symlink_to(moved)
    else:
        apart.chmod(0o755)
    loop = _resume(run, monkeypatch)
    try:
        with pytest.raises(InvocationError) as raised:
            loop._stop_leftovers()
    finally:
        loop.close()
    # Refused as a check that failed; what failed, the place apart, is in the hook log.
    assert raised.value.context.get("check") == "the check recorded 'error'", raised.value.context
    logged = "".join(p.read_text() for p in (run.session_dir() / "state").rglob("hooks.log.jsonl"))
    assert "place apart" in logged, logged[-600:]


assert base.SESSION  # the rig's stand-in, extended above
