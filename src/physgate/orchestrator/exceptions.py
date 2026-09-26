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


class RepairBudgetExhaustedError(OrchestratorError):
    """An attempt past the repair budget was asked for. The budget is three (ARCH-030)."""


class QueueError(OrchestratorError):
    """The approval queue was asked to do something its record forbids."""


class MergePreconditionError(OrchestratorError):
    """A merge was about to happen without what the ledger must show first (ARCH-001)."""


class GateNotRegisteredError(OrchestratorError):
    """The gate stage cannot pass: the run's gate mode needs a gate and none is registered."""


class ReviewerNotRegisteredError(OrchestratorError):
    """A role has no registered reviewer, or one on a model the run did not pin."""


class RunStateError(OrchestratorError):
    """The run is not in a state that allows what was asked: started twice, or interrupted."""


class GitError(OrchestratorError):
    """A git command failed. The step stops; nothing retries it."""


class MergeConflictError(OrchestratorError):
    """An accepted attempt did not merge cleanly.

    Under serial dispatch this means an invariant broke, so the run halts rather
    than charging the agent.
    """


class MergeRefusedError(OrchestratorError):
    """The commit about to be merged is not the one that was checked."""


class InvocationError(OrchestratorError):
    """A Claude Code session cannot be invoked as measured: no binary, or another version."""


class DecompositionError(OrchestratorError):
    """The decomposition's plan cannot be written: a node the store refuses, a bad path."""


class StoreRefusalError(OrchestratorError):
    """The store refused a write the pre-check had accepted. An incident, never a retry."""


class TrajectoryTamperedError(OrchestratorError):
    """A session's captured stream is not what the runtime wrote, or not what was sealed."""
