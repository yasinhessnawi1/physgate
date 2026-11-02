"""A resume takes as the run's own only the bytes an orchestrator recorded writing.

A session found at a resume may have run on after its orchestrator died. Whatever it wrote to the
run's held records (the event log, the task ledger, the approval queue) in the record's own form
reads as the orchestrator's: a line names what it says, and a forged line can say anything. So no
line is taken as an orchestrator's for what it says. Each orchestrator process writes, before
every append, which record, at which offset, how many bytes and their digest, to the run's write
account; a resume takes every byte of a held record before its own open as the run's only where
the account names it, from the first byte on, and anything else halts the run. A second name for
a held record is a change wherever it is made, and no attempt commit holds one.

A session its run ended, whose check after the stop passed, is named settled in the account
before any git call on the attempt: the resume never runs its end check again, so it never puts
back what the run itself wrote after that check (the attempt's commit, its series records).

The rig is the one the held records' own rows use: stand-in sessions that run the real hook
chain, installed by the dispatcher's own installer.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import test_a_session_s_hooks_never_fork_the_run_s_own_records as base
from loop_fakes import Rig
from test_a_session_s_hooks_never_fork_the_run_s_own_records import (
    GITENV,
    Died,
    Run,
    _incidents,
    _orchestrator_dies,
    _resume,
    leftovers,
)

from physgate.orchestrator import dispatch
from physgate.orchestrator.events import EventLog, Incident, InstallChecked, TokensUsed, read_events
from physgate.orchestrator.exceptions import MergePreconditionError
from physgate.state.task_ledger import TaskLedger, TaskLine

__all__ = ["leftovers"]

BRANCH = "physgate/run-1/s1"


def _account(run: Run) -> Path:
    return run.run.run_dir / "writes.jsonl"


def _forge_tokens(run: Run, message_id: str) -> None:
    """A line in the record's form, written by a writer that is no orchestrator's."""
    forger = EventLog(run.log_path, run_id="run-1", gate_mode="on")
    sid = run.session_dir().name
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 0}
    usage |= {"cache_read_input_tokens": 0}
    forger.emit(TokensUsed, attribution=f"session:{sid}", message_id=message_id, usage=usage)
    forger.close()


def _forge_install(run: Run) -> None:
    forger = EventLog(run.log_path, run_id="run-1", gate_mode="on")
    forger.emit(InstallChecked, path="/forged", action="checked", seconds=0.0, entries=0)
    forger.close()


def _left(run: Run, monkeypatch: pytest.MonkeyPatch, pids: list[int]) -> None:
    """The orchestrator dies while its session runs on."""
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    pids.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))


def _judged(run: Run, monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], bool, str]:
    """A resume's stop of the leftovers: the incidents on the record, whether it halted, why."""
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        details = " ".join(e.detail for e in read_events(run.log_path) if isinstance(e, Incident))
        return _incidents(run.log_path), loop.state.halted is not None, details
    finally:
        loop.close()


def _baseline(run: Run) -> Path:
    sdir = run.session_dir()
    return sdir / "state" / "sessions" / sdir.name / "sentinel" / "baseline.json"


# -- what the account names ------------------------------------------------------------------------


def test_every_byte_the_run_wrote_to_its_log_is_named_in_its_write_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "clean")
    assert _account(run).exists(), "the run keeps no write account"
    lines = [json.loads(x) for x in _account(run).read_bytes().splitlines()]
    data = run.log_path.read_bytes()
    at = 0
    for line in (x for x in lines if x.get("record") == "events.jsonl"):
        assert line["offset"] == at
        chunk = data[at : at + line["length"]]
        import hashlib

        assert hashlib.sha256(chunk).hexdigest() == line["sha256"]
        assert line["identity"] == [os.stat(run.log_path).st_dev, os.stat(run.log_path).st_ino]
        at += line["length"]
    assert at == len(data), "a byte of the log is named by no line of the account"


# -- a leftover's lines (O1) -----------------------------------------------------------------------


def test_a_line_after_an_earlier_resume_died_before_its_stop_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The earlier resume's own lines are the run's; the leftover's line after them is not."""
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    _resume(run, monkeypatch).close()
    _forge_tokens(run, "m-after-the-first-resume")
    incidents, halted, _ = _judged(run, monkeypatch)
    assert incidents[-1:] == ["run_records_changed"]
    assert halted


