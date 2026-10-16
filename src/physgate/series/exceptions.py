"""Domain exceptions raised by the series package.

Every one carries a ``context`` mapping, so a caller can report what was refused
without re-deriving it from the message.
"""

from __future__ import annotations


class SeriesError(Exception):
    """Base for every error this package raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class RecordRefusedError(SeriesError):
    """A series record is not one this format admits: malformed, unbounded or unitless."""


class RecordTamperedError(SeriesError):
    """A sealed series record is missing, or is not the bytes its seal names."""
