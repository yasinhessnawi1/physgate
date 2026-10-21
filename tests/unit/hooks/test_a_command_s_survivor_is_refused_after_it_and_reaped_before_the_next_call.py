"""The survivor hook: after a shell command a survivor killed refuses it; elsewhere it is logged.

The finding and killing is :mod:`physgate.oslayer.survivors`'s, stood in for here: the hook is
held to calling it only on macOS with the OS layer, to refusing the shell command that left a
survivor, and to logging, never refusing, what it kills before a tool call or at the end.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from hook_helpers import bash, event, write_config

from physgate.hooks import survivors
from physgate.hooks.config import HookInput, SessionConfig
from physgate.oslayer import survivors as finder
from physgate.oslayer.survivors import Process, SessionMark


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    (tmp_path / "state").mkdir()
    (tmp_path / "home").mkdir()
    return write_config(tmp_path, os_layer_home=str(tmp_path / "home"))[2]


@pytest.fixture
def killed(monkeypatch: pytest.MonkeyPatch) -> list[SessionMark]:
    """Every reap is recorded, and kills one stand-in process."""
    calls: list[SessionMark] = []

    def reap(mark: SessionMark) -> list[Process]:
        calls.append(mark)
        return [Process(4242, 1, 501, "t")]

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(finder, "reap", reap)
    return calls


def _log(config: SessionConfig) -> list[dict[str, object]]:
    path = Path(config.state_dir) / "hooks.log.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("name", ["PostToolUse", "PostToolUseFailure"])
def test_a_shell_command_that_left_a_process_running_is_refused(
    config: SessionConfig, killed: list[SessionMark], name: str
) -> None:
    hook_input = HookInput.model_validate(bash("python3 sim.py", hook_event_name=name))
    decision = survivors.after_shell(hook_input, config)
    assert not decision.allow
    assert "left 1 process(es) running after it ended" in decision.reason
    assert killed == [
        SessionMark.of(
            home=str(config.os_layer_home), state_dir=config.state_dir, worktree=config.worktree
        )
    ]


@pytest.mark.parametrize(
    "hook_input",
    [event("PreToolUse", tool_name="Read", tool_input={"file_path": "/x"}), event("SessionEnd")],
)
def test_a_survivor_found_before_a_call_or_at_the_end_is_logged_and_the_call_goes_on(
    config: SessionConfig, killed: list[SessionMark], hook_input: dict[str, object]
) -> None:
    decision = survivors.before_or_at_end(HookInput.model_validate(hook_input), config)
    assert decision.allow
    assert [(r["hook"], r["decision"], r["count"]) for r in _log(config)] == [
        ("survivors", "reaped", 1)
    ]


def test_another_tool_s_end_reaps_nothing(config: SessionConfig, killed: list[SessionMark]) -> None:
    hook_input = HookInput.model_validate(
        event("PostToolUse", tool_name="Read", tool_input={"file_path": "/x"})
    )
    assert survivors.after_shell(hook_input, config).allow
    assert killed == []


def test_without_the_os_layer_nothing_is_asked(tmp_path: Path, killed: list[SessionMark]) -> None:
    # No command is sandboxed, so none can be told apart by its sandbox.
    config = write_config(tmp_path, os_layer_home=None)[2]
    hook_input = HookInput.model_validate(bash("x", hook_event_name="PostToolUse"))
    assert survivors.after_shell(hook_input, config).allow
    assert killed == []


def test_on_linux_nothing_is_asked(
    config: SessionConfig, killed: list[SessionMark], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each command's process namespace ends what it started.
    monkeypatch.setattr(sys, "platform", "linux")
    hook_input = HookInput.model_validate(bash("x", hook_event_name="PostToolUse"))
    assert survivors.after_shell(hook_input, config).allow
    assert killed == []


def test_a_finder_that_cannot_answer_raises_so_the_call_is_refused(
    config: SessionConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")

    def unanswered(mark: SessionMark) -> list[Process]:
        raise finder.SurvivorError("ps could not be run")

    monkeypatch.setattr(finder, "reap", unanswered)
    hook_input = HookInput.model_validate(bash("x", hook_event_name="PostToolUse"))
    with pytest.raises(finder.SurvivorError):
        survivors.after_shell(hook_input, config)
