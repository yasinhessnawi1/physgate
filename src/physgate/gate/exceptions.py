"""Domain exceptions raised by the physics gate.

Each carries a ``context`` mapping, like the rest of the system's exceptions, so a
caller reports what was attempted without parsing a message. None of them is
answered by guessing a verdict: an exception here stops the step.
"""

from __future__ import annotations


class GateError(Exception):
    """Base for every error the gate raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class GateModeError(GateError):
    """The gate was asked to run in a mode in which no gate runs, or in no mode at all."""


class NothingCheckedError(GateError):
    """A gate call in which no check ran: there is no verdict to give, so none is given."""


class ChangeHistoryError(GateError):
    """A change history that does not describe the journal the gate was asked to read."""


class LawRecordError(GateError):
    """A law record that does not agree with the law table the gate was built with.

    A law the table does not hold, a status other than the table's, a count that is not the
    law's, or a law reported by a check other than the laws check: the runner would otherwise
    have to guess whether the failure blocks, so it stops instead.
    """
