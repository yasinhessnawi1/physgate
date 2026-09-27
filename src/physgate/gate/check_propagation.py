"""Check 7: a changed quantity reaches every node it constrains (ARCH-080, ARCH-082).

For every node whose quantities changed, every node its ``constrains`` edges
name must also have changed, in the same change set or a later one, or say in
its own ``no_change_justified`` why it did not need to. Otherwise the check
fails, naming each unwritten edge. A motor swapped for one with a different
stall current fails here when the current budget, the loop gain and the mount
are left as they were, though every module on its own is consistent: that is
the error no other check can see, because each of them looks at numbers that
are all still there.

**The unit of "the same commit" is one merged attempt**, and the check runs at
the integration call, over the change history the loop recorded: a role writes
only the nodes it owns, so the nodes a change constrains in other domains can
only follow in a later attempt.

What counts as a change, and what does not:

- A node **created** above the baseline has changed. Adding a motor without
  revisiting the budget it draws from is the same error as swapping one.
- A node rewritten with the **same physical values** has not: re-saving a
  number, or respelling 2.4 A as 2400 mA, excuses nothing, and on the side that
  changed it asks for nothing.
- An edge the change **dropped** still counts: taking the edge off does not take
  the obligation off.
- An obligation is owed from the **last** change that owed it: a target updated
  after that change was updated knowing everything before it.

What the check does not claim to know:

- A **justification** is the target's owner saying the target need not change.
  The check cannot verify the claim, so each justified edge is recorded as
  unchecked, never as passed. It counts only if the target was written in the
  change set that owed it or later: an excuse written before the source changed
  again excuses nothing about the new value.
- An edge into an **interface** node, which is fixed at decomposition and cannot
  be rewritten, or into a node that **does not exist**, is recorded as
  unchecked.
- With **no change history** at all, nothing can be said about what changed, and
  the check records that it did not judge rather than passing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from physgate.gate.context import CheckContext
from physgate.gate.graph import ChangeHistory, GraphView
from physgate.gate.result import CheckRun, Observation
from physgate.gate.units import PINT, UnitRefusedError, parse
from physgate.orchestrator.protocols import (
    NumericOutput,
    PropagationDetails,
    QuantityRef,
    UncheckedDetails,
)
from physgate.state.schema import Node, Quantity

TOOL = f"graph traversal; {PINT}"


@dataclass(frozen=True)
class _Owed:
    """One edge a change obliged to follow, and the change set it is owed from."""

    source: str
    target: str
    #: The position, in the history, of the last change set that obliged it.
    since: int
    #: The source's quantities that changed in that change set.
    changed: tuple[str, ...]


def run(ctx: CheckContext) -> CheckRun:
    """Judge every edge a change obliged to follow, over the whole graph."""
    view = ctx.view
    if view.history is None:
        return _without_history(view)
    index = _Index.of(view, view.history)
    satisfied = 0
    observations: list[Observation] = []
    unwritten: dict[str, list[_Owed]] = {}
    for edge in index.obligations():
        verdict = index.judge(edge)
        if verdict == "followed":
            satisfied += 1
        elif verdict == "unwritten":
            unwritten.setdefault(edge.source, []).append(edge)
        else:
            observations.append(_unchecked(view, edge, verdict))
    observations.extend(_failure(view, source, edges) for source, edges in unwritten.items())
    return CheckRun(tool=TOOL, evaluated=satisfied, observations=tuple(observations))


def _without_history(view: GraphView) -> CheckRun:
    """No history: say which quantities' propagation went unjudged, if any could owe it."""
    names = sorted(
        {name for node in view.nodes.values() if node.constrains for name in node.quantities}
    )
    if not names:
        return CheckRun(tool=TOOL, evaluated=0, observations=())
    unjudged = Observation(
        outcome="unchecked",
        node=None,
        module=None,
        value=None,
        expected=None,
        message=(
            "no change history was given, so which quantities changed, and whether each "
            "change reached the nodes it constrains, was not judged"
        ),
        details=UncheckedDetails(quantities=tuple(names)),
    )
    return CheckRun(tool=TOOL, evaluated=0, observations=(unjudged,))


@dataclass(frozen=True)
class _Change:
    """One node's change in one change set: what changed, and every edge it owes."""

    names: tuple[str, ...]
    #: Its edges before the change and after it: a dropped edge is still owed.
    edges: frozenset[str]


