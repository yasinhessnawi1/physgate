"""Domain exceptions raised by the operator UI's server.

Each carries a ``context`` mapping, as the orchestrator's do, so a refusal can be
reported as data rather than parsed out of a message.
"""

from __future__ import annotations


class UIError(Exception):
    """Base for every error the operator UI's server raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class StartupRefusedError(UIError):
    """The server will not start: a bind, a root, a refused path or the build is wrong."""


class PathRefusedError(UIError):
    """A path is outside every allowed root, or reaches a path nothing may read."""


class GuardRefusedError(UIError):
    """A request did something its route kind does not allow: a write, a connection, a spawn."""


class UnregisteredKindError(UIError):
    """A route or a request scope names a kind no policy is registered for."""


class NotFoundError(UIError):
    """A request names a run, a session or a sheet the roots do not hold."""
