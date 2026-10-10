"""A structured answer refused because ``review`` was a string is told exactly what to send.

The refusal itself stands: the binary refuses, the schema is unchanged, and nothing
here reads a string as a verdict. What the hook adds is the correction, handed to the
session's next request. Every other failure, and every other tool, passes untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

from hook_helpers import event, write_config
from hook_process import InstalledSession

from physgate.hooks import verdict_shape
from physgate.hooks.config import HookInput, SessionConfig

#: The refusal as the binary words it, for a ``review`` holding the verdict's JSON.
REFUSED = "Output does not match required schema: /review: must be object"


def _failure(tool: str, error: str | None) -> HookInput:
    fields: dict[str, object] = {"tool_name": tool, "tool_input": {"review": "{}"}}
    if error is not None:
        fields["error"] = error
    return HookInput.model_validate(event("PostToolUseFailure", **fields))


def _config(tmp: Path) -> SessionConfig:
    _, _, config = write_config(tmp, profile="reviewer", role=None, tools_allowed=["Read"])
    return config


def test_a_review_sent_as_a_string_gets_the_correction(tmp_path: Path) -> None:
    decision = verdict_shape.post_tool_use_failure(
        _failure("StructuredOutput", REFUSED), _config(tmp_path)
    )
    assert decision.allow
    assert decision.context == verdict_shape.CORRECTION
    assert "`review` must be the verdict object itself" in decision.context
    assert 'never {"review": "{...}"}' in decision.context


def test_any_other_refusal_or_tool_passes_untouched(tmp_path: Path) -> None:
    config = _config(tmp_path)
    for hook_input in (
        _failure("StructuredOutput", "/review/spec_defects: must contain at least 1 valid item"),
        _failure("StructuredOutput", "Required reading is not complete"),
        _failure("StructuredOutput", None),
        _failure("Read", REFUSED),
        _failure("Bash", REFUSED),
    ):
        decision = verdict_shape.post_tool_use_failure(hook_input, config)
        assert decision.allow
        assert decision.context == ""


def test_the_installed_hook_hands_the_correction_to_the_session(tmp_path: Path) -> None:
    session = InstalledSession(tmp_path)
    done = session.run(
        "PostToolUseFailure",
        session.event(
            "PostToolUseFailure",
            tool_name="StructuredOutput",
            tool_input={"review": "{}"},
            tool_use_id="toolu_1",
            error=REFUSED,
            is_interrupt=False,
        ),
    )
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUseFailure",
            "additionalContext": verdict_shape.CORRECTION,
        }
    }


def test_the_installed_hook_says_nothing_after_another_failure(tmp_path: Path) -> None:
    session = InstalledSession(tmp_path)
    done = session.run(
        "PostToolUseFailure",
        session.event(
            "PostToolUseFailure",
            tool_name="Bash",
            tool_input={"command": "false"},
            tool_use_id="toolu_2",
            error="Exit code 1",
        ),
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""
