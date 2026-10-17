"""Domain exceptions raised by the per-role evaluation, each with a ``context`` mapping."""

from __future__ import annotations


class PerRoleError(Exception):
    """Base for every error this package raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class TaskFormatError(PerRoleError):
    """A task, or an answer to one, is not in the format the scorers read."""


class ReferenceCheckError(PerRoleError):
    """A scorer passed a known-bad reference or failed the known-good one."""


class ControlEvalError(PerRoleError):
    """The public ControlEval data cannot be had as pinned, or is not whole."""


class SynthesisError(PerRoleError):
    """No reference answer could be built for a task as asked."""