def test_a_forged_install_line_makes_no_line_after_it_the_run_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    _forge_install(run)
    _forge_tokens(run, "m-forged")
    incidents, halted, _ = _judged(run, monkeypatch)
    assert incidents[-1:] == ["run_records_changed"]
    assert halted


def test_a_forged_ledger_line_after_a_forged_install_line_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    _forge_install(run)
    ledger = TaskLedger(run.run.run_dir / "ledger.jsonl")
    ledger.append(
        TaskLine(id="forged", spec_path="specs/x.md", assigned_role="electrical", attempt_count=1)
    )
    ledger.close()
    try:
        incidents, halted, details = _judged(run, monkeypatch)
    except MergePreconditionError:
        # The ledger is held to the event log when the record opens: refused before anything.
        return
    assert "run_records_changed" in incidents
    assert "ledger.jsonl" in details
    assert halted


def test_a_forged_end_record_makes_no_forged_line_the_run_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """An end record in the session's own directory says its run ended it: that is no proof."""
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    (run.session_dir() / "ended.json").write_text(json.dumps({"exit": 0, "findings": {}}))
    _forge_tokens(run, "m-forged-under-an-end")
    incidents, halted, _ = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents
    assert halted


def test_a_start_record_rewritten_to_the_forged_size_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The sentinel's record of the start is the session's to write: it sets no window."""
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    _forge_tokens(run, "m-forged-then-hidden")
    import hashlib

    data = run.log_path.read_bytes()
    base_record = json.loads(_baseline(run).read_text())
    for name, was in base_record["records"].items():
        if name.endswith("events.jsonl") and was is not None:
            was["size"] = len(data)
            was["sha256"] = hashlib.sha256(data).hexdigest()
    _baseline(run).write_text(json.dumps(base_record))
    incidents, halted, _ = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents
    assert halted


def test_a_start_record_naming_no_held_records_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """A start record with the held records taken out is never read as a session's of old."""
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    base_record = json.loads(_baseline(run).read_text())
    del base_record["records"]
    _baseline(run).write_text(json.dumps(base_record))
    incidents, halted, _ = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents
    assert halted


def test_a_leftover_s_chmod_of_the_log_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    os.chmod(run.log_path, 0o666)
    incidents, halted, details = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents, oct(stat.S_IMODE(os.stat(run.log_path).st_mode))
    assert "mode" in details
    assert halted


def test_a_run_with_no_write_account_halts_at_a_leftover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """A run recorded before the account, or one whose account is gone, is no proof of anything."""
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    assert _account(run).exists(), "the run keeps no write account"
    _account(run).unlink()
    incidents, halted, _ = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents
    assert halted


def test_a_write_account_line_of_no_form_halts_at_a_leftover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    assert _account(run).exists(), "the run keeps no write account"
    with _account(run).open("ab") as out:
        out.write(b'{"record": "events.jsonl", "offset": "nine"}\n')
    incidents, halted, _ = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents
    assert halted


def test_a_write_its_writer_died_in_covers_nothing_and_halts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The account's line is written first: one whose bytes never followed names nothing."""
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    assert _account(run).exists(), "the run keeps no write account"
    st = os.stat(run.log_path)
    import hashlib

    intent = {
        "record": "events.jsonl",
        "identity": [st.st_dev, st.st_ino],
        "offset": st.st_size,
        "length": 11,
        "sha256": hashlib.sha256(b'{"seq": 9}\n').hexdigest(),
    }
    with _account(run).open("ab") as out:
        out.write(json.dumps(intent).encode() + b"\n")
    incidents, halted, _ = _judged(run, monkeypatch)
    assert "run_records_changed" not in incidents
    assert not halted


# -- second names (O2) -----------------------------------------------------------------------------


def test_a_hard_link_a_leftover_made_to_the_log_halts_the_run_and_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    link = run.run.run_dir / "worktrees" / "s1" / "modules" / "power" / "kept.jsonl"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.link(run.log_path, link)
    incidents, halted, details = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents
    assert str(link) in details
    assert halted


WAITS = """
if MODE == "waits":
    flag("started")
    for _ in range(400):
        if os.path.exists(os.path.join(FLAGS, "forged")):
            break
        time.sleep(0.05)
    hook("PreToolUse", tool_name="Bash", tool_input={"command": "true"})
"""


