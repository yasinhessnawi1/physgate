"""A command bubblewrap aborted is its own outcome: never a denial, never a refusal.

Bubblewrap that cannot set a sandboxed command up exits before the command runs, and
the session is told the command failed, with bubblewrap's own line. The stream reader
finds such a result by its call, and the hook layer logs it under its own decision,
which no count of refusals reads. A result that merely mentions bubblewrap, or one the
runtime did not mark as an error, is no abort.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hook_helpers import event, write_config

from physgate.hooks import os_abort
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.runtime import dispatch
from physgate.oslayer.abort import OS_LAYER_ABORTED, aborted_tool_uses, is_abort

#: What the Oracle VM's sessions were told when a sibling session removed a placeholder.
TOLD = (
    "Exit code 1\n"
    "bwrap: Can't find source path /tmp/pytest-of-ubuntu/pytest-3/.mcp.json: "
    "No such file or directory"
)
#: The decisions every count of refusals reads in the hook log.
REFUSALS = {"refuse", "put back", "halt", "node mismatch"}


def test_bubblewrap_s_own_line_is_an_abort_and_a_mention_is_not() -> None:
    assert is_abort(TOLD)
    assert is_abort("bwrap: Can't bind mount /oldroot/tmp/.claude/agents on /newroot/tmp")
    assert is_abort("Exit code 1\n  bwrap: Can't get type of source /tmp/.mcp.json")
    assert not is_abort("tee: /x/plain: Read-only file system")
    assert not is_abort("tee: /x/plain: Operation not permitted")
    assert not is_abort("see bwrap: its manual")
    assert not is_abort("")


def _result(tool_use_id: str, content: Any, *, is_error: bool) -> str:  # noqa: ANN401
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return json.dumps({"type": "user", "message": {"role": "user", "content": [block]}})


def test_the_stream_names_each_aborted_call_and_only_those() -> None:
    stream = "\n".join(
        [
            json.dumps({"type": "system", "subtype": "init"}),
            _result("toolu_1", TOLD, is_error=True),
            _result("toolu_2", "Exit code 1\ntee: x: Read-only file system", is_error=True),
            _result("toolu_3", [{"type": "text", "text": TOLD}], is_error=True),
            _result("toolu_4", "bwrap: printed by a command that succeeded", is_error=False),
            "not json",
            json.dumps({"type": "result", "is_error": False}),
        ]
    )
    assert aborted_tool_uses(stream) == ("toolu_1", "toolu_3")


def _failure(tool: str, error: str) -> HookInput:
    return HookInput.model_validate(
        event("PostToolUseFailure", tool_name=tool, tool_input={"command": "ls"}, error=error)
    )


def _config(tmp: Path) -> SessionConfig:
    _, _, config = write_config(tmp)
    return config


def _log(config: SessionConfig) -> list[dict[str, Any]]:
    path = Path(config.state_dir) / "hooks.log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_the_hook_logs_an_abort_as_its_own_decision_and_allows(tmp_path: Path) -> None:
    config = _config(tmp_path)
    decision = dispatch([os_abort.HOOK], _failure("Bash", TOLD), config)
    assert decision.allow and decision.context == ""
    (line,) = _log(config)
    assert (line["hook"], line["decision"], line["tool"]) == ("os_abort", OS_LAYER_ABORTED, "Bash")
    assert line["told"].startswith("bwrap: Can't find source path")
    assert line["decision"] not in REFUSALS


def test_the_hook_logs_nothing_for_a_denial_another_tool_or_a_mention(tmp_path: Path) -> None:
    config = _config(tmp_path)
    for hook_input in (
        _failure("Bash", "Exit code 1\ntee: x: Read-only file system"),
        _failure("Bash", "Exit code 1\nsee bwrap: its manual"),
        _failure("Read", TOLD),
    ):
        decision = dispatch([os_abort.HOOK], hook_input, config)
        assert decision.allow
    assert _log(config) == []
