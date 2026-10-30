"""The canonical graph as a contract reads it: every node at one revision of the journal.

A contract result is taken over the graph at the journal revision the run's log records. The
journal alone is read, and the store is never opened, since opening runs recovery, which writes. So
any later process that reads the same journal at the same revision reads the same nodes, and can
take the same result again.
"""

from __future__ import annotations

from pathlib import Path

from physgate.state.exceptions import StoreStaleError
from physgate.state.schema import Node, validate_node
from physgate.state.store import journal_records_after


def nodes_at(root: Path, revision: int) -> dict[str, Node]:
    """Every node of the store at ``root`` as journal ``revision`` left it, in id order.

    Raises:
        StoreStaleError: the journal ends before ``revision``, so the store does not hold what the
            run recorded.
        DesignStateError: a journal line, or the node it holds, is not one the store could write.
    """
    lines = [line for line in journal_records_after(Path(root), 0) if line.rev <= revision]
    if not lines or lines[-1].rev != revision:
        msg = "the canonical journal ends before the revision the run records"
        ends = str(lines[-1].rev) if lines else "0"
        raise StoreStaleError(msg, revision=str(revision), journal_ends_at=ends)
    latest = {line.node_id: line for line in lines}
    return {node_id: validate_node(latest[node_id].payload) for node_id in sorted(latest)}
