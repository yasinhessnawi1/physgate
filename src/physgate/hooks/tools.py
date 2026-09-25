"""Each profile runs on a closed list of tools.

A tool that is not on the list is refused, including one this version of Claude
Code does not have yet and every tool from an MCP server. The list is closed
because the tools left off it act outside the call a hook can see: a subagent
that can run remotely, a workflow or a scheduled prompt that runs later, a web
fetch that brings in text nobody reviewed. Opening one is a decision with a
test, never a default.
"""

from __future__ import annotations

from physgate.hooks.config import SessionConfig
from physgate.hooks.runtime import ALLOW, Decision, HookInput, HookSpec, refuse

NOT_AVAILABLE = "The {tool} tool is not available to a {profile} session. Available: {allowed}."


def pre_tool_use(hook_input: HookInput, config: SessionConfig) -> Decision:
    """Refuse a tool that is not on the profile's list."""
    tool = hook_input.tool_name or ""
    if tool in config.tools_allowed:
        return ALLOW
    return refuse(
        NOT_AVAILABLE.format(
            tool=tool or "(unnamed)",
            profile=config.profile,
            allowed=", ".join(config.tools_allowed),
        )
    )


HOOK = HookSpec("tools", {"PreToolUse": pre_tool_use})
