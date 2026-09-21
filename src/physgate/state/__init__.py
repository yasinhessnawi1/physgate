"""The design-state graph and the task ledger.

This package owns the durable record of what has been designed: one JSON file
per graph node, an append-only journal that is the authority those files are
derived from, and a separate append-only ledger of dispatched subtasks.

A store handle is a view as of open, and one process holds the store at a time.
If the journal moves underneath a handle it refuses to answer rather than
answering inconsistently. ``README.md`` in this directory says why that matters
and what else this package deliberately does not own.
"""

from physgate.state.exceptions import (
    CrossRoleWriteError,
    DesignStateError,
    InterfaceImmutableError,
    MalformedNodeIdError,
    MissingUnitError,
    StoreStaleError,
)
from physgate.state.protocol import (
    REJECT_CROSS_ROLE,
    REJECT_DUPLICATE_NODE,
    REJECT_INTERFACE_IMMUTABLE,
    REJECT_MISSING_UNIT,
    REJECT_UNKNOWN_NODE,
    DesignStateStore,
    NodeChange,
    NodeNotFoundError,
    Revision,
    WriteResult,
    canonical_json,
)
from physgate.state.schema import Node, Quantity, validate_node, validate_node_id
from physgate.state.task_ledger import TaskLedger, TaskLine, TornLineError

__all__ = [
    "REJECT_CROSS_ROLE",
    "REJECT_DUPLICATE_NODE",
    "REJECT_INTERFACE_IMMUTABLE",
    "REJECT_MISSING_UNIT",
    "REJECT_UNKNOWN_NODE",
    "CrossRoleWriteError",
    "DesignStateError",
    "DesignStateStore",
    "InterfaceImmutableError",
    "MalformedNodeIdError",
    "MissingUnitError",
    "Node",
    "NodeChange",
    "NodeNotFoundError",
    "Quantity",
    "Revision",
    "StoreStaleError",
    "TaskLedger",
    "TaskLine",
    "TornLineError",
    "WriteResult",
    "canonical_json",
    "validate_node",
    "validate_node_id",
]
