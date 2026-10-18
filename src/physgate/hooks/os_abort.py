"""A shell command the OS layer's bubblewrap aborted is logged as that, never as a refusal.

When bubblewrap cannot set a sandboxed command up it exits before the command runs,
and the session is told the command failed with bubblewrap's own line
(:mod:`physgate.oslayer.abort`). No layer judged that command: it is not a denial and
not a reach. The hook layer's log is what the bypass measurements count a refusal by,
so the abort gets its own line there, decision ``os_layer_aborted``, which no count of
refusals reads (they read ``refuse``, ``put back``, ``halt`` and ``node mismatch``).

The hook only records, and only beside the others: it allows every call, adds nothing to
the session, and changes no other hook's decision. Any command can print bubblewrap's
words, and nothing outside the sandbox tells a real abort from a printed one, so the line
is a possible abort, never a judgement that takes the place of another record.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec
from physgate.hooks.state import append_log
from physgate.oslayer.abort import OS_LAYER_ABORTED, is_abort

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

#: The most of bubblewrap's line the log keeps.
TOLD_LIMIT = 300


def after_shell(hook_input: InputView, config: ConfigView) -> Decision:
    """After a failed shell call: log an abort by bubblewrap as its own outcome.

    Only a failure is read: an abort always ends the command with bubblewrap's exit
    status, which Claude Code reports as a failed call (measured on 2.1.301).
    """
    if hook_input.tool_name != "Bash":
        return ALLOW
    told = hook_input.error or ""
    if not is_abort(told):
        return ALLOW
    line = next(t.strip() for t in told.splitlines() if is_abort(t))
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
            "tool_input": hook_input.tool_input,
            "hook": "os_abort",
            "decision": OS_LAYER_ABORTED,
            "told": line[:TOLD_LIMIT],
        },
    )
    return ALLOW


HOOK = HookSpec("os_abort", {"PostToolUseFailure": after_shell})
