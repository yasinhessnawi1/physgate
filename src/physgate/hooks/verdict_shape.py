"""A refused structured answer whose ``review`` came as a string is told exactly what to fix.

The verdict is submitted as one object, ``{"review": {...}}``. Real reviewers have more
than once passed ``review`` as a string holding the verdict's JSON (with one stray
closing brace, so the binary could not read it as an object either), and the binary
refused each with "/review: must be object" and nothing more. One reviewer repeated it
until the binary's cap on refused structured answers ended the session with no verdict.

Nothing here loosens the contract: the refusal stands, the schema is unchanged, and no
string is ever read as a verdict. After such a refusal (Claude Code's
``PostToolUseFailure`` event, whose ``error`` carries the refusal; measured on both
pinned binaries, and its context reaches the session's next request), the session is
told precisely what was wrong and what to send instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

#: The binary's refusal of a ``review`` that is not an object (measured on both binaries).
NOT_AN_OBJECT = "/review: must be object"
CORRECTION = (
    "That StructuredOutput call was refused because `review` was a string holding JSON. "
    "`review` must be the verdict object itself: call StructuredOutput with "
    '{"review": {"verdict": ..., "finding": ..., ...}}, the verdict\'s fields as an object, '
    'never {"review": "{...}"}. Send the same verdict again, as an object.'
)


def post_tool_use_failure(hook_input: InputView, config: ConfigView) -> Decision:
    """After a refused structured answer: a precise correction when ``review`` was a string."""
    if hook_input.tool_name != "StructuredOutput":
        return ALLOW
    if NOT_AN_OBJECT not in (hook_input.error or ""):
        return ALLOW
    return Decision(allow=True, context=CORRECTION)


HOOK = HookSpec("verdict_shape", {"PostToolUseFailure": post_tool_use_failure})
