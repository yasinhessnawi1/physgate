"""What a blind check's kept session shows it answered, derived from its stream alone.

Every blind check's session is kept beneath the role's withheld root, however it ended
(``<store>/<role>/withheld/check/<session id>/``): its stream (``stdout.jsonl``, the binary's
own record of every message and tool call) and its record (``record.json``: how it ended,
what it spent, whether a held-out canary showed). A session the runner could not record is
kept as ``unrecorded-<hex>``: its check raised before it took any answer.

**The answer** is the content of the session's last write to its answer file by its file-write
tool whose result was not an error, read from the tool call in the stream. Its model and binary
are the ones the stream names as it starts; when it was written is the time the stream gives
that write's result. A whole read of the tasks file it was given, where the stream holds one,
is kept too, so the version it was given can be held to it by content. Where a tool call names
the answer file after that write (a shell command reading or changing it, an edit), what the
check read at its end cannot be told from the stream alone, and the session says so. Where a
session named its answer file but never wrote it by its file-write tool, whether it answered
cannot be told, and the session is refused.

Nothing here opens a tier: the stream is read as bytes and JSON, and what it holds is returned
to the import alone (:func:`.checks.import_check`), which prints counts and digests only.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from physgate.evaluation.tiers.check_tasks import answers_of
from physgate.evaluation.tiers.checks import CheckError
from physgate.evaluation.tiers.store import check_evidence
from physgate.evaluation.tiers.task import Role

STREAM = "stdout.jsonl"
RECORD = "record.json"
ANSWERS = "answers.json"
TASKS = "tasks.json"
#: What the runner names a session it could not record: its check took no answer.
UNRECORDED = "unrecorded-"
#: The most bytes a kept stream is read to, and a kept record.
MOST_STREAM_BYTES = 512 * 1024 * 1024
MOST_RECORD_BYTES = 1024 * 1024
#: The tools that read a file and change nothing: naming the answer file in one is no change.
_READING = frozenset({"Read", "Glob", "Grep", "LS"})
#: The tools that write a file and say so: one whose call was refused changed nothing.
_FILE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
_CUT_OFF = "tokens_not_in_binary_totals"


def _unclear(where: str, why: str) -> CheckError:
    msg = (
        f"the kept check session {where} {why}: whether it answered, and how, cannot be told, "
        "so nothing is recorded; a person must look"
    )
    return CheckError(msg, refused_because="check_session_unclear")


@dataclass(frozen=True)
class KeptAnswer:
    """What one kept session shows of its answer; the import's alone, never printed."""

    session_id: str
    stream_sha256: str
    #: The answer file's content as the session last wrote it, parsed; ``None`` without one.
    answer: dict[str, dict[str, bool]] | None
    #: Whether the session's record says no held-out canary showed: an answer the check took.
    took: bool
    model: str
    claude_version: str
    #: When the answer was written, UTC to the second; empty without an answer.
    written_at: str
    #: The tasks file as the session read it whole, parsed; ``None`` where the stream holds no
    #: whole read of it.
    tasks_read: object | None
    #: A tool call named the answer file after its last write.
    touched_after: bool
    #: The session's spend, as the check printed it from the record.
    spent: dict[str, Any]


def _read(path: Path, most: int) -> bytes | None:
    """``path``'s bytes, a plain file of its own read without following a link; ``None`` if absent.

    Raises:
        CheckError: it is a link, not a plain file of its own, or larger than ``most``.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _unclear(path.parent.name, f"cannot be read ({exc.strerror})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _unclear(path.parent.name, f"holds a {path.name} that is not a file of its own")
        with os.fdopen(os.dup(fd), "rb") as handle:
            data = handle.read(most + 1)
    finally:
        os.close(fd)
    if len(data) > most:
        raise _unclear(path.parent.name, f"holds a {path.name} larger than any is")
    return data


def _lines(stream: bytes, where: str) -> list[dict[str, Any]]:
    """The stream's lines as JSON objects; only a last line cut off as it ended is passed over."""
    raw = [line for line in stream.split(b"\n") if line.strip()]
    found: list[dict[str, Any]] = []
    for at, line in enumerate(raw):
        try:
            shape = json.loads(line)
        except ValueError:
            if at == len(raw) - 1:
                break
            raise _unclear(where, f"has a line {at} of its stream that is not one") from None
        if isinstance(shape, dict):
            found.append(shape)
    return found


def _content(line: dict[str, Any]) -> list[dict[str, Any]]:
    message = line.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [c for c in content if isinstance(c, dict)] if isinstance(content, list) else []


def _input(call: dict[str, Any]) -> dict[str, Any]:
    given = call.get("input")
    return given if isinstance(given, dict) else {}


def _utc(stamp: object) -> str | None:
    if not isinstance(stamp, str):
        return None
    try:
        at = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if at.tzinfo is None:
        return None
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _whole_read(result: object) -> object | None:
    """The file a read tool's result holds, parsed, if it is the whole file; else ``None``."""
    if not isinstance(result, dict):
        return None
    file = result.get("file")
    if not isinstance(file, dict) or not isinstance(file.get("content"), str):
        return None
    lines, total = file.get("numLines"), file.get("totalLines")
    if file.get("startLine") != 1 or not isinstance(total, int) or lines != total:
        return None
    try:
        parsed: object = json.loads(file["content"])
    except ValueError:
        return None
    return parsed


