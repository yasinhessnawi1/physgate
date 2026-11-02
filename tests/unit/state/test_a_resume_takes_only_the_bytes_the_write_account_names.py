"""The run's write account names every append before it is made, and nothing else counts.

Each held record's writer names, in the account, the record's file, the offset, the length and
the digest of what it is about to write, and syncs that before it writes. A resume walks the
record from its first byte along those lines: a line at the walk's place whose bytes are there
moves it on, a line whose bytes are not is a write its writer died in, and a line anywhere else
or on another file refuses. Whatever the walk does not reach, before the resume opened the
record, is no orchestrator's.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from physgate.orchestrator.events import EventLog, RunStarted, SubtaskPlanned
from physgate.orchestrator.held_records import unaccounted
from physgate.state.held_file import HeldFile
from physgate.state.write_account import Completed, Intent, Settled, WriteAccount, read_account


def _logged(run_dir: Path) -> Path:
    account = WriteAccount(run_dir / "writes.jsonl")
    log = EventLog(run_dir / "events.jsonl", run_id="r", gate_mode="on", account=account)
    log.emit(RunStarted, config_sha256="d" * 64)
    log.emit(SubtaskPlanned, subtask_id="s1", spec_path="p", assigned_role="r", module_dir="m")
    log.close()
    account.close()
    return run_dir / "events.jsonl"


def _judged(path: Path) -> str | None:
    entries, problem = read_account(path.with_name("writes.jsonl"))
    return unaccounted(HeldFile(path), entries, problem)


def test_every_append_is_named_before_it_is_made_and_the_walk_reaches_the_end(
    tmp_path: Path,
) -> None:
    path = _logged(tmp_path)
    entries, problem = read_account(tmp_path / "writes.jsonl")
    assert problem is None
    first = len(path.read_bytes().splitlines()[0]) + 1
    assert [e.offset for e in entries if isinstance(e, Intent)] == [0, first]
    assert [e.offset for e in entries if isinstance(e, Completed)] == [0, first]
    kinds = [type(e).__name__ for e in entries]
    assert kinds == ["Intent", "Completed", "Intent", "Completed"], kinds
    assert _judged(path) is None


def test_a_line_at_another_offset_refuses(tmp_path: Path) -> None:
    path = _logged(tmp_path)
    account = tmp_path / "writes.jsonl"
    lines = [x for x in account.read_bytes().splitlines() if b'"identity"' in x]
    second = json.loads(lines[1])
    second["offset"] += 1
    account.write_bytes(lines[0] + b"\n" + json.dumps(second).encode() + b"\n")
    why = _judged(path)
    assert why is not None and "where the orchestrators' writes had reached" in why


def test_a_line_on_another_file_refuses(tmp_path: Path) -> None:
    path = _logged(tmp_path)
    copy = path.with_name("events.copy")
    shutil.copy2(path, copy)
    os.replace(copy, path)
    why = _judged(path)
    assert why is not None and "another file" in why


def test_a_write_its_writer_died_in_covers_nothing_and_the_next_follows_it(
    tmp_path: Path,
) -> None:
    path = _logged(tmp_path)
    st = os.stat(path)
    dead = {
        "record": "events.jsonl",
        "identity": [st.st_dev, st.st_ino],
        "offset": st.st_size,
        "length": 4,
        "sha256": hashlib.sha256(b"lost").hexdigest(),
    }
    with (tmp_path / "writes.jsonl").open("ab") as out:
        out.write(json.dumps(dead).encode() + b"\n")
    assert _judged(path) is None
    account = WriteAccount(tmp_path / "writes.jsonl")
    log = EventLog(path, run_id="r", gate_mode="on", account=account)
    log.emit(SubtaskPlanned, subtask_id="s2", spec_path="p", assigned_role="r", module_dir="m")
    log.close()
    account.close()
    assert _judged(path) is None


def test_bytes_no_line_names_refuse(tmp_path: Path) -> None:
    path = _logged(tmp_path)
    with path.open("ab") as out:
        out.write(b'{"seq": 2}\n')
    why = _judged(path)
    assert why is not None and "no write the write account names" in why


def test_a_torn_last_line_is_cut_and_a_line_of_no_form_is_named(tmp_path: Path) -> None:
    path = _logged(tmp_path)
    account = tmp_path / "writes.jsonl"
    whole = account.read_bytes()
    account.write_bytes(whole + b'{"record": "ev')
    WriteAccount(account).close()
    assert account.read_bytes() == whole
    account.write_bytes(whole + b'{"record": 1}\n')
    entries, problem = read_account(account)
    assert problem is not None and "no form" in problem
    assert _judged(path) == problem


def test_a_settle_line_reads_back_as_written(tmp_path: Path) -> None:
    account = WriteAccount(tmp_path / "writes.jsonl")
    account.settle("sid-1", "s1", 2)
    account.close()
    assert read_account(tmp_path / "writes.jsonl") == ((Settled("sid-1", "s1", 2),), None)


def _named(path: Path, offset: int, payload: bytes, *, completed: bool) -> None:
    st = os.stat(path)
    digest = hashlib.sha256(payload).hexdigest()
    intent = {
        "record": path.name,
        "identity": [st.st_dev, st.st_ino],
        "offset": offset,
        "length": len(payload),
        "sha256": digest,
    }
    done = {"completed": path.name, "offset": offset, "sha256": digest}
    with path.with_name("writes.jsonl").open("ab") as out:
        for line in (intent, done) if completed else (intent,):
            out.write(json.dumps(line).encode() + b"\n")


def test_a_write_that_died_before_its_bytes_and_was_written_again_as_it_was_covers_nothing(
    tmp_path: Path,
) -> None:
    """The next process writes the very same bytes where the dead write stood, and completes it."""
    path = _logged(tmp_path)
    at = path.stat().st_size
    payload = b'{"seq": 2}\n'
    _named(path, at, payload, completed=False)
    with path.open("ab") as out:
        out.write(payload)
    _named(path, at, payload, completed=True)
    assert _judged(path) is None


def test_a_completed_write_cut_and_written_over_where_it_stood_refuses(tmp_path: Path) -> None:
    path = _logged(tmp_path)
    data = path.read_bytes()
    at = data.rstrip(b"\n").rfind(b"\n") + 1
    os.truncate(path, at)
    payload = b'{"seq": 9}\n'
    with path.open("ab") as out:
        out.write(payload)
    _named(path, at, payload, completed=True)
    why = _judged(path)
    assert why is not None and "names complete is not there as written" in why
