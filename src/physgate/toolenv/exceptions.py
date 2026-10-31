"""Domain exceptions of the tool environment."""

from __future__ import annotations


class ToolEnvironmentError(Exception):
    """The tool environment is refused, or is not the one a run recorded."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)
