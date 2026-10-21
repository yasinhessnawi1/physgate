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
DONE = "physgate-reaper: done"
WHEN = "physgate-reaper: stopped 3 process(es) when the command was stopped (signal 15)"


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


def test_output_without_a_final_newline_cannot_hide_the_line(tmp_path: Path) -> None:
    # What a ``printf x`` command gives, with the reaper's line after it as the reaper
    # writes it (a newline first): the line stands on its own and is read.
    config = _config(tmp_path)
    told = "x" + f"\n{STOPPED}\n" + f"\n{DONE}\n"
    decision = dispatch([survivors.HOOK], _success(told), config)
    assert not decision.allow and "left 2 process(es)" in decision.reason
    assert reaper.TAG in told.splitlines()[1]


def test_a_mention_another_tool_or_nothing_is_allowed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    for hook_input in (
        _success("ok"),
        _success(f"  {STOPPED}"),
        _success("physgate-reaper: stopped 0 process(es) this command left running"),
        _success(STOPPED, tool="Read"),
        _failure("Exit code 1"),
    ):
        assert dispatch([survivors.HOOK], hook_input, config).allow
    assert _log(config) == []


def _reaper_on(tmp: Path) -> SessionConfig:
    _, _, config = write_config(tmp, survivor_reaper=True)
    return config


def test_with_the_reaper_on_a_command_without_its_done_line_is_refused(tmp_path: Path) -> None:
    # Its reaper did not finish: the command killed it (``Exit code 1``, measured), or it
    # died with the command. Only a session whose configuration says the reaper is on.
    config = _reaper_on(tmp_path)
    for hook_input in (_failure("Exit code 1"), _success("ok")):
        decision = dispatch([survivors.HOOK], hook_input, config)
        assert not decision.allow and "did not finish" in decision.reason
    for hook_input in (_failure(f"Exit code 3\ny\n{DONE}"), _success(f"ok\n{DONE}")):
        assert dispatch([survivors.HOOK], hook_input, config).allow
    # Another tool is not the reaper's.
    assert dispatch([survivors.HOOK], _success("ok", tool="Read"), config).allow


def test_with_the_reaper_off_a_missing_done_line_is_nothing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert not config.survivor_reaper
    assert dispatch([survivors.HOOK], _failure("Exit code 1"), config).allow


def test_a_stopped_command_s_reaping_is_logged_and_allowed(tmp_path: Path) -> None:
    config = _reaper_on(tmp_path)
    told = f"Exit code 143\nCommand timed out after 2s\n{WHEN}\n{DONE}"
    assert dispatch([survivors.HOOK], _failure(told), config).allow
    (line,) = _log(config)
    assert (line["hook"], line["decision"]) == ("survivors", survivors.REAPED)
    assert line["told"].startswith("stopped 3 process(es) when the command was stopped")


def _persisted(tmp: Path, inside: bool, end: str) -> tuple[SessionConfig, HookInput]:
    config_dir = tmp / "claude-config"
    roots = [{"path": str(config_dir), "reason": "Claude Code's", "watch": "none"}]
    _, _, config = write_config(tmp, survivor_reaper=True, protected_roots=roots)
    where = (config_dir if inside else tmp / "elsewhere") / "tool-results" / "b1.txt"
    where.parent.mkdir(parents=True)
    where.write_text("y" * 50_000 + end)
    response = {
        "stdout": "y" * 30_000,
        "stderr": "",
        "interrupted": False,
        "isImage": False,
        "persistedOutputPath": str(where),
        "persistedOutputSize": 50_000,
    }
    return config, HookInput.model_validate(
        event("PostToolUse", tool_name="Bash", tool_input={"command": "x"}, tool_response=response)
    )


def test_a_persisted_output_is_read_to_its_end_where_claude_code_wrote_it(tmp_path: Path) -> None:
    # After a success Claude Code hands the hook the first 30 000 characters and the path
    # of the whole output, in the session's configuration directory (measured on 2.1.301).
    config, hook_input = _persisted(tmp_path / "a", True, f"\n{DONE}\n")
    assert dispatch([survivors.HOOK], hook_input, config).allow
    config, hook_input = _persisted(tmp_path / "b", True, f"\n{STOPPED}\n\n{DONE}\n")
    decision = dispatch([survivors.HOOK], hook_input, config)
    assert not decision.allow and "left 2 process(es)" in decision.reason
    config, hook_input = _persisted(tmp_path / "c", True, "\n")
    assert not dispatch([survivors.HOOK], hook_input, config).allow


def test_a_persisted_output_outside_every_protected_root_is_not_read(tmp_path: Path) -> None:
    # A path the command could have written is never read: the end counts as cut off.
    config, hook_input = _persisted(tmp_path, False, f"\n{STOPPED}\n\n{DONE}\n")
    assert dispatch([survivors.HOOK], hook_input, config).allow
    (line,) = _log(config)
    assert line["decision"] == survivors.UNVERIFIED


def test_a_failure_whose_end_was_cut_off_is_logged_unverified_not_refused(tmp_path: Path) -> None:
    # After a failure Claude Code keeps about 10 000 characters and marks the cut.
    config = _reaper_on(tmp_path)
    told = (
        "Exit code 3\n" + "y" * 5000 + "\n\n... [20012 characters truncated] ...\n\n" + "y" * 5000
    )
    assert dispatch([survivors.HOOK], _failure(told), config).allow
    (line,) = _log(config)
    assert line["decision"] == survivors.UNVERIFIED
    assert not dispatch([survivors.HOOK], _failure("Exit code 3\n" + "y" * 9000), config).allow


def test_the_hook_reads_the_reaper_s_own_tag() -> None:
    assert survivors.TAG == reaper.TAG


def test_the_hook_is_registered() -> None:
    assert REGISTRY["survivors"] is survivors.HOOK
    assert set(survivors.HOOK.handlers) == {"PostToolUse", "PostToolUseFailure"}
