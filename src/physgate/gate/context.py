"""What a check is handed when it runs: the graph, and the scope it runs at."""

from __future__ import annotations

from dataclasses import dataclass

from physgate.gate.graph import GraphView
from physgate.orchestrator.protocols import Scope


@dataclass(frozen=True)
class CheckContext:
    """One check's input at one scope.

    At ``subtask`` scope a check looks at the attempt's own nodes; at ``module``
    scope at the modules the attempt touched; at ``system`` scope at the whole
    graph. Which nodes those are is read off ``view``.
    """

    view: GraphView
    scope: Scope
