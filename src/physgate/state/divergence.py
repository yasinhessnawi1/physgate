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

It also names a change that breaks a cross-cutting duty (ARCH-051): a cross node
by a role that does not own the cross nodes, a domain node by the role that does,
an interface node created during a step or a node turned into one, any node by the
role that owns completion. The store holds none of these rules, so recorded runs and corpora
written straight into a store replay as they were; whoever checks a step asks the
role register who owns each duty and passes the answer in, or says by name that it
checks ownership alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from physgate.state.protocol import REJECT_CROSS_ROLE, NodeChange
from physgate.state.schema import validate_node_id
from physgate.state.store import Store


def _owner_the_guard_would_have_checked(store: Store, change: NodeChange) -> str:
    """The owner of ``change``'s node as it stood immediately before the change."""
    earlier = [rev for rev in store.history(change.node_id) if rev < change.revision]
    revision = max(earlier) if earlier else change.revision
    owner: str = store.payload_at(revision)["owner_role"]
    return owner


#: Not the store's reasons: a cross node written by a role that does not own the cross
#: nodes, or a node of a domain by the role that does; an interface node created during a
#: step; a node written by the role that owns completion. The hook and the apply step give
#: the same names when they refuse the same writes.
CROSS_NODE = "cross_node"
INTERFACE_CREATION = "interface_creation"
COMPLETION_OWNER_NODE = "completion_owner_node"

#: The domain of the quantities that tie domains together, and the kind of node a plan fixes
#: between modules (``schema.DomainKind``, ``schema.NodeKind``).
_CROSS = "cross"
_INTERFACE = "interface"


@dataclass(frozen=True)
class Duties:
    """Who the role register says owns each cross-cutting duty, when a step is checked.

    Each field is the sorted names of the registered roles that own the duty: one, none,
    or more than one. The register refuses a second owner when it is built, but it is a
    mapping that can be changed afterwards, so the answer may still name two. This package
    reads no register; whoever checks a step asks it and passes the answer here.
    """

    cross_nodes: tuple[str, ...]
    completion: tuple[str, ...]


@dataclass(frozen=True)
class OwnershipOnly:
    """No cross-cutting duty is held: only ownership is checked.

    For a store no role register stands behind, as every store was before the duties
    existed. It is not :class:`Duties` with no owners: a register that names nobody as
    owning the cross nodes still holds the duty, and every cross write is then named.
    """


#: The one value a caller passes to ask for ownership alone, by name.
OWNERSHIP_ONLY = OwnershipOnly()


@dataclass(frozen=True)
class Divergence:
    """One node changed during a step by a role that does not own it, or against a duty."""

    node_id: str
    revision: int
    owner_role: str
    acting_role: str
    #: Why it is named: the store's ``cross_role_write`` for a node the acting role did not
    #: own, or one of the duties' reasons above.
    reason: str = REJECT_CROSS_ROLE
    #: What the duty's reason means for this change; empty for a node the role did not own.
    detail: str = ""

    def __str__(self) -> str:
        """A one-line description, for a log or a failure message."""
        if self.reason == REJECT_CROSS_ROLE:
            return (
                f"{self.node_id} at revision {self.revision} is owned by "
                f"{self.owner_role!r} but changed during a step assigned to "
                f"{self.acting_role!r}"
            )
        return (
            f"{self.node_id} at revision {self.revision}, changed during a step assigned to "
            f"{self.acting_role!r}, breaks a duty ({self.reason}): {self.detail}"
        )


