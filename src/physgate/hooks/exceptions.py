"""Domain exceptions raised by the hook layer.

A hook that raises does not let the tool call through: the dispatcher turns every
exception into a refusal, because Claude Code treats any hook outcome other than
an explicit refusal as permission to run the tool. These exist so a refusal
caused by an error can say what went wrong in words an agent can act on.
"""

from __future__ import annotations


class HookError(Exception):
    """Base for every error this package raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class SessionConfigMismatchError(HookError):
    """The session configuration is not the file the spawner wrote.

    The hook command line carries the digest of the configuration it was
    generated with, and the settings file holding that command line is not
    re-read during a session. A configuration whose bytes no longer match was
    changed after the spawn, by something inside the session or beside it.
    """


class UndecidableError(HookError):
    """A hook could not reach a decision, so the call is refused.

    Raised for input a check cannot interpret: a shell command it cannot
    tokenise, a record it cannot parse. Guessing would be failing open.
    """
