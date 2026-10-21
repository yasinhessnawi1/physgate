"""A shell command that left something running is refused after it, and the reaper's word logged.

On macOS the survivor reaper (:mod:`physgate.oslayer.reaper`) runs inside each sandboxed
command's own sandbox and stops whatever the command left running when it ends. It says so in
one line on the command's standard error, which Claude Code hands the session and this hook
as part of the command's output. This hook turns that line into a refusal of the command,
logged like any other. The same holds for the reaper's two other lines: it could not prove its
fence and signalled nothing, or a process was still running after it reaped.

The line is the reaper's word, read from output the command shares: a command can print it,
and the refusal is then its own. Nothing here signals or stops anything. The reaper did that
inside the sandbox, or did nothing.

A command that kills its own reaper leaves no line, and Claude Code reports that death as an
ordinary ``Exit code 1`` (measured on 2.1.301, M5). Nothing outside the sandbox tells it from a
command that exits 1, so this hook cannot see it (a residual, stated in the reaper).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

#: The reaper's tag (``physgate.oslayer.reaper.TAG``, which a test holds equal). Not imported:
#: the reaper module loads ``ctypes`` and ``subprocess``, which the hook hot path stays off.
TAG = "physgate-reaper:"

#: The reaper's lines, each whole on a line of its own.
LINE = re.compile(
    "^"
    + re.escape(TAG)
    + r" (?P<what>stopped (?P<count>[1-9][0-9]{0,5}) process\(es\) this command left running"
    r"|not reaping: [^\n]{1,300}"
    r"|some process of this command was still running after reaping)$",
    re.MULTILINE,
)

LEFT_RUNNING = (
    "This command left {count} process(es) running after it ended (started in a session of "
    "its own, or detached some other way), and they were stopped. Nothing a command starts "
    "may outlive it: run what you need in the foreground, within the command."
)
NOT_REAPED = (
    "The OS layer could not make sure this command left nothing running ({what}). Nothing a "
    "command starts may outlive it."
)


def _told(hook_input: InputView) -> str:
    response = hook_input.tool_response
    parts: list[str] = []
    if isinstance(response, dict):
        parts += [str(response.get(key) or "") for key in ("stdout", "stderr")]
    parts.append(hook_input.error or "")
    return "\n".join(parts)


def after_shell(hook_input: InputView, config: ConfigView) -> Decision:  # noqa: ARG001
    """After a shell command: refuse it if the reaper said it left something running."""
    if hook_input.tool_name != "Bash":
        return ALLOW
    said = list(LINE.finditer(_told(hook_input)))
    if not said:
        return ALLOW
    stopped = sum(int(m.group("count")) for m in said if m.group("count"))
    others = [m.group("what") for m in said if not m.group("count")]
    if others:
        return refuse(NOT_REAPED.format(what="; ".join(others)))
    return refuse(LEFT_RUNNING.format(count=stopped))


HOOK = HookSpec("survivors", {"PostToolUse": after_shell, "PostToolUseFailure": after_shell})
