/**
 * The design graph's records as the server sends them: the graph at a revision, one node's
 * history, and the store's change list between two revisions. Each guard checks the fields the
 * graph views show; a quantity is refused unless it is a value with its unit.
 */
import type { Quantity } from "../design/quantity";
import { requireQuantity } from "../design/quantity";
import { count, list, object, oneOf, text } from "./check";

export const DOMAINS = ["mechanical", "electrical", "control", "firmware", "cross"] as const;
export type Domain = (typeof DOMAINS)[number];

export interface NodeRecord {
  readonly id: string;
  readonly kind: string;
  readonly domain: Domain;
  readonly owner: string;
  /** The journal revision this state of the node was written at. */
  readonly revision: number;
  readonly constrains: readonly string[];
  readonly quantities: readonly (readonly [string, Quantity])[];
}

/** A node as the server sends it beside its revision: ``{revision, node}``. */
export function nodeAt(value: unknown): NodeRecord {
  const entry = object(value, "a node at a revision");
  const node = object(entry.node, "a node");
  return {
    id: text(node.id, "a node id"),
    kind: text(node.kind, "a node kind"),
    domain: oneOf(node.domain, DOMAINS, "a node domain"),
    owner: text(node.owner_role, "a node's owner"),
    revision: count(entry.revision, "a revision"),
    constrains: list(node.constrains, "a node's edges").map((t) => text(t, "an edge target")),
    quantities: Object.entries(object(node.quantities, "a node's quantities")).map(
      ([name, q]): readonly [string, Quantity] => [name, requireQuantity(q)],
    ),
  };
}

export interface GraphAt {
  readonly revision: number;
  readonly headRevision: number;
  readonly nodes: readonly NodeRecord[];
}

/** The graph at a revision; the head graph's answer names no revision and is the head's. */
export function graphAt(value: unknown): GraphAt {
  const graph = object(value, "a graph");
  const head = count(graph.head_revision, "a head revision");
  return {
    revision: graph.revision === undefined ? head : count(graph.revision, "a revision"),
    headRevision: head,
    nodes: Object.values(object(graph.nodes, "the graph's nodes")).map(nodeAt),
  };
}

export type Writer =
  "decomposition" | { readonly subtask: string; readonly attempt: number } | null;

export interface HistoryEntry {
  readonly revision: number;
  readonly op: "create" | "write" | "rollback";
  readonly version: number;
  readonly writtenBy: Writer;
  readonly node: NodeRecord;
}

export interface NodeHistory {
  readonly nodeId: string;
  readonly baseline: number;
  readonly history: readonly HistoryEntry[];
}

function writer(value: unknown): Writer {
  if (value === null) return null;
  if (value === "decomposition") return "decomposition";
  const by = object(value, "a writer");
  return { subtask: text(by.subtask_id, "a subtask id"), attempt: count(by.attempt, "an attempt") };
}

export function nodeHistory(value: unknown): NodeHistory {
  const answer = object(value, "a node's history");
  return {
    nodeId: text(answer.node_id, "a node id"),
    baseline: count(answer.baseline, "a baseline revision"),
    history: list(answer.history, "a history").map((raw) => {
      const entry = object(raw, "a history entry");
      return {
        revision: count(entry.revision, "a revision"),
        op: oneOf(entry.op, ["create", "write", "rollback"] as const, "a journal op"),
        version: count(entry.version, "a version"),
        writtenBy: writer(entry.written_by),
        node: nodeAt({ revision: entry.revision, node: entry.node }),
      };
    }),
  };
}

export interface Change {
  readonly revision: number;
  readonly nodeId: string;
  readonly version: number;
  readonly op: "create" | "write" | "rollback";
}

export interface GraphDiff {
  readonly from: number;
  readonly to: number;
  readonly changes: readonly Change[];
  readonly nodes: readonly {
    readonly id: string;
    readonly before: NodeRecord | null;
    readonly after: NodeRecord | null;
  }[];
}

export function graphDiff(value: unknown): GraphDiff {
  const answer = object(value, "a diff");
  return {
    from: count(answer.from, "a revision"),
    to: count(answer.to, "a revision"),
    changes: list(answer.changes, "a change list").map((raw) => {
      const change = object(raw, "a change");
      return {
        revision: count(change.revision, "a revision"),
        nodeId: text(change.node_id, "a node id"),
        version: count(change.version, "a version"),
        op: oneOf(change.op, ["create", "write", "rollback"] as const, "a journal op"),
      };
    }),
    nodes: Object.entries(object(answer.nodes, "the changed nodes")).map(([id, raw]) => {
      const sides = object(raw, "a changed node");
      return {
        id,
        before: sides.before === null ? null : nodeAt(sides.before),
        after: sides.after === null ? null : nodeAt(sides.after),
      };
    }),
  };
}
