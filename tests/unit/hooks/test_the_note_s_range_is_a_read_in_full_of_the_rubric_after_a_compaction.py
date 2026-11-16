"""The range the note names for the rubric is, read with the Read tool, a read in full.

After a compaction a reviewer is told to read the rubric again from offset 1 with a limit of
the rubric's lines, as the Read tool counts them. Measured on both pinned binaries: the Read
tool counts one line more than a file's newlines, so the empty line after a final newline is
counted (a file of 19 newlines reports 20 lines in all, with or without a final newline), and a
read from line 1 with a limit returns the lesser of the limit and that count. A Read with that
range is new to the binary's own record of what was read, so it returns the file, not a note
that it is unchanged, and the reading hook records it. These rows hold the count, and hold
that a read by it is a read in full of a rubric with and without a final newline, at the epoch
of the last compaction; one line fewer is not, for a rubric without a final newline.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import event, write_config

import physgate.reviewers.claude as claude
from physgate.hooks import reading
from physgate.hooks.config import HookInput, SessionConfig

#: Nineteen newlines, ending on one; and the same with a twentieth line that has none.
ENDS_ON_A_NEWLINE = "".join(f"item {n}\n" for n in range(1, 20))
NO_FINAL_NEWLINE = ENDS_ON_A_NEWLINE + "item 20"


def _counted() -> Callable[[bytes], int]:
    count = getattr(claude, "read_tool_lines", None)
    assert count is not None, "nothing counts the rubric's lines for the note"
    return count  # type: ignore[no-any-return]


def test_the_rubric_s_lines_are_counted_as_the_read_tool_counts_them() -> None:
    count = _counted()
    # Measured on both pins: 20 lines in all for 19 newlines, with or without a final one.
    assert count(ENDS_ON_A_NEWLINE.encode()) == 20
    assert count(NO_FINAL_NEWLINE.encode()) == 20
    assert count(b"one line") == 1
    assert count(b"one line\n") == 2


def _compacted(tmp_path: Path, text: str) -> tuple[SessionConfig, Path]:
    read = tmp_path / "read"
    read.mkdir()
    rubric = read / "rubric.md"
    rubric.write_text(text)
    _, _, config = write_config(
        tmp_path,
        profile="reviewer",
        role=None,
        required_reading=[str(rubric)],
        after_compaction=[str(rubric)],
        compaction_note="N",
    )
    start = HookInput.model_validate(event("SessionStart", source="compact"))
    assert reading.session_start(start, config).context == "N"
    return config, rubric


def _read_by_range(config: SessionConfig, rubric: Path, limit: int) -> None:
    """A Read from offset 1 with ``limit``, its result as both pins return it."""
    total = rubric.read_bytes().count(b"\n") + 1
    response: dict[str, Any] = {
        "type": "text",
        "file": {
            "filePath": str(rubric),
            "content": "...",
            "numLines": min(limit, total),
            "startLine": 1,
            "totalLines": total,
        },
    }
    hook_input = HookInput.model_validate(
        event(
            "PostToolUse",
            tool_name="Read",
            tool_input={"file_path": str(rubric), "offset": 1, "limit": limit},
            tool_response=response,
        )
    )
    assert reading.post_tool_use(hook_input, config).allow


def _verdict_allowed(config: SessionConfig) -> bool:
    hook_input = HookInput.model_validate(event(tool_name="StructuredOutput", tool_input={}))
    return reading.pre_tool_use(hook_input, config).allow


@pytest.mark.parametrize("text", [ENDS_ON_A_NEWLINE, NO_FINAL_NEWLINE], ids=["newline", "none"])
def test_a_read_by_the_note_s_range_is_a_read_in_full_after_a_compaction(
    tmp_path: Path, text: str
) -> None:
    config, rubric = _compacted(tmp_path, text)
    assert not _verdict_allowed(config), "the rubric counts as read again before any read"
    _read_by_range(config, rubric, _counted()(rubric.read_bytes()))
    assert _verdict_allowed(config), "a read by the note's range is not a read in full"


def test_one_line_fewer_is_not_a_read_in_full_of_a_rubric_without_a_final_newline(
    tmp_path: Path,
) -> None:
    config, rubric = _compacted(tmp_path, NO_FINAL_NEWLINE)
    _read_by_range(config, rubric, _counted()(rubric.read_bytes()) - 1)
    assert not _verdict_allowed(config)


def test_the_note_names_the_range_it_is_given() -> None:
    assert "lines" in inspect.signature(claude.compaction_note).parameters, (
        "the note is not given the rubric's lines"
    )
    note = claude.compaction_note(Path("/r/read"), (), lines=20).replace("\n", " ")
    assert (
        "/r/read/rubric.md again in full with the Read tool, from offset 1 with limit 20;" in note
    )
