"""Nothing a role session's shell command starts outlives it.

The shell hook refuses backgrounding it can see in a command's text; a process started in a
session of its own by a program (``Popen(start_new_session=True)``) is not in the text, and on
macOS it lived on after its command, acting across later commands. This hook finds and kills
every such process (:mod:`physgate.oslayer.survivors`): after each shell command, before every
tool call, and when the session ends. On Linux each command's process namespace already ends
them, and the hook does nothing.

After a shell command, a survivor killed is a refusal, logged and told to the session: the
command left something running, which it may not. Before a tool call and at the session's end
the survivor came from a command whose own check did not run (it was cut short); it is
killed and logged as ``reaped``, and the call goes on. Where the OS layer does not run, no
command is sandboxed, no survivor can be told apart, and nothing is done.

Any failure to ask the process table or the sandbox raises, and the hook layer turns that into
a refusal: "nothing survives" is never concluded from a question that went unanswered.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.state import append_log

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

#: The decision a kill outside a shell command's own check is logged under; no count of
#: refusals reads it.
REAPED = "reaped"

SURVIVOR_REASON = (
    "This command left {count} process(es) running after it ended (a process started in a "
    "session of its own, or detached some other way), and they were stopped. Nothing a "
    "command starts may outlive it: run what you need in the foreground, within the command."
)


def _reap(config: ConfigView) -> list[int]:
    if sys.platform != "darwin" or config.os_layer_home is None:
        return []
    from physgate.oslayer.survivors import SessionMark, reap  # noqa: PLC0415 - macOS, layer on

    mark = SessionMark.of(
        home=config.os_layer_home, state_dir=config.state_dir, worktree=config.worktree
    )
    return [p.pid for p in reap(mark)]


def after_shell(hook_input: InputView, config: ConfigView) -> Decision:
    """After a shell command: kill what it left running, and refuse it if it left anything."""
    if hook_input.tool_name != "Bash":
        return ALLOW
    killed = _reap(config)
    if not killed:
        return ALLOW
    return refuse(SURVIVOR_REASON.format(count=len(killed)))


def before_or_at_end(hook_input: InputView, config: ConfigView) -> Decision:
    """Before any tool call and at the session's end: kill survivors, log them, go on."""
    killed = _reap(config)
    if killed:
        append_log(
            config,
            {
                "t": time.time(),
                "session": hook_input.session_id,
                "agent": hook_input.agent_id,
                "profile": config.profile,
                "role": config.role,
                "event": hook_input.hook_event_name,
                "tool": hook_input.tool_name,
                "hook": "survivors",
                "decision": REAPED,
                "count": len(killed),
            },
        )
    return ALLOW


HOOK = HookSpec(
    "survivors",
    {
        "PreToolUse": before_or_at_end,
        "PostToolUse": after_shell,
        "PostToolUseFailure": after_shell,
        "SessionEnd": before_or_at_end,
    },
)
