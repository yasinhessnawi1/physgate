"""No session uploads or flashes to hardware, or opens a serial device: the rule's place.

The hook is registered and decides nothing yet; the tests that hold it come first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

UPLOAD = "Uploading or flashing to hardware is refused."
SERIAL = "Opening a serial device is refused. The call names {device}."
DYNAMIC = "A word of this command is decided only when it runs."
UNREADABLE = "This call's arguments could not be read to their end ({detail})."
MAX_DEPTH = 16


def serial_device_in(text: str) -> str | None:
    """The serial device ``text`` names: none is known yet."""
    del text
    return None


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
    """Refuse nothing yet."""
    del hook_input, config
    return ALLOW


HOOK = HookSpec("hardware", {"PreToolUse": pre_tool_use})
