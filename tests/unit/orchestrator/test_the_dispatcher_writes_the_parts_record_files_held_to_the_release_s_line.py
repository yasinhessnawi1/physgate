"""The dispatcher writes the parts record's files for a session, held to the release's line.

Before anything is written the record's bytes are held to the digest and length the request
carries (the release line's); the files are the rendering of those bytes, written new into the
session's own directory and read back whole. A request with no record writes nothing, and a
record that is not one is refused as such, never shown.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from physgate.orchestrator.dispatch import ClaudeDispatcher, parts_record_dir
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.parts_reading import parts_files
from physgate.orchestrator.protocols import IssuedState

RECORD = json.dumps(
    {
        "components": [
            {
                "node": "power.motor",
                "label": "the motor",
                "choice": "make",
                "declared": {},
                "texts": ["printed in PETG"],
            }
        ]
    },
    sort_keys=True,
    separators=(",", ":"),
).encode()


def _held(data: bytes = RECORD) -> IssuedState:
    return IssuedState(
        text=data.decode(), sha256=hashlib.sha256(data).hexdigest(), length=len(data)
    )


def _request(held: IssuedState | None) -> Any:  # noqa: ANN401
    return SimpleNamespace(parts_record=held, subtask_id="s1")


def test_the_files_are_the_rendering_of_the_record_written_in_the_sessions_own_directory(
    tmp_path: Path,
) -> None:
    written = ClaudeDispatcher._issue_parts_record(_request(_held()), tmp_path)  # noqa: SLF001
    files = parts_files(RECORD)
    assert [p.name for p in written] == [name for name, _ in files]
    assert all(p.parent == parts_record_dir(tmp_path) for p in written)
    assert [p.read_bytes() for p in written] == [data for _, data in files]


def test_a_request_with_no_record_writes_nothing(tmp_path: Path) -> None:
    assert ClaudeDispatcher._issue_parts_record(_request(None), tmp_path) == []  # noqa: SLF001
    assert not parts_record_dir(tmp_path).exists()


@pytest.mark.parametrize("change", ["a byte short", "another record"])
def test_a_record_that_is_not_the_one_the_release_named_is_refused_and_nothing_is_written(
    tmp_path: Path, change: str
) -> None:
    other = RECORD[:-1] if change == "a byte short" else RECORD.replace(b"PETG", b"steel")
    held = _held().model_copy(update={"text": other.decode()})
    with pytest.raises(InvocationError, match="parts record"):
        ClaudeDispatcher._issue_parts_record(_request(held), tmp_path)  # noqa: SLF001
    assert not parts_record_dir(tmp_path).exists()


def test_a_record_that_is_not_the_parts_record_is_refused(tmp_path: Path) -> None:
    junk = b'{"components": 3}'
    with pytest.raises(InvocationError, match="parts record"):
        ClaudeDispatcher._issue_parts_record(_request(_held(junk)), tmp_path)  # noqa: SLF001
    assert not parts_record_dir(tmp_path).exists()


def test_the_files_are_written_new_and_never_over_another_session_s(tmp_path: Path) -> None:
    ClaudeDispatcher._issue_parts_record(_request(_held()), tmp_path)  # noqa: SLF001
    with pytest.raises(FileExistsError):
        ClaudeDispatcher._issue_parts_record(_request(_held()), tmp_path)  # noqa: SLF001


def test_a_file_that_reads_back_as_another_than_was_written_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Path.read_bytes

    def another(self: Path) -> bytes:
        data = real(self)
        return data + b"x" if self.parent == parts_record_dir(tmp_path) else data

    monkeypatch.setattr(Path, "read_bytes", another)
    with pytest.raises(InvocationError, match="not the one rendered"):
        ClaudeDispatcher._issue_parts_record(_request(_held()), tmp_path)  # noqa: SLF001
