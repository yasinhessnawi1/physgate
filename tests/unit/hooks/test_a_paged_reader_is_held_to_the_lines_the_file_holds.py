"""A required file is read when every line holding content is covered, decided from its bytes.

The Read tool reports one line more than a file holds when the file ends in a newline:
the empty line after the last one, shown only to a read that runs past the end. A reader
paging to the file's last line was refused for that line alone (a real review, 4,881
lines against a reported 4,882), so it is not required. A file without a final newline
has no such line, and every line through the last is required. What the reader reports
as the total plays no part. A refusal names the lines still unread, file by file.
"""

from __future__ import annotations

from pathlib import Path

from hook_helpers import SESSION, bash, event, write_config

from physgate.hooks import reading
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.runtime import Decision


def _config(tmp_path: Path, *files: Path) -> SessionConfig:
    _, _, config = write_config(tmp_path, required_reading=[str(f) for f in files])
    return config


def _read(config: SessionConfig, path: Path, start: int, num: int, total: int) -> None:
    done = reading.post_tool_use(
        HookInput.model_validate(
            event(
                "PostToolUse",
                session_id=SESSION,
                tool_name="Read",
                tool_input={"file_path": str(path)},
                tool_response={
                    "type": "text",
                    "file": {
                        "filePath": str(path),
                        "content": "...",
                        "numLines": num,
                        "startLine": start,
                        "totalLines": total,
                    },
                },
            )
        ),
        config,
    )
    assert done.allow


def _bash(config: SessionConfig) -> Decision:
    return reading.pre_tool_use(HookInput.model_validate(bash("ls", session_id=SESSION)), config)


def test_a_file_ending_in_a_newline_is_read_through_its_last_line(tmp_path: Path) -> None:
    path = tmp_path / "transcript.md"
    path.write_text("".join(f"line {n}\n" for n in range(1, 11)))  # 10 lines, total 11
    config = _config(tmp_path, path)
    _read(config, path, 1, 6, 11)
    _read(config, path, 7, 4, 11)  # paged to line 10, the last that holds content
    assert _bash(config).allow


def test_a_file_without_a_final_newline_needs_its_last_line_too(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("\n".join(f"line {n}" for n in range(1, 11)))  # 10 lines, no final newline
    config = _config(tmp_path, path)
    _read(config, path, 1, 9, 10)
    refused = _bash(config)
    assert not refused.allow and "lines not yet read: 10 of 10" in refused.reason
    _read(config, path, 10, 1, 10)
    assert _bash(config).allow


def test_the_reader_s_reported_total_decides_nothing(tmp_path: Path) -> None:
    path = tmp_path / "spec.md"
    path.write_text("a\nb\nc\n")
    config = _config(tmp_path, path)
    _read(config, path, 1, 2, 2)  # a reader that claims the file has two lines
    refused = _bash(config)
    assert not refused.allow and "lines not yet read: 3 of 3" in refused.reason
    _read(config, path, 3, 1, 999)
    assert _bash(config).allow


def test_the_refusal_names_the_unread_ranges_of_each_file(tmp_path: Path) -> None:
    first, second = tmp_path / "one.md", tmp_path / "two.md"
    first.write_text("".join(f"{n}\n" for n in range(1, 21)))
    second.write_text("x\ny\n")
    config = _config(tmp_path, first, second)
    _read(config, first, 1, 5, 21)
    _read(config, first, 9, 4, 21)
    reason = _bash(config).reason
    assert f"{first} (lines not yet read: 6-8, 13-20 of 20)" in reason
    assert f"{second} (lines not yet read: 1-2 of 2)" in reason


def test_a_read_from_offset_zero_counts_from_the_first_line(tmp_path: Path) -> None:
    path = tmp_path / "t.md"
    path.write_text("".join(f"{n}\n" for n in range(1, 9)))
    config = _config(tmp_path, path)
    _read(config, path, 0, 4, 9)  # numbered 0..3, shows lines 1..4
    _read(config, path, 5, 4, 9)
    assert _bash(config).allow


def test_an_empty_line_inside_the_file_is_still_required(tmp_path: Path) -> None:
    path = tmp_path / "gaps.md"
    path.write_text("a\n\nb\n")
    config = _config(tmp_path, path)
    _read(config, path, 1, 1, 4)
    _read(config, path, 3, 1, 4)
    assert "lines not yet read: 2 of 3" in _bash(config).reason


def test_lines_holding_content_counted_from_the_bytes() -> None:
    assert reading.content_lines(b"") == 0
    assert reading.content_lines(b"a") == 1
    assert reading.content_lines(b"a\n") == 1
    assert reading.content_lines(b"a\nb") == 2
    assert reading.content_lines(b"a\n\n") == 2
