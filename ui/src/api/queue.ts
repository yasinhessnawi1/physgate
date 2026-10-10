/**
 * The approval queue as the server sends it, and the one request the app sends that acts.
 *
 * The listing is ``physgate queue list``'s own record: the open items and every decision with
 * its mark. An item view is one item as a person is shown it, with its line's digest and each
 * trajectory held to its seal; a decision sends both back, and the server checks them again.
 * Each guard checks the fields the view shows; a record of another shape is refused whole.
 */
import { requireQuantity } from "../design/quantity";
import type { Quantity } from "../design/quantity";
import { count, flag, list, object, oneOf, optionalText, text } from "./check";
import { ShapeError } from "./client";

export const SOURCES = [
  "gate_escalation",
  "repair_budget_exhausted",
  "review_unavailable",
  "review_blocked",
  "arbitration",
] as const;
export type QueueSource = (typeof SOURCES)[number];

export interface CitedQuantity {
  readonly nodeId: string;
  readonly name: string;
  readonly q: Quantity;
}

export interface QueueItem {
  readonly itemId: string;
  readonly ts: string;
  readonly runId: string;
  readonly subtaskId: string;
  readonly source: QueueSource;
  readonly decisionRequired: string;
  readonly artefactDiff: string;
  readonly triggeringFinding: string;
  readonly quantities: readonly CitedQuantity[];
  readonly trajectories: readonly string[];
}

export function queueItem(value: unknown): QueueItem {
  const item = object(value, "a queue item");
  return {
    itemId: text(item.item_id, "an item id"),
    ts: text(item.ts, "a time"),
    runId: text(item.run_id, "a run id"),
    subtaskId: text(item.subtask_id, "a subtask id"),
    source: oneOf(item.source, SOURCES, "a queue source"),
    decisionRequired: text(item.decision_required, "the decision required"),
    artefactDiff: text(item.artefact_diff, "an artefact diff"),
    triggeringFinding: text(item.triggering_finding, "a triggering finding"),
    quantities: list(item.quantities, "the quantities").map((raw) => {
      const cited = object(raw, "a cited quantity");
      return {
        nodeId: text(cited.node_id, "a node id"),
        name: text(cited.name, "a quantity's name"),
        q: requireQuantity({ value: cited.value, unit: cited.unit }),
      };
    }),
    trajectories: list(item.trajectories, "the trajectories").map((raw) =>
      text(raw, "a trajectory link"),
    ),
  };
}

export interface Decided {
  readonly itemId: string;
  readonly ts: string;
  readonly decision: string;
  readonly resolvedBy: string;
  /** The queue's own mark for a decision written while a session ran, word for word. */
  readonly flag: string | null;
}

function decided(value: unknown): Decided {
  const d = object(value, "a decision");
  return {
    itemId: text(d.item_id, "an item id"),
    ts: text(d.ts, "a time"),
    decision: text(d.decision, "a decision"),
    resolvedBy: text(d.resolved_by, "who decided"),
    flag: optionalText(d.flag, "a decision's mark"),
  };
}

export interface QueueListing {
  readonly open: readonly QueueItem[];
  readonly decided: readonly Decided[];
}

export function queueListing(value: unknown): QueueListing {
  const listing = object(value, "a queue listing");
  return {
    open: list(listing.open, "the open items").map(queueItem),
    decided: list(listing.decided, "the decisions").map(decided),
  };
}

export const STATUSES = [
  "holds",
  "tampered",
  "missing",
  "no_seal",
  "not_in_this_run",
  "too_large",
] as const;
export type TrajectoryStatus = (typeof STATUSES)[number];

export interface TrajectoryView {
  readonly link: string;
  readonly sessionId: string | null;
  readonly status: TrajectoryStatus;
}

export interface ItemView {
  readonly position: number;
  readonly item: QueueItem;
  readonly itemSha256: string;
  readonly open: boolean;
  readonly trajectories: readonly TrajectoryView[];
}

const DIGEST = /^[0-9a-f]{64}$/;

export function itemView(value: unknown): ItemView {
  const view = object(value, "an item view");
  const digest = text(view.item_sha256, "an item digest");
  if (!DIGEST.test(digest)) throw new ShapeError("an item digest");
  return {
    position: count(view.position, "an item position"),
    item: queueItem(view.item),
    itemSha256: digest,
    open: flag(view.open, "whether the item is open"),
    trajectories: list(view.trajectories, "the trajectories").map((raw) => {
      const t = object(raw, "a trajectory");
      return {
        link: text(t.link, "a trajectory link"),
        sessionId: optionalText(t.session_id, "a session id"),
        status: oneOf(t.status, STATUSES, "a seal status"),
      };
    }),
  };
}

export function operatorName(value: unknown): string | null {
  return optionalText(object(value, "the operator").operator, "the operator's name");
}

export type Verb = "approve" | "reject";

/**
 * The decision as recorded, exactly as the queue's own ``decision_text`` makes it: the verb, and
 * the note after a colon when there is one. ``null`` for a rejection without a note, which the
 * server refuses too.
 */
export function decisionText(verb: Verb, note: string): string | null {
  if (note.trim() === "") return verb === "reject" ? null : verb;
  return `${verb}: ${note}`;
}

export interface Resolved {
  readonly itemId: string;
  readonly ts: string;
  readonly decision: string;
  readonly resolvedBy: string;
}

export function resolved(value: unknown): Resolved {
  const r = object(object(value, "a recorded decision").resolved, "a recorded decision");
  return {
    itemId: text(r.item_id, "an item id"),
    ts: text(r.ts, "a time"),
    decision: text(r.decision, "a decision"),
    resolvedBy: text(r.resolved_by, "who decided"),
  };
}

/** The body of a decision request: the item, the verb and note, and what the page showed. */
export function decisionRequest(view: ItemView, verb: Verb, note: string): string {
  return JSON.stringify({
    item_id: view.item.itemId,
    verb,
    note,
    shown: {
      item_sha256: view.itemSha256,
      trajectories: view.trajectories.map((t) => t.status),
    },
  });
}
