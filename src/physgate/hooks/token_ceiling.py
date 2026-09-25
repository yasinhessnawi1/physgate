"""The always-loaded set stays under its token ceiling (ARCH-023).

**The count is an upper bound, not an estimate.** A tokenizer that works on
bytes emits tokens that each cover at least one byte, so a text of n bytes
needs at most n tokens. That property is assumed for the provider's tokenizer,
which is not published, and it can be checked against the provider's own count
the day a real ceiling is set. The provider's count cannot be asked from here:
it is a network call, and a hook makes none. The bound overstates English prose
roughly three- to fourfold (a common rule of thumb, not measured here), so an
error can only refuse a set that is really under the ceiling, never admit one
that is over it. If that proves too strict, the remedy is to measure, not to
switch quietly to a laxer count.

**A breach is a defect in the file, not a reason to raise the ceiling**, so
the message names the files, largest first. The ceiling itself has no default:
it is a number someone has to decide, and the configuration requires it.

The session-start hook reports a breach, but it cannot stop a session: Claude
Code carries on past a refusal there (measured). So the same measurement is
taken before every tool call, and every tool is refused while the set is over.
It costs one ``stat`` per file, since the bound is the file's size.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

OVER = (
    "The always-loaded set is over its token ceiling, so every tool is refused. It "
    "needs at most {bound} tokens (its size in bytes, an upper bound; roughly {rough} by "
    "the usual estimate) against a ceiling of {ceiling}. By size:\n{files}\nThis is a "
    "defect in those files, not a reason to raise the ceiling."
)
UNMEASURABLE = (
    "The always-loaded file {path} cannot be measured ({error}), so the token ceiling "
    "cannot be checked and every tool is refused."
)


def measure(config: ConfigView) -> Decision:
    """Refuse when the always-loaded set's upper bound is over the ceiling."""
    sizes: list[tuple[int, str]] = []
    for path in config.always_loaded:
        try:
            sizes.append((os.stat(path).st_size, path))
        except OSError as exc:
            return refuse(UNMEASURABLE.format(path=path, error=exc.strerror or exc))
    bound = sum(size for size, _ in sizes)
    if bound <= config.token_ceiling:
        return ALLOW
    sizes.sort(key=lambda item: (-item[0], item[1]))
    files = "\n".join(f"- {path}: at most {size} tokens" for size, path in sizes)
    return refuse(
        OVER.format(bound=bound, rough=bound // 4, ceiling=config.token_ceiling, files=files)
    )


def session_start(hook_input: InputView, config: ConfigView) -> Decision:
    """Report a breach at the start of the session."""
    return measure(config)


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
    """Refuse every tool while the always-loaded set is over the ceiling."""
    return measure(config)


HOOK = HookSpec("token_ceiling", {"SessionStart": session_start, "PreToolUse": pre_tool_use})
