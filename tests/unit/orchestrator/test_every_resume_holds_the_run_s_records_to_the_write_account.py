"""Every resume holds the run's records to the write account, whatever it finds left.

The account names every append before it is made, and its completion after. A resume walks every
held record along it, with or without a session left running: a line no orchestrator named halts
the run, after its end as before it. A write the account names complete must be there as written,
so a leftover that cuts the run's last line is found; a write its writer died in before its
completion covers its bytes only if they are all there, and nothing if they are not.

At a session's end each held record has exactly one name, wherever a second one was made. And a
forgery refused when the record opens is put on the record where the event log can still take a
line, before the refusal: an incident and a halt.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from loop_fakes import Rig
from test_a_session_s_hooks_never_fork_the_run_s_own_records import (
    INSTALL_BIN,
    Run,
    _incidents,
    _orchestrator_dies,
    _resume,
    leftovers,
)

from physgate.orchestrator.events import (
    EventLog,
    Halted,
    Incident,
    InstallChecked,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.merge import GitMerger

__all__ = ["leftovers"]


def _account(run: Run) -> Path:
    return run.run.run_dir / "writes.jsonl"


def _left(run: Run, monkeypatch: pytest.MonkeyPatch, pids: list[int]) -> None:
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    pids.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))


def _judged(run: Run, monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], bool, str]:
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        details = " | ".join(e.detail for e in read_events(run.log_path) if isinstance(e, Incident))
        return _incidents(run.log_path), loop.state.halted is not None, details
    finally:
        loop.close()


def _line(run: Run, message_id: str) -> bytes:
    """A valid line of the record's form, returned and not written."""
    scratch = run.run.run_dir.parent / "scratch_events.jsonl"
    shutil.copy(run.log_path, scratch)
    forger = EventLog(scratch, run_id="run-1", gate_mode="on")
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 0}
    usage |= {"cache_read_input_tokens": 0}
    forger.emit(TokensUsed, attribution="session:x", message_id=message_id, usage=usage)
    forger.close()
    data = scratch.read_bytes()[run.log_path.stat().st_size :]
    scratch.unlink()
    return data


def _intent(run: Run, payload: bytes) -> bytes:
    st = os.stat(run.log_path)
    line = {
        "record": "events.jsonl",
        "identity": [st.st_dev, st.st_ino],
        "offset": st.st_size,
        "length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    return json.dumps(line, separators=(",", ":")).encode() + b"\n"


def _append(path: Path, data: bytes) -> None:
    with path.open("ab") as out:
        out.write(data)


# -- every resume walks the account (O1) -----------------------------------------------------------


def test_a_line_appended_after_the_run_is_done_halts_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "clean")
    rig = Rig(run.run.run_dir, dispatcher=run.dispatcher(monkeypatch))  # type: ignore[arg-type]
    rig.merger = GitMerger(run.run, removal_timeout_s=60.0)  # type: ignore[assignment]
    loop = rig.open()
    try:
        loop.record.emit(
            InstallChecked(
                **loop.record.envelope(),
                path=str(INSTALL_BIN),
                action="checked",
                seconds=0.1,
                entries=1,
            )
        )
        loop.run()
        assert loop.state.halted is None
    finally:
        loop.close()
    _append(run.log_path, _line(run, "m-after-done"))
    incidents, halted, details = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents, details
    assert "events.jsonl" in details
    assert halted


def test_a_line_appended_with_no_leftover_halts_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "clean")
    _append(run.log_path, _line(run, "m-no-leftover"))
    incidents, halted, _ = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents
    assert halted


# -- a write the account names complete (Y1) -------------------------------------------------------


def test_the_run_s_last_line_cut_by_a_leftover_halts_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """An earlier resume wrote its first line and died; the leftover cut that line."""
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    _resume(run, monkeypatch).close()
    data = run.log_path.read_bytes()
    os.truncate(run.log_path, data.rstrip(b"\n").rfind(b"\n") + 1)
    incidents, halted, details = _judged(run, monkeypatch)
    assert "run_records_changed" in incidents, details
    assert halted


def test_a_crash_after_the_data_and_before_its_completion_resumes_with_the_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    payload = _line(run, "m-written-not-completed")
    _append(_account(run), _intent(run, payload))
    _append(run.log_path, payload)
    incidents, halted, details = _judged(run, monkeypatch)
    assert "run_records_changed" not in incidents, details
    assert not halted
    assert any(
        isinstance(e, TokensUsed) and e.message_id == "m-written-not-completed"
        for e in read_events(run.log_path)
    )
    again, halted_again, _ = _judged(run, monkeypatch)
    assert "run_records_changed" not in again
    assert not halted_again


