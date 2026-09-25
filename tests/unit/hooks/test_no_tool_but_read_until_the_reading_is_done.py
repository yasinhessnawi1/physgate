"""No tool but Read until every required file has been read in full, by the Read tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hook_helpers import SESSION, bash, event, write_config

from physgate.hooks import reading
from physgate.hooks.config import SessionConfig
from physgate.hooks.runtime import HookInput


@pytest.fixture
def setup(tmp_path: Path) -> tuple[SessionConfig, Path, Path]:
    a = tmp_path / "standards.md"
    b = tmp_path / "spec.md"
    a.write_text("one\ntwo\nthree\n")
    b.write_text("1\n2\n3\n4\n5\n")
    _, _, config = write_config(tmp_path, required_reading=[str(a), str(b)])
    return config, a, b


def _post_read(path: Path, start: int, num: int, total: int, session: str = SESSION) -> HookInput:
    return HookInput.model_validate(
        event(
            "PostToolUse",
            session_id=session,
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
    )


def _pre(tool: str = "Bash", session: str = SESSION, **fields: Any) -> HookInput:  # noqa: ANN401
    if tool == "Bash":
        return HookInput.model_validate(bash("ls", session_id=session))
    return HookInput.model_validate(event(tool_name=tool, session_id=session, **fields))


def _read(config: SessionConfig, path: Path, start: int, num: int, total: int) -> None:
    assert reading.post_tool_use(_post_read(path, start, num, total), config).allow


def test_bash_is_refused_after_reading_one_of_two_and_allowed_after_both(
    setup: tuple[SessionConfig, Path, Path],
) -> None:
    config, a, b = setup
    first = reading.pre_tool_use(_pre(), config)
    assert not first.allow
    assert str(a) in first.reason and str(b) in first.reason
    _read(config, a, 1, 4, 4)
    second = reading.pre_tool_use(_pre(), config)
    assert not second.allow
    assert str(a) not in second.reason and str(b) in second.reason
    _read(config, b, 1, 6, 6)
    assert reading.pre_tool_use(_pre(), config).allow


def test_the_read_tool_itself_is_never_refused(setup: tuple[SessionConfig, Path, Path]) -> None:
    config, a, _ = setup
    assert reading.pre_tool_use(_pre("Read", tool_input={"file_path": str(a)}), config).allow


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit", "TaskCreate"])
def test_every_other_tool_is_refused_until_then(
    setup: tuple[SessionConfig, Path, Path], tool: str
) -> None:
    config, _, _ = setup
    assert not reading.pre_tool_use(_pre(tool, tool_input={}), config).allow


def test_reading_through_the_shell_does_not_count(setup: tuple[SessionConfig, Path, Path]) -> None:
    config, a, b = setup
    for path in (a, b):
        cat = HookInput.model_validate(
            event(
                "PostToolUse",
                tool_name="Bash",
                tool_input={"command": f"cat {path}"},
                tool_response={"stdout": path.read_text(), "stderr": ""},
            )
        )
        assert reading.post_tool_use(cat, config).allow
    assert not reading.pre_tool_use(_pre(), config).allow


def test_partial_reads_count_only_when_together_they_cover_the_file(
    setup: tuple[SessionConfig, Path, Path],
) -> None:
    config, a, b = setup
    _read(config, b, 1, 6, 6)
    _read(config, a, 1, 2, 4)
    assert str(a) in reading.pre_tool_use(_pre(), config).reason
    _read(config, a, 4, 1, 4)
    assert str(a) in reading.pre_tool_use(_pre(), config).reason, "line 3 was never shown"
    _read(config, a, 2, 2, 4)
    assert reading.pre_tool_use(_pre(), config).allow


def test_a_file_changed_after_it_was_read_must_be_read_again(
    setup: tuple[SessionConfig, Path, Path],
) -> None:
    config, a, b = setup
    _read(config, a, 1, 4, 4)
    _read(config, b, 1, 6, 6)
    assert reading.pre_tool_use(_pre(), config).allow
    b.write_text("1\n2\n3\n4\n5\n6 appended after the read\n")
    decision = reading.pre_tool_use(_pre(), config)
    assert not decision.allow
    assert str(b) in decision.reason


def test_a_read_through_a_symlink_counts_as_the_file(
    setup: tuple[SessionConfig, Path, Path], tmp_path: Path
) -> None:
    config, a, b = setup
    link = tmp_path / "elsewhere.md"
    link.symlink_to(a)
    _read(config, link, 1, 4, 4)
    _read(config, b, 1, 6, 6)
    assert reading.pre_tool_use(_pre(), config).allow


def test_another_sessions_reading_does_not_count(setup: tuple[SessionConfig, Path, Path]) -> None:
    config, a, b = setup
    other = "11111111-2222-3333-4444-555555555555"
    for path, n in ((a, 4), (b, 6)):
        assert reading.post_tool_use(_post_read(path, 1, n, n, session=other), config).allow
    assert not reading.pre_tool_use(_pre(), config).allow
    assert reading.pre_tool_use(_pre(session=other), config).allow


def test_a_read_of_a_file_not_required_records_nothing(
    setup: tuple[SessionConfig, Path, Path], tmp_path: Path
) -> None:
    config, _, _ = setup
    other = tmp_path / "notes.md"
    other.write_text("x\n")
    _read(config, other, 1, 2, 2)
    reads = Path(config.state_dir) / "sessions" / SESSION / "reads"
    assert not reads.exists() or not list(reads.iterdir())


def test_a_read_response_without_line_numbers_records_nothing(
    setup: tuple[SessionConfig, Path, Path],
) -> None:
    config, a, _ = setup
    image = HookInput.model_validate(
        event(
            "PostToolUse",
            tool_name="Read",
            tool_input={"file_path": str(a)},
            tool_response={"type": "image", "file": {"filePath": str(a)}},
        )
    )
    assert reading.post_tool_use(image, config).allow
    assert str(a) in reading.pre_tool_use(_pre(), config).reason


def test_a_required_file_that_does_not_exist_keeps_every_tool_refused(tmp_path: Path) -> None:
    _, _, config = write_config(tmp_path, required_reading=[str(tmp_path / "missing.md")])
    decision = reading.pre_tool_use(_pre(), config)
    assert not decision.allow
    assert "does not exist" in decision.reason


def test_a_session_with_nothing_to_read_is_not_held(tmp_path: Path) -> None:
    _, _, config = write_config(tmp_path)
    assert reading.pre_tool_use(_pre(), config).allow


def test_the_session_is_told_at_start_what_it_must_read(
    setup: tuple[SessionConfig, Path, Path],
) -> None:
    config, a, b = setup
    decision = reading.session_start(HookInput.model_validate(event("SessionStart")), config)
    assert decision.allow
    assert str(a) in decision.context and str(b) in decision.context
