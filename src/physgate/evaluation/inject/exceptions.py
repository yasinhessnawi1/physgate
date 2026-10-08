"""Domain exceptions raised by the injected-error instrument.

Each carries a ``context`` mapping, like the rest of the system's exceptions. None
is answered by skipping an artefact: a corpus that does not load, or a reviewer
that could have seen an answer, stops the run before a row is written for it.
"""

from __future__ import annotations


class InstrumentError(Exception):
    """Base for every error the instrument raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class CorpusError(InstrumentError):
    """The corpus on disk is not the committed one, or is not a corpus at all."""


class BlindnessError(InstrumentError):
    """What a reviewer was about to be shown carries something that states an answer."""


class ReviewerRefusedError(InstrumentError):
    """No reviewer is registered for an artefact, or one is on the corpus author's model."""


class RunDirectoryError(InstrumentError):
    """The run or scratch directory is not fresh, or lies inside what a reviewer may not read."""


class InstrumentParamsError(InstrumentError):
    """The parameters the real reviewers run under are missing or incomplete."""