def test_a_crash_mid_way_through_the_data_resumes_without_the_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    payload = _line(run, "m-torn")
    _append(_account(run), _intent(run, payload))
    _append(run.log_path, payload[: len(payload) // 2])
    incidents, halted, details = _judged(run, monkeypatch)
    assert "run_records_changed" not in incidents, details
    assert not halted


def test_every_append_s_completion_is_in_the_account_after_its_bytes(
    tmp_path: Path, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "clean")
    lines = [json.loads(x) for x in _account(run).read_bytes().splitlines()]
    intents = [x for x in lines if "sha256" in x and "completed" not in x]
    completed = [x for x in lines if "completed" in x]
    assert intents and len(completed) == len(intents)
    for intent in intents:
        at = lines.index(intent)
        done = {"completed": intent["record"], "offset": intent["offset"]}
        assert any(
            {k: x[k] for k in ("completed", "offset") if k in x} == done for x in lines[at + 1 :]
        )


# -- one name per held record at a session's end (Y2) ----------------------------------------------


@pytest.mark.parametrize("where", ["run_dir", "sessions_dir", "store"])
def test_a_second_name_made_before_the_spawn_anywhere_is_refused_at_the_session_s_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int], where: str
) -> None:
    run = Run(tmp_path, "clean")
    rd = run.run.run_dir
    link = {
        "run_dir": rd / "kept.jsonl",
        "sessions_dir": rd / "sessions" / "kept.jsonl",
        "store": rd / "store" / "kept.jsonl",
    }[where]
    link.parent.mkdir(parents=True, exist_ok=True)
    os.link(run.log_path, link)
    loop = Rig(rd).open()
    raised: BaseException | None = None
    try:
        try:
            run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
        except Exception as exc:  # noqa: BLE001 - its context is asserted below
            raised = exc
    finally:
        loop.close()
    assert raised is not None, "a held record with a second name passed the session's end"
    assert "events.jsonl" in json.dumps(getattr(raised, "context", {})), raised


# -- a forgery refused at open is put on the record (Y3) -------------------------------------------


def _opened(run: Run, monkeypatch: pytest.MonkeyPatch) -> BaseException | None:
    try:
        _resume(run, monkeypatch).close()
    except Exception as exc:  # noqa: BLE001 - asserted by the caller
        return exc
    return None


def _on_the_record(run: Run, named: str) -> None:
    events = read_events(run.log_path)
    incidents = [e for e in events if isinstance(e, Incident)]
    assert [e.cause for e in incidents][-1:] == ["run_records_changed"]
    assert named in incidents[-1].detail
    assert isinstance(events[-1], Halted)


def test_a_forged_ledger_line_refused_at_open_is_an_incident_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    ledger = run.run.run_dir / "ledger.jsonl"
    _append(ledger, ledger.read_bytes().splitlines(keepends=True)[-1])
    raised = _opened(run, monkeypatch)
    assert raised is not None
    assert "ledger.jsonl" in str(raised) + json.dumps(getattr(raised, "context", {}))
    _on_the_record(run, "ledger.jsonl")
    assert _opened(run, monkeypatch) is not None
    assert len([e for e in read_events(run.log_path) if isinstance(e, Halted)]) == 1


def test_a_forged_queue_line_refused_at_open_is_an_incident_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    _append(run.run.run_dir / "queue.jsonl", b'{"x":1}\n')
    raised = _opened(run, monkeypatch)
    assert raised is not None
    assert "queue.jsonl" in str(raised) + json.dumps(getattr(raised, "context", {}))
    _on_the_record(run, "queue.jsonl")


def test_a_forged_log_line_refused_at_open_names_the_log_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The log itself refuses to open: no line can be put on it, so the error names it."""
    run = Run(tmp_path, "leftover")
    _left(run, monkeypatch, leftovers)
    data = run.log_path.read_bytes()
    _append(run.log_path, data.splitlines(keepends=True)[-1])
    held = run.log_path.read_bytes()
    raised = _opened(run, monkeypatch)
    assert raised is not None
    assert "events.jsonl" in str(raised) + json.dumps(getattr(raised, "context", {}))
    assert run.log_path.read_bytes() == held
