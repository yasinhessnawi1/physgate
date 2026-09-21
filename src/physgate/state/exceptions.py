"""Domain exceptions raised by the design-state package.

Every one carries a ``context`` mapping so a caller can report what was
attempted without re-deriving it from a message string.

These are raised, not returned. The store's *rejections* — a role writing a node
it does not own, a write to an interface node, a quantity with no unit — are
returned as a reason on the write result, because those three reasons are the
vocabulary the pre-registered store comparison counted its correctness score in.
Anything that is malformed input or a broken invariant rather than a policy
decision raises instead, which leaves that vocabulary closed.
"""

from __future__ import annotations


class DesignStateError(Exception):
    """Base for every error this package raises."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class MissingUnitError(DesignStateError):
    """A quantity was written without a unit, or without a number."""


class CrossRoleWriteError(DesignStateError):
    """A role attempted to write a node owned by a different role.

    Nothing in this package raises it. The store *returns* that refusal as a
    reason on the write result, because those reason strings are the closed
    vocabulary the store comparison counted its correctness in. This exists for
    the hook layer, which refuses the same write before it is attempted and has
    no write result to put a reason on.
    """


class InterfaceImmutableError(DesignStateError):
    """An interface node was written after it was created.

    Raised by nothing here, for the same reason as :class:`CrossRoleWriteError`.
    """


class MalformedNodeIdError(DesignStateError):
    """A node id is not a legal identifier.

    The graph keeps one file per node and builds that file's name from the id,
    so an id carrying a path separator or a parent reference would write outside
    the graph directory. Node ids come from agents, which makes this untrusted
    input. This is a raise rather than a rejection: a rejection reason would join
    the set the frozen correctness score counts, and change what those counters
    mean.
    """


class CorruptRecordError(DesignStateError):
    """A durable record holds a complete line that is not a valid record.

    Distinct from a torn tail. A torn tail is the expected consequence of a
    process dying mid-write and is dropped; a complete line that does not parse,
    or that names an identifier no writer of this package could have produced,
    means something wrote to the record that was not this package. Dropping it
    silently would discard every valid record after it as well, so the default is
    to refuse to open and to name the offset — and the way through is explicit,
    recorded, and asked for by the caller.
    """


class StoreStaleError(DesignStateError):
    """The durable record moved underneath this handle.

    A store handle rebuilds its indexes when it opens and not afterwards, so a
    handle held while another process writes would answer some reads from the
    current files and others from indexes that predate them — and would mint a
    revision number the other process has already used, leaving a node that no
    diff will ever return. Rather than answer inconsistently, it refuses.
    """