def _session_meanwhile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    act: Any,  # noqa: ANN401
) -> tuple[Run, BaseException | None]:
    """A normal session under its run, while which ``act`` runs as one of its commands would."""
    session = base.SESSION.replace(
        'hook("SessionStart", source="startup")\n',
        'hook("SessionStart", source="startup")\n' + WAITS,
        1,
    )
    monkeypatch.setattr(base, "SESSION", session)
    run = Run(tmp_path, "waits")
    loop = Rig(run.run.run_dir).open()

    def meanwhile() -> None:
        deadline = time.monotonic() + 20
        while not (run.flags / "started").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        act(run)
        (run.flags / "forged").write_text("")

    thread = threading.Thread(target=meanwhile)
    thread.start()
    raised: BaseException | None = None
    try:
        try:
            run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
        except Exception as exc:  # noqa: BLE001 - asserted by the caller
            raised = exc
    finally:
        thread.join()
        loop.close()
    return run, raised


def _branch_files(run: Run) -> list[str]:
    shown = subprocess.run(
        ["git", "log", "--name-only", "--format=", f"master..{BRANCH}"],
        cwd=run.run.repo,
        env=GITENV,
        capture_output=True,
        text=True,
        check=False,
    )
    return shown.stdout.split()


def test_a_hard_link_to_the_log_in_the_integration_worktree_is_refused_at_the_session_s_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    def link(run: Run) -> None:
        trees = sorted(p for p in (run.run.run_dir / "worktrees").iterdir() if p.is_dir())
        target = trees[0] / "modules" / "power" / "events_link.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(run.log_path, target)

    run, raised = _session_meanwhile(tmp_path, monkeypatch, link)
    assert raised is not None, "a second name for the run's log went unrefused"
    assert "events.jsonl" in json.dumps(getattr(raised, "context", {})), raised
    assert "events_link.jsonl" not in _branch_files(run)


def test_a_hard_link_to_the_log_in_the_session_s_own_worktree_is_refused_and_never_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    def link(run: Run) -> None:
        target = run.run.run_dir / "worktrees" / "s1" / "modules" / "power" / "events_link.jsonl"
        os.link(run.log_path, target)

    run, raised = _session_meanwhile(tmp_path, monkeypatch, link)
    assert raised is not None, "a second name for the run's log in the worktree went unrefused"
    assert "events.jsonl" in json.dumps(getattr(raised, "context", {})), raised
    assert not any(f.endswith("events_link.jsonl") for f in _branch_files(run))


# -- the run's own git writes after a settled session (O3) -----------------------------------------


def _git_out(run: Run, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=run.run.repo, env=GITENV, capture_output=True, text=True, check=False
    ).stdout.strip()


def _has_commit(run: Run, commit: str) -> bool:
    found = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=run.run.repo,
        env=GITENV,
        capture_output=True,
        check=False,
    )
    return found.returncode == 0


def _ended_under_its_run(run: Run, monkeypatch: pytest.MonkeyPatch) -> str:
    """A session ends under its run, which dies before it writes the session's end line."""
    loop = Rig(run.run.run_dir).open()
    try:
        report = run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
    finally:
        loop.close()
    assert report.attempt_commit is not None
    return report.attempt_commit


def _killed_after_the_commit(run: Run, monkeypatch: pytest.MonkeyPatch) -> str:
    """The run dies after the attempt's commit and before the session's end record."""
    real = dispatch.write_record

    def dies(parent: Path, name: str, record: dict[str, Any], file: str) -> None:
        if file == "ended.json":
            raise Died
        real(parent, name, record, file)

    loop = Rig(run.run.run_dir).open()
    try:
        with monkeypatch.context() as killed:
            killed.setattr(dispatch, "write_record", dies)
            with pytest.raises(Died):
                run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
    finally:
        loop.close()
    assert not (run.session_dir() / "ended.json").exists()
    commit = _git_out(run, "rev-parse", "--verify", f"{BRANCH}^{{commit}}")
    assert commit != _git_out(run, "rev-parse", "master")
    return commit


def _resumed_keeps(run: Run, monkeypatch: pytest.MonkeyPatch, commit: str) -> None:
    before = len(run.hook_decisions())
    index = run.run.repo / ".git" / "worktrees" / "s1" / "index"
    indexed = index.read_bytes() if index.exists() else None
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        assert loop.state.halted is None
    finally:
        loop.close()
    after = run.hook_decisions()[before:]
    assert not any(d == "put back" for d, _ in after), after
    assert _has_commit(run, commit), "the attempt's commit is gone from the repository"
    assert _git_out(run, "rev-parse", "--verify", f"{BRANCH}^{{commit}}") == commit
    if indexed is not None:
        assert index.read_bytes() == indexed, "the worktree's index was put back"


