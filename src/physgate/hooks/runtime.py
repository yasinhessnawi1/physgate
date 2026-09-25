"""The contract between Claude Code and a hook, and the dispatcher that keeps it.

Claude Code runs a hook command with a JSON description of the event on stdin.
Only two outcomes stop a tool call: exit status 2, or a JSON refusal on stdout.
**Every other outcome lets the tool run** — measured on the pinned version for
exit 1, exit 3, an uncaught exception, a killed process, an interpreter that is
not there, and a hook that outlives its timeout. So the dispatcher turns every
exception into a refusal, and the shell trampoline around it turns every exit it
cannot vouch for into a refusal too.

A refusal is written both ways at once: a JSON refusal on stdout and exit status
2. With both, the agent is shown only the reason; with the exit status alone it
is shown the hook's whole command line as well (measured).

One process serves every hook module for one event. Claude Code runs matching
hook commands in parallel, so one process per module would start an interpreter
and import the validation library once per module on every tool call; the module
names are on the command line instead, which is also how the settings file shows
that every module is wired.
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from physgate.hooks.config import SessionConfig, load_config
from physgate.hooks.state import append_log

Event = Literal[
    "SessionStart", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "SessionEnd"
]
EVENTS: tuple[Event, ...] = (
    "SessionStart",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SessionEnd",
)

#: The events on which a refusal stops something. On the others a refusal is
#: still reported and logged, and the later hooks act on the record it leaves.
_BLOCKING_EVENTS = {"PreToolUse"}


class HookInput(BaseModel):
    """The part of Claude Code's event description the hooks rely on.

    Unknown fields are ignored rather than refused. This is the one boundary in
    the package that does not forbid extras, deliberately: the description is a
    vendor contract that gains fields between versions, and refusing an unknown
    field would turn a routine upgrade into a refusal of every tool call. The
    fields that are relied on are typed and required where the decision needs
    them.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    cwd: str
    hook_event_name: Event
    tool_name: str | None = None
    # Any: the shape of a tool's input and response is the tool's, and each
    # hook validates the part it reads.
    tool_input: dict[str, Any] | None = None
    tool_response: Any = None
    agent_id: str | None = None


@dataclass(frozen=True)
class Decision:
    """What a hook concluded. ``context`` is text handed to the session at start."""

    allow: bool
    reason: str = ""
    context: str = ""


ALLOW = Decision(allow=True)


def refuse(reason: str) -> Decision:
    """A refusal, carrying the reason the agent will read."""
    return Decision(allow=False, reason=reason)


Handler = Callable[[HookInput, SessionConfig], Decision]


@dataclass(frozen=True)
class HookSpec:
    """One hook module: its name and what it does on each event."""

    name: str
    handlers: Mapping[Event, Handler] = field(default_factory=dict)


def dispatch(specs: Sequence[HookSpec], hook_input: HookInput, config: SessionConfig) -> Decision:
    """Run every named hook that handles this event; the first refusal wins.

    Every refusal is logged, not only the first, so the record says which layers
    caught a call.
    """
    event = hook_input.hook_event_name
    first: Decision | None = None
    contexts = []
    for spec in specs:
        handler = spec.handlers.get(event)
        if handler is None:
            continue
        decision = handler(hook_input, config)
        if decision.context:
            contexts.append(decision.context)
        if not decision.allow:
            _log_refusal(config, hook_input, spec.name, decision.reason)
            if first is None:
                first = decision
    if first is not None:
        return first
    return Decision(allow=True, context="\n\n".join(contexts))


def _log_refusal(config: SessionConfig, hook_input: HookInput, hook: str, reason: str) -> None:
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
            "hook": hook,
            "decision": "refuse",
            "reason": reason,
        },
    )


def emit(event: str, decision: Decision) -> int:
    """Write the decision the way Claude Code reads it, and return the exit status."""
    if decision.allow:
        if decision.context and event == "SessionStart":
            context = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": decision.context,
                }
            }
            sys.stdout.write(json.dumps(context))
        return 0
    out: dict[str, object]
    if event in _BLOCKING_EVENTS:
        out = {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": decision.reason,
            }
        }
    else:
        out = {"decision": "block", "reason": decision.reason}
    sys.stdout.write(json.dumps(out))
    sys.stderr.write(decision.reason + "\n")
    return 2


def main(argv: Sequence[str], stdin_text: str, registry: Mapping[str, HookSpec]) -> int:
    """Decide one event. Never raises; never returns anything but 0 or 2.

    ``argv`` is ``<event> --hooks a,b,c --config <path> --config-sha256 <hex>``.
    """
    event = argv[0] if argv else "PreToolUse"
    config: SessionConfig | None = None
    try:
        args = _parse_argv(argv)
        event = args["event"]
        config = load_config(args["config"], args["sha256"])
        specs = [registry[name] for name in args["hooks"]]
        hook_input = HookInput.model_validate_json(stdin_text)
        if hook_input.hook_event_name != event:
            msg = f"the hook was wired for {event} but received {hook_input.hook_event_name}"
            raise ValueError(msg)
        decision = dispatch(specs, hook_input, config)
    except BaseException as exc:  # noqa: BLE001 - every failure must become a refusal
        # Anything that escapes a check means no check was made, and Claude Code
        # would run the tool. Refusing is the only safe answer.
        reason = (
            "The hook that checks this call could not reach a decision "
            f"({type(exc).__name__}: {exc}), so the call is refused."
        )
        decision = refuse(reason)
        # The refusal stands whether or not the log line can be written.
        if config is not None:
            with contextlib.suppress(BaseException):
                append_log(
                    config,
                    {"t": time.time(), "event": event, "decision": "error", "reason": reason},
                )
    return emit(event, decision)


def _parse_argv(argv: Sequence[str]) -> dict[str, Any]:
    if len(argv) != 7 or argv[1] != "--hooks" or argv[3] != "--config":
        msg = "expected: <event> --hooks <names> --config <path> --config-sha256 <hex>"
        raise ValueError(msg)
    if argv[5] != "--config-sha256":
        msg = "expected --config-sha256"
        raise ValueError(msg)
    if argv[0] not in EVENTS:
        msg = f"unknown event {argv[0]!r}"
        raise ValueError(msg)
    return {
        "event": argv[0],
        "hooks": [name for name in argv[2].split(",") if name],
        "config": argv[4],
        "sha256": argv[6],
    }
