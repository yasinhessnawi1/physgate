"""Each profile runs on a closed list of tools.

A tool that is not on the list is refused, including one this version of Claude
Code does not have yet and every tool of a tool server but the admitted tools of the servers the
session is offered (the tool-server register). An admitted server tool is asked only what its
register entry names (:mod:`physgate.hooks.server_arguments`). The list is closed
because the tools left off it act outside the call a hook can see: a subagent
that can run remotely, a workflow or a scheduled prompt that runs later, a web
fetch that brings in text nobody reviewed. Opening one is a decision with a
test, never a default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.server_arguments import SERVER_TOOL, arguments_refusal

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

NOT_AVAILABLE = "The {tool} tool is not available to a {profile} session. Available: {allowed}."


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
    """Refuse a tool that is not on the profile's list."""
    tool = hook_input.tool_name or ""
    if tool in config.tools_allowed:
        if not tool.startswith(SERVER_TOOL):
            return ALLOW
        # A tool server's tool is asked only what its register entry names.
        reason = arguments_refusal(tool, hook_input.tool_input, hook_input.cwd, config)
        return ALLOW if reason is None else refuse(reason)
    return refuse(
        NOT_AVAILABLE.format(
            tool=tool or "(unnamed)",
            profile=config.profile,
            allowed=", ".join(config.tools_allowed),
        )
    )


HOOK = HookSpec("tools", {"PreToolUse": pre_tool_use})