def test_a_session_its_run_settled_keeps_its_commit_through_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "clean")
    commit = _ended_under_its_run(run, monkeypatch)
    _resumed_keeps(run, monkeypatch, commit)


def test_a_kill_between_the_commit_and_the_end_record_keeps_the_commit_through_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "clean")
    commit = _killed_after_the_commit(run, monkeypatch)
    _resumed_keeps(run, monkeypatch, commit)


@pytest.mark.parametrize("killed", ["after_the_end_record", "before_the_end_record"])
def test_the_attempt_restarted_after_such_a_resume_has_one_commit_and_no_ref_left_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int], killed: str
) -> None:
    """The restarted attempt's commit replaces the one its session's end never recorded."""
    run = Run(tmp_path, "clean")
    first = (
        _ended_under_its_run(run, monkeypatch)
        if killed == "after_the_end_record"
        else _killed_after_the_commit(run, monkeypatch)
    )
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
    finally:
        loop.close()
    again = Rig(run.run.run_dir).open()
    try:
        report = run.dispatcher(monkeypatch).run(run.request(), again._spawned)
    finally:
        again.close()
    second = report.attempt_commit
    assert second is not None and second != first
    on_branch = _git_out(run, "rev-list", f"master..{BRANCH}").split()
    assert on_branch == [second], "the attempt has more than one commit on its branch"
    holding = _git_out(run, "for-each-ref", "--contains", first, "--format=%(refname)")
    assert holding == "", f"a ref still holds the superseded commit: {holding}"


# -- rows the mutations asked for --------------------------------------------------------------


def test_a_line_an_earlier_resume_wrote_rewritten_after_it_died_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """After the session's start, so its start record cannot tell: only the account's digest."""
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    _resume(run, monkeypatch).close()
    data = run.log_path.read_bytes()
    at = data.rindex(b'"seconds":0.1')
    with run.log_path.open("r+b") as out:
        out.seek(at)
        out.write(b'"seconds":0.2')
    incidents, halted, _ = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents
    assert halted


def test_a_start_record_that_leaves_one_held_record_out_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    base_record = json.loads(_baseline(run).read_text())
    (named,) = [n for n in base_record["records"] if n.endswith("events.jsonl")]
    del base_record["records"][named]
    _baseline(run).write_text(json.dumps(base_record))
    incidents, halted, details = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents
    assert "does not name it" in details
    assert halted


def test_a_session_that_changes_the_log_and_puts_it_back_is_refused_at_its_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    def changed_and_back(run: Run) -> None:
        first = run.log_path.read_bytes()[:1]
        with run.log_path.open("r+b") as out:
            out.write(b"X")
        with run.log_path.open("r+b") as out:
            out.write(first)

    run, raised = _session_meanwhile(tmp_path, monkeypatch, changed_and_back)
    assert raised is not None, "a held record changed and put back went unrefused"
    assert "events.jsonl" in json.dumps(getattr(raised, "context", {})), raised


def test_a_hard_link_to_the_log_left_in_the_worktree_before_the_session_is_never_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """There before the spawn, so nothing about the record changes while the session runs."""
    run = Run(tmp_path, "clean")
    worktree = run.run.open_subtask("s1")
    link = worktree / "modules" / "power" / "events_link.jsonl"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.link(run.log_path, link)
    loop = Rig(run.run.run_dir).open()
    raised: BaseException | None = None
    try:
        try:
            run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
        except Exception as exc:  # noqa: BLE001 - its context is asserted below
            raised = exc
    finally:
        loop.close()
    assert raised is not None, "a second name for the log in the worktree went unrefused"
    assert str(link) in json.dumps(getattr(raised, "context", {})), raised
    assert not any(f.endswith("events_link.jsonl") for f in _branch_files(run))


def test_a_session_killed_after_its_commit_is_read_as_one_its_run_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """Its end ran but for its record: what that end showed is derived again at the resume."""
    run = Run(tmp_path, "clean")
    _killed_after_the_commit(run, monkeypatch)
    seen: list[Any] = []
    real = dispatch.ClaudeDispatcher.stop_leftovers

    def kept(self: dispatch.ClaudeDispatcher) -> Any:  # noqa: ANN401
        found = real(self)
        seen.extend(found)
        return found

    monkeypatch.setattr(dispatch.ClaudeDispatcher, "stop_leftovers", kept)
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
    finally:
        loop.close()
    (left,) = seen
    assert left.session_id == run.session_dir().name
    assert left.taken_up
