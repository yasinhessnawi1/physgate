/**
 * A node's `constrains` edges both ways, from the graph as recorded. The record holds only the
 * outgoing list, so the incoming one is the same edges read the other way: an inversion, not a
 * figure. An edge whose target the graph does not hold at this revision is kept and said so,
 * because a typo'd target is accepted when it is written and only shows here.
 */
import type { NodeRecord } from "../../api/graph";

export interface EdgeEnd {
  readonly id: string;
  /** The node at the other end, or ``null`` when the graph does not hold it at this revision. */
  readonly node: NodeRecord | null;
}

export interface NodeEdges {
  readonly constrains: readonly EdgeEnd[];
  readonly constrainedBy: readonly EdgeEnd[];
}

export function edgesOf(id: string, nodes: readonly NodeRecord[]): NodeEdges {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const self = byId.get(id);
  return {
    constrains: (self?.constrains ?? []).map((target) => ({
      id: target,
      node: byId.get(target) ?? null,
    })),
    constrainedBy: nodes
      .filter((n) => n.constrains.includes(id))
      .map((n) => ({ id: n.id, node: n }))
      .sort((a, b) => a.id.localeCompare(b.id)),
  };
}

/** Every edge whose target the graph does not hold, as ``[from, to]``. */
export function missingTargets(
  nodes: readonly NodeRecord[],
): readonly (readonly [string, string])[] {
  const held = new Set(nodes.map((n) => n.id));
  return nodes.flatMap((n) =>
    n.constrains.filter((t) => !held.has(t)).map((t): readonly [string, string] => [n.id, t]),
  );
}
