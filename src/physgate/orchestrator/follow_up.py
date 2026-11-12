"""What sizing's closing pass owes the domain modules: a follow-up for each node it reached.

The propagation check (ARCH-082) fails a changed node whose ``constrains`` edges name a node
not rewritten after it that gives no reason in its own ``no_change_justified``. Sizing's closing
pass runs after every domain module, so a value it changes leaves each domain node that value
constrains unwritten, and only that node's owner may rewrite it or say why it need not change.
Before the integration call the loop therefore reopens, once, each domain module the pass
reached (ARCH-051).

Computed from the canonical journal and the change history alone, so a fresh process computes
the same, and on the safe side: a value counts as changed when its quantities differ as written,
a unit compared in its canonical form (another spelling of one unit is no change, another unit
such as ``mA`` for ``A`` is), where the check compares physical values. A follow-up the check
would not have asked for costs a session; none is ever left out that it would. The check stays
the authority over what passes.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from physgate.orchestrator.events import OwedEdge
from physgate.orchestrator.protocols import ChangeSet, PersonOrder
from physgate.orchestrator.repair import _quantity_name, quoted
from physgate.state.schema import Node, validate_node
from physgate.state.store import JournalLine
from physgate.unit_spelling import canonical_unit


def owed(
    lines: Sequence[JournalLine],
    change_sets: Sequence[ChangeSet],
    closing: str,
    candidates: Collection[str],
) -> Mapping[str, tuple[OwedEdge, ...]]:
    """Each candidate module the closing pass reached, by subtask id, with its edges, sorted.

    Each change set of the closing pass is judged on its own, as the propagation check judges
    them: a set that created a node, or wrote it with other quantities than it had before the set,
    changed it. An edge is owed from a node a closing set changed, from its constrains before or
    after any such set (a dropped edge still owes), into a node that exists, is not an interface
    node, was last written before the last closing set that changed the source, and was last
    written by a candidate: one of the domain modules that merged. So a closing pass that merges
    twice owes from its later set too, a value changed and then changed back included. ``lines``
    is the journal up to the change history's end.
    """
    writer = {r: c.subtask_id for c in change_sets for r in c.revisions}
    sets = sorted(
        (c.revisions for c in change_sets if c.subtask_id == closing and c.revisions), key=min
    )
    if not sets:
        return {}
    timeline: dict[str, list[tuple[int, Node]]] = {}
    for line in lines:
        timeline.setdefault(line.node_id, []).append((line.rev, validate_node(line.payload)))
    found: dict[str, set[tuple[str, str]]] = {}
    for source, revisions in timeline.items():
        written = {r for r, _ in revisions}
        since: int | None = None
        targets: set[str] = set()
        for revs in sets:
            if not written & set(revs):
                continue
            before = _at(revisions, min(revs) - 1)
            after = _at(revisions, max(revs))
            if after is None or (before is not None and _as_written(before) == _as_written(after)):
                continue
            since = min(revs)
            targets |= set(after.constrains) | set(before.constrains if before else ())
        if since is None:
            continue
        for target in targets:
            if target == source or target not in timeline:
                continue
            rev, node = timeline[target][-1]
            subtask_id = writer.get(rev)
            if subtask_id is None or subtask_id not in candidates:
                continue
            if node.kind == "interface" or rev >= since:
                continue
            found.setdefault(subtask_id, set()).add((source, target))
    return {
        subtask_id: tuple(OwedEdge(source=s, target=t) for s, t in sorted(edges))
        for subtask_id, edges in sorted(found.items())
    }


def _as_written(node: Node) -> dict[str, dict[str, object]]:
    """The node's quantities, each unit in its canonical form: a respelling is no change."""
    return {
        name: {**quantity.model_dump(mode="json"), "unit": canonical_unit(quantity.unit)}
        for name, quantity in node.quantities.items()
    }


def _at(revisions: Sequence[tuple[int, Node]], revision: int) -> Node | None:
    """The node as it stood at ``revision``, or ``None`` if it did not exist yet."""
    found = None
    for written, node in revisions:
        if written > revision:
            break
        found = node
    return found


def follow_up_order(
    lines: Sequence[JournalLine],
    change_sets: Sequence[ChangeSet],
    closing: str,
    edges: Sequence[OwedEdge],
    of_attempt: int,
) -> PersonOrder:
    """What a follow-up's one session is told, by code: each changed node and what it reaches.

    Each source as the closing pass left it in the journal, its quantities by name with value and
    unit, each part held to its form; never a quantity's free-text provenance. ``change_sets`` is
    the history where the follow-up was written, and ``of_attempt`` the attempt that merged.
    """
    from physgate.orchestrator import integration_state as render

    last = max(r for c in change_sets if c.subtask_id == closing for r in c.revisions)
    timeline: dict[str, list[tuple[int, Node]]] = {}
    for line in lines:
        timeline.setdefault(line.node_id, []).append((line.rev, validate_node(line.payload)))
    reached: dict[str, list[str]] = {}
    for edge in edges:
        reached.setdefault(edge.source, []).append(render.held(edge.target))
    changed = []
    for source, targets in reached.items():
        node = _at(timeline.get(source, []), last)
        values = "; ".join(
            f"quantity {render.q(name) if _quantity_name(name) else 'with a refused name'} = "
            f"{render.measure(quantity.value, quantity.unit)}"
            for name, quantity in sorted(node.quantities.items() if node else ())
        )
        changed.append(
            f"Node {render.held(source)} holds {values or 'no quantity'}; it constrains this "
            f"module's node {', '.join(targets)}."
        )
    instruction = "\n".join(
        [
            "Sizing's closing pass, which settles the cross values after every domain module, "
            "changed values that constrain nodes of this module, merged at attempt "
            f"{of_attempt}, and no session wrote those nodes after it. This attempt is the "
            "module's one follow-up, ordered by code: it is not repaired or retried.",
            "",
            "Each changed node as the design graph holds it now, and this module's nodes it "
            "constrains:",
            *quoted("\n".join(changed)),
            "For each node of this module named above: rewrite it so it agrees with the changed "
            "values, or keep its values and write in its no_change_justified, under the changed "
            "node's id, why it need not change.",
            "The specification as issued otherwise still governs.",
        ]
    )
    return PersonOrder(kind="follow_up", of_attempt=of_attempt, instruction=instruction)
