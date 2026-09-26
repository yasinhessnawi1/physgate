"""Domain exceptions raised by the orchestrator.

Every one carries a ``context`` mapping, so a caller can report what was
attempted without parsing a message string. None of them is ever answered by
asking a model what to do: an exception here stops the step, and what happens
next is decided by code or by a person.
"""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base for every error this package raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class CorruptEventLogError(OrchestratorError):
    """The run-event log holds a complete line this package could not have written.

    A final line without its terminator is a process dying mid-write and is
    dropped. A complete line that does not parse, or that does not follow from
    the lines before it, was written by something else; dropping it would
    discard every valid line after it, so the log refuses to open instead.
    """


class RunConfigError(OrchestratorError):
    """A run's configuration is missing, already written, or not the recorded one."""


class ModelSeparationError(OrchestratorError):
    """A reviewer was about to run on the implementer's model string (ARCH-060)."""


class GateContractError(OrchestratorError):
    """A gate handed back a result for a mode it was not asked to run in."""


class AccountingError(OrchestratorError):
    """The token record contradicts itself: one message, two usages."""


class RoutingTokensError(OrchestratorError):
    """Tokens were attributed to routing, which the deterministic binding never spends."""
