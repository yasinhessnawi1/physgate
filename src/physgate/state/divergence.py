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

from physgate.state.protocol import DesignStateStore, NodeChange


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
    store: DesignStateStore,
    changes: list[NodeChange],
    acting_role: str,
) -> list[Divergence]:
    """Return every change in ``changes`` to a node ``acting_role`` does not own.

    Ownership is a fact about the graph, so the store is a parameter. It is not a
    method on the store because the store's interface is the one the pre-registered
    comparison froze, and this question is not part of it.

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
        owner = store.read_node(change.node_id)["owner_role"]
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
