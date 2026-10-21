"""A shell command the reaper stopped survivors of is refused after it, and logged.

Claude Code hands the hook a command's output with its standard error in it (measured on
2.1.301: ``tool_response.stdout`` after a success, ``error`` after a failure). The reaper's
line there is a refusal. Its two other lines (no fence proven, a process still running) are
refusals too. A mention elsewhere in a line, another tool, or no line at all is allowed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hook_helpers import event, write_config

from physgate.hooks import survivors
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.registry import REGISTRY
from physgate.hooks.runtime import dispatch
from physgate.oslayer import reaper

STOPPED = "physgate-reaper: stopped 2 process(es) this command left running"
NOT_REAPING = "physgate-reaper: not reaping: the canary 400 is gone"
STILL = "physgate-reaper: some process of this command was still running after reaping"


def _success(stdout: str, tool: str = "Bash") -> HookInput:
    response = {"stdout": stdout, "stderr": "", "interrupted": False, "isImage": False}
    return HookInput.model_validate(
        event(
            "PostToolUse",
            tool_name=tool,
            tool_input={"command": "x"},
            tool_response=response,
        )
    )


def _failure(error: str) -> HookInput:
    return HookInput.model_validate(
        event("PostToolUseFailure", tool_name="Bash", tool_input={"command": "x"}, error=error)
    )


def _config(tmp: Path) -> SessionConfig:
    _, _, config = write_config(tmp)
    return config


def _log(config: SessionConfig) -> list[dict[str, Any]]:
    path = Path(config.state_dir) / "hooks.log.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_the_reaper_s_line_after_a_success_is_a_logged_refusal(tmp_path: Path) -> None:
    config = _config(tmp_path)
    decision = dispatch([survivors.HOOK], _success(f"spawned 96142\n{STOPPED}"), config)
    assert not decision.allow
    assert "left 2 process(es) running after it ended" in decision.reason
    (line,) = _log(config)
    assert (line["hook"], line["decision"], line["event"]) == ("survivors", "refuse", "PostToolUse")


def test_after_a_failure_too(tmp_path: Path) -> None:
    config = _config(tmp_path)
    decision = dispatch([survivors.HOOK], _failure(f"Exit code 3\ny\n{STOPPED}"), config)
    assert not decision.allow and "left 2 process(es)" in decision.reason


def test_an_unproven_fence_or_a_process_still_running_is_refused_with_why(tmp_path: Path) -> None:
    config = _config(tmp_path)
    for said, why in ((NOT_REAPING, "the canary 400 is gone"), (STILL, "still running")):
        decision = dispatch([survivors.HOOK], _success(f"out\n{said}"), config)
        assert not decision.allow and why in decision.reason, said
    # With a stopped line as well, the unproven fence is what the session is told.
    decision = dispatch([survivors.HOOK], _success(f"{STOPPED}\n{NOT_REAPING}"), config)
    assert not decision.allow and "could not make sure" in decision.reason


def test_a_mention_another_tool_or_nothing_is_allowed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    for hook_input in (
        _success("ok"),
        _success(f"  {STOPPED}"),
        _success(f"see: {STOPPED}"),
        _success("physgate-reaper: stopped 0 process(es) this command left running"),
        _success(STOPPED, tool="Read"),
        _failure("Exit code 1"),
    ):
        assert dispatch([survivors.HOOK], hook_input, config).allow
    assert _log(config) == []


def test_the_hook_reads_the_reaper_s_own_tag() -> None:
    assert survivors.TAG == reaper.TAG


def test_the_hook_is_registered() -> None:
    assert REGISTRY["survivors"] is survivors.HOOK
    assert set(survivors.HOOK.handlers) == {"PostToolUse", "PostToolUseFailure"}
