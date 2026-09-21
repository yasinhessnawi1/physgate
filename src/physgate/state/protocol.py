"""The design-state store interface, and the small types that cross it.

Promoted from the pre-registered store comparison (R-OP-01) unchanged. The
experiment froze this surface before either implementation existed and scored
both against it; widening it here would make the promoted store something the
comparison never measured, and would leave a future backend implementing methods
no experiment ever exercised. The eight methods, their signatures and their
semantics are the frozen ones.

The Protocol declares no exception behaviour, so the domain exceptions this
package raises are not an extension of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

Revision = int

#: Rejection reasons. These exact strings are what the frozen workload's
#: correctness score is counted in, so they are a fixed vocabulary: a new
#: failure mode raises rather than joining this set, or the counters stop
#: meaning what they meant when the store was measured.
REJECT_CROSS_ROLE = "cross_role_write"
REJECT_INTERFACE_IMMUTABLE = "interface_immutable"
REJECT_MISSING_UNIT = "quantity_missing_unit"
REJECT_UNKNOWN_NODE = "unknown_node"
REJECT_DUPLICATE_NODE = "duplicate_node"


@dataclass(frozen=True)
class WriteResult:
    """What a write attempt did.

    A rejected write mints no revision and leaves the graph untouched.
    """

    accepted: bool
    revision: Revision | None = None
    reason: str | None = None


@dataclass(frozen=True)
class NodeChange:
    """One accepted mutation, as reported by ``diff``."""

    revision: Revision
    node_id: str
    version: int
    op: str  # "create" | "write" | "rollback"


class NodeNotFoundError(LookupError):
    """Raised by ``read_node`` for an id the store has never held."""


@runtime_checkable
class DesignStateStore(Protocol):
    """The design-state graph store the orchestrator reads and writes."""

    def write_node(self, node: dict[str, Any], actor_role: str) -> WriteResult:
        """Create or update ``node`` on behalf of ``actor_role``."""
        ...

    def read_node(self, node_id: str) -> dict[str, Any]:
        """Return the current payload of ``node_id``."""
        ...

    def diff(self, since: Revision) -> list[NodeChange]:
        """Return every accepted mutation with a revision greater than ``since``."""
        ...

    def traverse_constrains(self, node_id: str) -> list[str]:
        """Return the transitive ``constrains`` closure of ``node_id``, breadth first."""
        ...

    def history(self, node_id: str) -> list[Revision]:
        """Return every revision of ``node_id``, oldest first."""
        ...

    def rollback(self, node_id: str, to: Revision) -> None:
        """Append a new head whose payload equals the payload at ``to``."""
        ...

    def head_revision(self) -> Revision:
        """The highest revision the store has minted. Zero on an empty store."""
        ...

    def close(self) -> None:
        """Release any handles. Idempotent."""
        ...


def canonical_json(payload: dict[str, Any]) -> str:
    """Stable serialisation used for payload equality."""
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
