"""The design-state graph as the gate reads it: from the journal, read-only.

The gate never opens a store. Opening one runs recovery, which rewrites node
files and moves unknown files aside, and a gate that wrote to the graph it judges
would no longer be only a judge. So it reads the journal alone, through the state
package's read-only reader, which holds every line to the same rules recovery
applies, and takes each node's latest payload. Each payload is validated as a
whole node again here: the gate does arithmetic on these numbers, and a number no
schema has seen is not one it will do arithmetic on.

A record the state package refuses raises out of the gate. That fails closed: the
step stops, and no verdict is invented for a graph nobody can read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from physgate.state.schema import Node, validate_node
from physgate.state.store import journal_records_after


@dataclass(frozen=True)
class GraphView:
    """Every node at its latest revision, and which of them one attempt wrote."""

    nodes: Mapping[str, Node]
    revisions: Mapping[str, int]
    #: The canonical journal's head before the attempt: nodes above it are the attempt's.
    base_revision: int

    @classmethod
    def read(cls, root: Path, base_revision: int) -> GraphView:
        """Read the graph at ``root`` without writing anything.

        Raises:
            CorruptRecordError: a journal line is not one the store could have written.
            DesignStateError: a node does not validate as a whole node.
        """
        latest = {line.node_id: line for line in journal_records_after(Path(root), 0)}
        nodes = {node_id: validate_node(line.payload) for node_id, line in latest.items()}
        revisions = {node_id: line.rev for node_id, line in latest.items()}
        return cls(
            nodes=MappingProxyType(dict(sorted(nodes.items()))),
            revisions=MappingProxyType(dict(sorted(revisions.items()))),
            base_revision=base_revision,
        )

    def own(self) -> tuple[str, ...]:
        """The nodes the attempt wrote: those whose latest revision is above the base."""
        return tuple(n for n, rev in self.revisions.items() if rev > self.base_revision)

    def constrained_by(self, target: str) -> tuple[str, ...]:
        """The nodes whose ``constrains`` edges name ``target``, in id order."""
        return tuple(n for n, node in self.nodes.items() if target in node.constrains)

    def module_of(self, node_id: str) -> str | None:
        """The module a node belongs to: itself if it is one, else the first it constrains."""
        node = self.nodes[node_id]
        if node.kind == "module":
            return node_id
        modules = sorted(
            t for t in node.constrains if t in self.nodes and self.nodes[t].kind == "module"
        )
        return modules[0] if modules else None

    def modules_touched(self) -> tuple[str, ...]:
        """The modules the attempt's own nodes are, or constrain directly, in id order."""
        found: set[str] = set()
        for node_id in self.own():
            node = self.nodes[node_id]
            if node.kind == "module":
                found.add(node_id)
            found.update(
                t for t in node.constrains if t in self.nodes and self.nodes[t].kind == "module"
            )
        return tuple(sorted(found))

    def modules(self) -> tuple[str, ...]:
        """Every module in the graph, in id order."""
        return tuple(n for n, node in self.nodes.items() if node.kind == "module")
