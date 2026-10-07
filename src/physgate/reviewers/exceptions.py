"""Domain exceptions raised while preparing or reading a review.

Each carries a ``context`` mapping, like the rest of the system's exceptions. None
is answered by reviewing less: a review that cannot be prepared as specified does
not run.
"""

from __future__ import annotations


class ReviewError(Exception):
    """Base for every error this package raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class ReviewRootError(ReviewError):
    """The directory reviews are read from would name the harness, or sits inside a checkout."""