@dataclass(frozen=True)
class _Index:
    """The history laid over the graph: which change set wrote what, and what changed."""

    view: GraphView
    #: Each revision above the baseline, and the position of the change set that wrote it.
    position: Mapping[int, int]
    #: Per change set, in order: every node it changed.
    changed: tuple[Mapping[str, _Change], ...]

    @classmethod
    def of(cls, view: GraphView, history: ChangeHistory) -> _Index:
        position = {r: p for p, change in enumerate(history.change_sets) for r in change.revisions}
        changed: list[dict[str, _Change]] = []
        for change in history.change_sets:
            mine = set(change.revisions)
            first, last = change.revisions[0], change.revisions[-1]
            found: dict[str, _Change] = {}
            for node_id, revisions in view.timeline.items():
                if not any(r in mine for r, _ in revisions):
                    continue
                before, after = _at(view, node_id, first - 1), _at(view, node_id, last)
                if after is None:
                    continue  # written in this change set and gone after it: no such write
                names = _changed_names(before, after)
                if before is None or names:
                    edges = set(after.constrains) | set(before.constrains if before else ())
                    found[node_id] = _Change(names=names, edges=frozenset(edges - {node_id}))
            changed.append(found)
        return cls(view=view, position=position, changed=tuple(changed))

    def obligations(self) -> list[_Owed]:
        """Every edge some change obliged to follow, from the last change that obliged it."""
        latest: dict[tuple[str, str], _Owed] = {}
        for position, found in enumerate(self.changed):
            for source, change in found.items():
                for target in change.edges:
                    latest[(source, target)] = _Owed(source, target, position, change.names)
        return [latest[key] for key in sorted(latest)]

    def judge(self, edge: _Owed) -> str:
        """``followed``, ``unwritten``, or why the edge could not be judged."""
        view = self.view
        if edge.target not in view.nodes:
            return "missing"
        if any(edge.target in found for found in self.changed[edge.since :]):
            return "followed"
        target = view.nodes[edge.target]
        written = self.position.get(view.revisions[edge.target])
        if (
            edge.source in target.no_change_justified
            and written is not None
            and written >= edge.since
        ):
            return "justified"
        if target.kind == "interface":
            return "interface"
        return "unwritten"


def _at(view: GraphView, node_id: str, revision: int) -> Node | None:
    """``node_id`` as it stood at ``revision``, or ``None`` if it did not exist yet."""
    found: Node | None = None
    for written, node in view.timeline.get(node_id, ()):
        if written > revision:
            break
        found = node
    return found


def _changed_names(before: Node | None, after: Node) -> tuple[str, ...]:
    """The quantities added, removed, or given a different physical value, by name."""
    if before is None:
        return tuple(sorted(after.quantities))
    names = set(before.quantities) | set(after.quantities)
    return tuple(
        sorted(
            n
            for n in names
            if n not in before.quantities
            or n not in after.quantities
            or not _same(before.quantities[n], after.quantities[n])
        )
    )


def _same(left: Quantity, right: Quantity) -> bool:
    """Whether two declarations are one physical value: exactly, in base units.

    A spelling pint cannot read is compared as written; the unit check refuses it
    anyway, at every scope it runs.
    """
    if (left.value, left.unit) == (right.value, right.unit):
        return True
    try:
        a, b = parse(left.value, left.unit), parse(right.value, right.unit)
    except UnitRefusedError:
        return False
    if a.dimensionality != b.dimensionality:
        return False
    try:
        return Fraction(a.to_base_units().magnitude) == Fraction(b.to_base_units().magnitude)
    except Exception:  # noqa: BLE001 - pint raises several types on one unconvertible pair
        return False


def _refs(node_id: str, node: Node, names: tuple[str, ...]) -> tuple[QuantityRef, ...]:
    return tuple(
        QuantityRef(node_id=node_id, name=n, value=q.value, unit=q.unit)
        for n in names
        if (q := node.quantities.get(n)) is not None
    )


def _failure(view: GraphView, source: str, edges: list[_Owed]) -> Observation:
    node = view.nodes[source]
    changed = max(edges, key=lambda e: e.since).changed
    refs = _refs(source, node, changed)
    targets = sorted(e.target for e in edges)
    what = ", ".join(changed) if changed else "its creation"
    return Observation(
        outcome="fail",
        node=source,
        module=view.module_of(source),
        value=NumericOutput(value=refs[0].value, unit=refs[0].unit) if refs else None,
        expected=(
            f"every node {source} constrains is rewritten in the change that changed it or a "
            f"later one, or says in no_change_justified why it need not be"
        ),
        message=(
            f"{source} changed ({what}) and the nodes it constrains were not rewritten after "
            f"it and give no reason why not: {', '.join(targets)}"
        ),
        details=PropagationDetails(unwritten=tuple(f"{source}->{t}" for t in targets)),
        quantities=refs[:3],
    )


_WHY: Mapping[str, str] = {
    "missing": "is not in the graph, so whether it followed cannot be judged",
    "interface": "is an interface node, fixed at decomposition, so it cannot be rewritten",
}


def _unchecked(view: GraphView, edge: _Owed, why: str) -> Observation:
    if why == "justified":
        reason = view.nodes[edge.target].no_change_justified[edge.source]
        said = (
            f"was not rewritten, and its owner says why: {reason!r}; the claim is recorded, "
            "not verified"
        )
    else:
        said = _WHY[why]
    changed = edge.changed or tuple(sorted(view.nodes[edge.source].quantities)) or ("constrains",)
    return Observation(
        outcome="unchecked",
        node=edge.source,
        module=view.module_of(edge.source),
        value=None,
        expected=None,
        message=f"{edge.source} changed; {edge.target}, which it constrains, {said}",
        details=UncheckedDetails(quantities=changed),
    )
