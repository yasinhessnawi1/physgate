"""Name every node in a change list that the acting role does not own.

The store refuses a cross-role write at the point of writing. This is the second
line, and it reads the durable record rather than trusting that the first line
ran: it takes the changes since a revision and the role that was dispatched, and
names anything in them owned by somebody else. A write that reached the graph
without passing the store's guard — a file edited directly in a worktree, a
journal line appended by something that is not this class — is invisible to the
guard and visible here.

That is why this is a separate function over a change list and not a method on
the store. It answers a question about a step, and it must be able to answer it
about changes the store did not make.
"""

from __future__ import annotations

from dataclasses import dataclass

from physgate.state.protocol import NodeChange
from physgate.state.schema import validate_node_id
from physgate.state.store import Store


def _owner_the_guard_would_have_checked(store: Store, change: NodeChange) -> str:
    """The owner of ``change``'s node as it stood immediately before the change."""
    earlier = [rev for rev in store.history(change.node_id) if rev < change.revision]
    revision = max(earlier) if earlier else change.revision
    owner: str = store.payload_at(revision)["owner_role"]
    return owner


@dataclass(frozen=True)
class Divergence:
    """One node changed during a step by a role that does not own it."""

    node_id: str
    revision: int
    owner_role: str
    acting_role: str

    def __str__(self) -> str:
        """A one-line description, for a log or a failure message."""
        return (
            f"{self.node_id} at revision {self.revision} is owned by "
            f"{self.owner_role!r} but changed during a step assigned to "
            f"{self.acting_role!r}"
        )


def divergence(
    store: Store,
    changes: list[NodeChange],
    acting_role: str,
) -> list[Divergence]:
    """Return every change in ``changes`` to a node ``acting_role`` does not own.

    Ownership is a fact about the graph, so the store is a parameter. It is not a
    method on the store because the store's interface is the one the
    pre-registered comparison froze, and this question is not part of it.

    **Ownership is the owner the store's own guard would have checked**, which is
    not the owner now and is not the owner in the changed payload either. The
    guard admits a write when the acting role owns the node *as it stood before
    the write*, so that is what this reads: the payload at the node's previous
    revision, or — for a create, which has no previous — the payload being
    created, which is exactly what the guard falls back to.

    Both of the other readings are wrong and wrong differently. Reading the
    owner *now* reports a false positive on every legitimate handover: a role
    that writes its own node and passes ownership on is reported as having
    written someone else's. Reading the owner from the changed payload is worse,
    because it lets a foreign writer clear itself by putting its own name in the
    payload it is not entitled to write.

    The parameter is the concrete store rather than the frozen interface for this
    reason — the interface cannot answer a question about a past revision, and
    widening it was refused.

    Args:
        store: the store the changed nodes are read from.
        changes: the changes since the revision the step started at.
        acting_role: the role the step was dispatched to.

    Returns:
        One entry per offending change, in the order the changes arrived. A node
        changed more than once in the step appears once per change, because each
        one is a separate event in the record.
    """
    found: list[Divergence] = []
    for change in changes:
        # An identifier no writer of this package could have produced means
        # something reached the record without passing the store. Raising here
        # rather than skipping is the point: a foreign write must not become
        # invisible by being malformed as well as foreign.
        validate_node_id(change.node_id)
        owner = _owner_the_guard_would_have_checked(store, change)
        if owner != acting_role:
            found.append(
                Divergence(
                    node_id=change.node_id,
                    revision=change.revision,
                    owner_role=owner,
                    acting_role=acting_role,
                )
            )
    return found
