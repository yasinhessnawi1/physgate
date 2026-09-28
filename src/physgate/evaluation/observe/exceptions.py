"""Domain exceptions raised by the observability layer, each with a ``context`` mapping."""

from __future__ import annotations


class ObserveError(Exception):
    """Base for every error this package raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class ManifestError(ObserveError):
    """A run's records do not make a manifest: something is missing or disagrees."""


class PriceSheetError(ObserveError):
    """A price sheet is missing, incomplete, or not the one its date was recorded with."""


class TrendError(ObserveError):
    """The cost trend file refuses a line, or holds one it could not have written."""


class RerunError(ObserveError):
    """A rerun cannot be made from the recorded run as asked."""


class CompareRefusedError(ObserveError):
    """Two runs were measured under different pinned models, binary or endpoint."""


class VarianceError(ObserveError):
    """Runs handed to the variance measurement are not repeats of one configuration."""
