"""What sizing's closing pass owes the domain modules: a follow-up for each node it reached.

The propagation check (ARCH-082) fails a changed node whose ``constrains`` edges name a node
not rewritten after it that gives no reason in its own ``no_change_justified``. Sizing's closing
pass runs after every domain module, so a value it changes leaves each domain node that value
constrains unwritten, and only that node's owner may rewrite it or say why it need not change.
Before the integration call the loop therefore reopens, once, each domain module the pass
reached (ARCH-051).

Computed from the canonical journal and the change history alone, so a fresh process computes
the same, and on the safe side: a value counts as changed when its quantities differ as written
(a respelled unit included), where the check compares physical values. A follow-up the check
would not have asked for costs a session; none is ever left out that it would. The check stays
the authority over what passes.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from physgate.orchestrator.events import OwedEdge
from physgate.orchestrator.protocols import ChangeSet
from physgate.state.schema import Node, validate_node
from physgate.state.store import JournalLine


def owed(
    lines: Sequence[JournalLine],
    change_sets: Sequence[ChangeSet],
    closing: str,
    candidates: Collection[str],
) -> Mapping[str, tuple[OwedEdge, ...]]:
    """Each candidate module the closing pass reached, by subtask id, with its edges, sorted.

    An edge is owed from a node the closing pass created or wrote with other quantities, before
    or after its write (a dropped edge still owes), into a node that exists, is not an interface
    node, was last written before the closing pass, and was last written by a candidate: one of
    the domain modules that merged. ``lines`` is the journal up to the change history's end.
    """
    writer = {r: c.subtask_id for c in change_sets for r in c.revisions}
    ours = sorted(r for r, subtask_id in writer.items() if subtask_id == closing)
    if not ours:
        return {}
    timeline: dict[str, list[tuple[int, Node]]] = {}
    for line in lines:
        timeline.setdefault(line.node_id, []).append((line.rev, validate_node(line.payload)))
    found: dict[str, set[tuple[str, str]]] = {}
    for source, revisions in timeline.items():
        before = _at(revisions, ours[0] - 1)
        after = _at(revisions, ours[-1])
        if after is None or not any(r in ours for r, _ in revisions):
            continue
        if before is not None and before.quantities == after.quantities:
            continue
        for target in set(after.constrains) | set(before.constrains if before else ()):
            if target == source or target not in timeline:
                continue
            rev, node = timeline[target][-1]
            subtask_id = writer.get(rev)
            if subtask_id is None or subtask_id not in candidates:
                continue
            if node.kind == "interface" or rev >= ours[0]:
                continue
            found.setdefault(subtask_id, set()).add((source, target))
    return {
        subtask_id: tuple(OwedEdge(source=s, target=t) for s, t in sorted(edges))
        for subtask_id, edges in sorted(found.items())
    }


def _at(revisions: Sequence[tuple[int, Node]], revision: int) -> Node | None:
    """The node as it stood at ``revision``, or ``None`` if it did not exist yet."""
    found = None
    for written, node in revisions:
        if written > revision:
            break
        found = node
    return found
