"""A verdict called before the required reading is done is told it was counted, and to wait.

The binary counts every call of the verdict tool toward its cap on refused verdicts, the reading
hook's refusal included, and nothing the harness can set before a session withholds the tool until
the reading is done. Real reviewers called it early in nine of fourteen reviews, and in both that
ended at the cap. So the refusal of that one tool says the call was not taken, that it counted,
and to call it once after the reading, with ``review`` as an object. Every other tool's refusal
is worded exactly as before.
"""

from __future__ import annotations

from pathlib import Path

from hook_helpers import SESSION, bash, event, write_config

from physgate.hooks import reading
from physgate.hooks.config import HookInput, SessionConfig


def _config(tmp_path: Path) -> tuple[SessionConfig, Path]:
    rubric = tmp_path / "rubric.md"
    rubric.write_text("one\ntwo\n")
    _, _, config = write_config(tmp_path, required_reading=[str(rubric)])
    return config, rubric


def _verdict() -> HookInput:
    return HookInput.model_validate(
        event(tool_name="StructuredOutput", session_id=SESSION, tool_input={"review": {}})
    )


def test_a_verdict_called_too_early_is_told_it_counted_and_to_call_once_after_reading(
    tmp_path: Path,
) -> None:
    config, rubric = _config(tmp_path)
    decision = reading.pre_tool_use(_verdict(), config)
    assert not decision.allow
    missing = reading.unread_files(config, _verdict())
    listing = "\n".join(f"- {path} ({why})" for path, why in missing)
    assert str(rubric) in listing
    # The refusal as every tool gets it, then the words for the verdict tool alone.
    assert decision.reason == reading.NOT_DONE.format(files=listing) + reading.VERDICT_TOO_EARLY
    assert "counts toward the limit on verdict calls" in decision.reason
    assert "call StructuredOutput once, with `review` as an object" in decision.reason


def test_every_other_tool_s_refusal_is_worded_exactly_as_before(tmp_path: Path) -> None:
    config, _ = _config(tmp_path)
    decision = reading.pre_tool_use(HookInput.model_validate(bash("ls")), config)
    assert not decision.allow
    assert reading.VERDICT_TOO_EARLY not in decision.reason
    missing = reading.unread_files(config, HookInput.model_validate(bash("ls")))
    listing = "\n".join(f"- {path} ({why})" for path, why in missing)
    assert decision.reason == reading.NOT_DONE.format(files=listing)


def test_a_verdict_after_the_reading_is_not_refused(tmp_path: Path) -> None:
    config, rubric = _config(tmp_path)
    read = event(
        "PostToolUse",
        session_id=SESSION,
        tool_name="Read",
        tool_input={"file_path": str(rubric)},
        tool_response={
            "type": "text",
            "file": {
                "filePath": str(rubric),
                "content": "...",
                "numLines": 3,
                "startLine": 1,
                "totalLines": 3,
            },
        },
    )
    assert reading.post_tool_use(HookInput.model_validate(read), config).allow
    assert reading.pre_tool_use(_verdict(), config).allow
