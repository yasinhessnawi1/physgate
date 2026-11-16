"""What a check is handed when it runs: the graph, the scope, and the gate's tables."""

from __future__ import annotations

from dataclasses import dataclass

from physgate.gate.bounds_table import Bounds
from physgate.gate.equilibrium import EquilibriumSolver
from physgate.gate.graph import GraphView
from physgate.gate.laws import LawTable
from physgate.orchestrator.protocols import Scope


@dataclass(frozen=True)
class CheckContext:
    """One check's input at one scope.

    At ``subtask`` scope a check looks at the attempt's own nodes; at ``module``
    scope at the modules the attempt touched; at ``system`` scope at the whole
    graph. Which nodes those are is read off ``view``. ``bounds`` is the sourced
    bounds table, loaded once when the gate is built. ``solver`` stands behind
    the equilibrium check; ``None`` means the closed form. ``laws`` is the law
    table the gate was built with, which the laws check judges; the gate always
    hands it over, and no other check reads it.
    """

    view: GraphView
    scope: Scope
    bounds: Bounds
    solver: EquilibriumSolver | None = None
    laws: LawTable | None = None