def divergence(
    store: Store,
    changes: list[NodeChange],
    acting_role: str,
    duties: Duties | OwnershipOnly,
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

    **Given the duties, a change to a node the acting role owned is also held to them**:
    a node of the cross domain written by a role that does not own the cross nodes, or a
    node of a domain by the role that does; an interface node created during the step, or
    a node turned into one; any node written by the role that owns completion. The store
    holds none of these, so a write that bypassed the hook and the apply step reaches the
    record, and is named here. A change already named for its owner is not named again.

    Args:
        store: the store the changed nodes are read from.
        changes: the changes since the revision the step started at.
        acting_role: the role the step was dispatched to.
        duties: who the role register says owns each cross-cutting duty, asked by the
            caller when the step is checked; or :data:`OWNERSHIP_ONLY`, which checks
            ownership alone, as for a store no register stands behind. Always passed, so
            a caller cannot drop the duties by leaving them out.

    Returns:
        One entry per offending change, in the order the changes arrived. A node
        changed more than once in the step appears once per change, because each
        one is a separate event in the record.

    Raises:
        MalformedNodeIdError: a change names an identifier no writer of this
            package could have produced. It raises rather than skipping: a
            foreign write must not pass unreported by being malformed as well as
            foreign.
        StoreStaleError: the journal moved underneath the handle mid-check.
        RevisionNotFoundError: a change names a revision the store never minted.
        NodeNotFoundError: a change names a node the store has never held.

    Limitations:
        It takes the concrete store rather than the frozen interface, because the
        interface cannot answer a question about a past revision and widening it
        was refused. A second store implementation would therefore need this
        function reworked, or the interface reopened as a decision.
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
            continue
        if isinstance(duties, OwnershipOnly):
            continue
        broken = _duty_broken(store, change, acting_role, duties)
        if broken is not None:
            reason, detail = broken
            found.append(
                Divergence(
                    node_id=change.node_id,
                    revision=change.revision,
                    owner_role=owner,
                    acting_role=acting_role,
                    reason=reason,
                    detail=detail,
                )
            )
    return found


def _duty_broken(
    store: Store, change: NodeChange, acting_role: str, duties: Duties
) -> tuple[str, str] | None:
    """The first cross-cutting duty ``change`` breaks, as (reason, what it means), or ``None``.

    In the order the hook and the apply step hold a proposal to them: the cross nodes, no
    interface made in a step, the owner of completion. The writer is the role the step
    was dispatched to, which by now owned the node before the change. An interface is
    exempt from the cross rule only if the node was created as one and is one still: a node
    turned into an interface after its creation was never one of decomposition's, and is
    named as an interface made, whatever its domain. The hook and apply refuse that write
    as a kind change, which the store accepts from the owner; this names it in the record.
    """
    payload = store.payload_at(change.revision)
    first = min(store.history(change.node_id))
    node_id, kind, domain = change.node_id, payload.get("kind"), payload.get("domain")
    created_as_interface = store.payload_at(first).get("kind") == _INTERFACE
    if not (kind == _INTERFACE and created_as_interface):
        cross = domain == _CROSS
        owners = duties.cross_nodes
        if len(owners) > 1:
            return CROSS_NODE, (
                f"the role register named more than one owner of the cross nodes "
                f"({','.join(owners)}), so whose they are cannot be told, and no node but an "
                "interface is written while it does"
            )
        if not owners and cross:
            return CROSS_NODE, (
                f"{node_id} is of the cross domain, and no registered role owns the cross "
                "nodes, so no step writes one"
            )
        if owners and cross and acting_role != owners[0]:
            return CROSS_NODE, (
                f"{node_id} is of the cross domain, whose quantities tie domains together; only "
                f"the {owners[0]} role writes them, and the step was the {acting_role} role's"
            )
        if owners and not cross and acting_role == owners[0]:
            return CROSS_NODE, (
                f"{node_id} is of the {domain} domain; the {owners[0]} role owns the cross "
                "nodes and writes no node of a domain"
            )
    if change.revision == first and kind == _INTERFACE:
        return INTERFACE_CREATION, (
            f"{node_id} was created as an interface node during the step; interface nodes are "
            "written from the plan when the task is decomposed, never by a session"
        )
    if kind == _INTERFACE and not created_as_interface:
        return INTERFACE_CREATION, (
            f"{node_id} was turned into an interface node, of the {domain} domain, after it "
            "was created as another kind; interface nodes are written from the plan when the "
            "task is decomposed, never by a session"
        )
    owners = duties.completion
    if len(owners) > 1:
        return COMPLETION_OWNER_NODE, (
            f"the role register named more than one owner of completion ({','.join(owners)}), "
            "so which role may write no node cannot be told, and no node is written while it does"
        )
    if owners and acting_role == owners[0]:
        return COMPLETION_OWNER_NODE, (
            f"the {owners[0]} role owns the completion declaration, which is its one write; it "
            "writes no node of the graph"
        )
    return None