def _spent(record: dict[str, Any]) -> dict[str, Any]:
    """The spend the check printed of its session, from the session's record, as it printed it."""
    spent = {key: record.get(key) for key in ("end", "tokens", "cap", "wall_clock_s")}
    if record.get(_CUT_OFF):
        spent[_CUT_OFF] = record[_CUT_OFF]
    return spent


def read_kept(directory: Path) -> KeptAnswer:
    """What the kept session in ``directory`` shows of its answer.

    Raises:
        CheckError: its record or stream is not there or cannot be read whole, they are not one
            session's, or it named its answer file without one write of it by its file-write
            tool that landed (``check_session_unclear``).
    """
    where = directory.name
    record_bytes = _read(directory / RECORD, MOST_RECORD_BYTES)
    stream = _read(directory / STREAM, MOST_STREAM_BYTES)
    if record_bytes is None or stream is None:
        raise _unclear(where, "holds no record or no stream")
    try:
        record = json.loads(record_bytes)
    except ValueError:
        raise _unclear(where, "holds a record that is not one") from None
    if not isinstance(record, dict) or record.get("session_id") != where:
        raise _unclear(where, "holds a record of another session")
    lines = _lines(stream, where)
    start = next((x for x in lines if (x.get("type"), x.get("subtype")) == ("system", "init")), {})
    if start.get("session_id") != where:
        raise _unclear(where, "has a stream that does not start as this session")
    cwd = start.get("cwd")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        raise _unclear(where, "has a stream that names no directory it worked in")

    def names(path: object, name: str) -> bool:
        return isinstance(path, str) and os.path.normpath(os.path.join(cwd, path)) == (
            os.path.normpath(os.path.join(cwd, name))
        )

    calls: list[dict[str, Any]] = []
    results: dict[str, tuple[bool, str | None, object]] = {}
    for line in lines:
        for block in _content(line):
            if line.get("type") == "assistant" and block.get("type") == "tool_use":
                calls.append(block)
            if line.get("type") == "user" and block.get("type") == "tool_result":
                results[str(block.get("tool_use_id"))] = (
                    block.get("is_error") is True,
                    _utc(line.get("timestamp")),
                    line.get("tool_use_result"),
                )
    landed: int | None = None
    tasks_read: object | None = None
    for at, call in enumerate(calls):
        given = _input(call)
        result = results.get(str(call.get("id")))
        if result is None or result[0]:
            continue
        if call.get("name") == "Write" and names(given.get("file_path"), ANSWERS):
            if isinstance(given.get("content"), str):
                landed = at
        elif call.get("name") == "Read" and names(given.get("file_path"), TASKS):
            whole = _whole_read(result[2])
            tasks_read = whole if whole is not None else tasks_read

    def changes(at: int, call: dict[str, Any]) -> bool:
        """Whether a call other than the landed write named the answer file and may change it."""
        if at == landed or call.get("name") in _READING:
            return False
        if ANSWERS not in json.dumps(_input(call)):
            return False
        result = results.get(str(call.get("id")))
        # A file tool's call that was refused changed nothing; anything else may have.
        return not (call.get("name") in _FILE_TOOLS and result is not None and result[0])

    named = [at for at, call in enumerate(calls) if changes(at, call)]
    spent = _spent(record)
    stream_sha256 = hashlib.sha256(stream).hexdigest()
    took = record.get("held_out_seen") is False
    if landed is None:
        if named:
            raise _unclear(where, "named its answer file but never wrote it by its file-write tool")
        return KeptAnswer(where, stream_sha256, None, took, "", "", "", None, False, spent)
    call = calls[landed]
    answer = answers_of(str(_input(call)["content"]).encode())
    if answer is None:
        return KeptAnswer(where, stream_sha256, None, took, "", "", "", None, False, spent)
    model, binary = start.get("model"), start.get("claude_code_version")
    written = results[str(call.get("id"))][1]
    if not isinstance(model, str) or not model or not isinstance(binary, str) or not binary:
        raise _unclear(where, "has a stream that does not name its model and binary")
    if written is None:
        raise _unclear(where, "has a stream that does not say when its answer was written")
    return KeptAnswer(
        session_id=where,
        stream_sha256=stream_sha256,
        answer=answer,
        took=took,
        model=model,
        claude_version=binary,
        written_at=written,
        tasks_read=tasks_read,
        touched_after=any(at > landed for at in named),
        spent=spent,
    )


def kept_answers(store: Path, role: Role) -> list[KeptAnswer]:
    """What every kept blind-check session of the role shows of its answer, by session id.

    A session the runner could not record (``unrecorded-``) took no answer and is passed over.

    Raises:
        CheckError: an entry of the kept sessions is not one, or a session cannot be read
            (:func:`read_kept`).
    """
    root = check_evidence(store, role)
    try:
        names = sorted(os.listdir(root))
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise _unclear("folder", f"cannot be listed ({exc.strerror})") from None
    found: list[KeptAnswer] = []
    for name in names:
        here = root / name
        if here.is_symlink() or not here.is_dir():
            raise _unclear(name, "is not a directory of its own")
        if name.startswith(UNRECORDED):
            continue
        found.append(read_kept(here))
    return found


__all__ = ["KeptAnswer", "kept_answers", "read_kept"]
