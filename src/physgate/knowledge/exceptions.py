"""Domain exceptions raised by the knowledge layer.

Each carries a ``context`` mapping, like the rest of the system's exceptions, so
a caller reports what was attempted without parsing a message.
"""

from __future__ import annotations


class KnowledgeError(Exception):
    """Base for every error this package raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class RoleNameError(KnowledgeError):
    """A role name is not a safe directory name to build a knowledge path from."""


class StagingError(KnowledgeError):
    """A candidate could not be written: empty content, or an unsafe identifier."""
