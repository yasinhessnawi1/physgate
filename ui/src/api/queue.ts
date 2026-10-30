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
import { count, flag, list, object, oneOf, optionalCount, optionalText, text } from "./check";
import { ShapeError } from "./client";

export const SOURCES = [
  "gate_escalation",
  "repair_budget_exhausted",
  "review_unavailable",
  "review_blocked",
  "arbitration",
  "escalation_decision",
  "contract",
] as const;
export type QueueSource = (typeof SOURCES)[number];

export const ON_APPROVE = ["merge_attempt", "record_only"] as const;
export const ON_REJECT = ["retry", "fix", "end_subtask", "record_only"] as const;
export const WHY_RECORD_ONLY = [
  "gate",
  "change_check",
  "reading",
  "indicator_in_history",
  "scan_hit",
  "source",
  "legacy",
] as const;
/** The positions an arbitration item offers, in the order it states them. */
export const POSITIONS = ["sizing", "domain"] as const;
/** The positions a failed contract's item offers, in the order it states them: whose merged work stands. */
export const CONTRACT_POSITIONS = ["producer", "consumer"] as const;
/**
 * What choosing a position does: order the next attempt to the graph's value, order the one fix to
 * it, end the subtask, resize (the subtask waits for sizing's closing pass to write the domain's
 * value), or record the decision only.
 */
export const ON_CHOOSE = [
  "retry",
  "fix",
  "end_subtask",
  "resize",
  "reopen",
  "record_only",
] as const;
export type Position = (typeof POSITIONS)[number] | (typeof CONTRACT_POSITIONS)[number];
export type OnChoose = (typeof ON_CHOOSE)[number];
export type OnApprove = (typeof ON_APPROVE)[number];
export type OnReject = (typeof ON_REJECT)[number];
export type WhyRecordOnly = (typeof WHY_RECORD_ONLY)[number];

/**
 * What each verb will do to an item, as the run that listed it computed it from its record.
 * Only a run that acts on decisions writes it; an item without one is decided and recorded, and
 * nothing in the run acts on it.
 */
export interface Consequence {
  readonly attempt: number | null;
  readonly attemptCommit: string | null;
  readonly onApprove: OnApprove;
  readonly onReject: OnReject;
  readonly whyRecordOnly: WhyRecordOnly | null;
  /** Every reward-hacking indicator a review of the subtask confirmed: which attempt, which kind. */
  readonly confirmedIndicators: readonly { readonly attempt: number; readonly kind: string }[];
  /** How many hits the scan before review found, for an item whose review never judged them. */
  readonly scanHits: number;
  /** What choosing each position does, on an item that offers positions; ``null`` otherwise. */
  readonly onChoose: Readonly<Partial<Record<Position, OnChoose>>> | null;
}

/** The positions each kind of item offers; no other kind offers any. */
const OFFERED: Readonly<Partial<Record<QueueSource, readonly Position[]>>> = {
  arbitration: POSITIONS,
  contract: CONTRACT_POSITIONS,
};

/**
 * The positions an item states, held to its kind's set in its order: any other shape is refused.
 * As the queue's own model holds it: only an arbitration or a failed contract's item states them,
 * and one that says what its verbs do must say what choosing each position does.
 */
function onChoose(
  value: unknown,
  source: QueueSource,
): Readonly<Partial<Record<Position, OnChoose>>> | null {
  const offered = OFFERED[source];
  if (value === undefined || value === null) {
    if (offered !== undefined) throw new ShapeError(`a ${source} item's positions`);
    return null;
  }
  if (offered === undefined) throw new ShapeError("positions on an item of another kind");
  const stated = object(value, "what choosing each position does");
  if (Object.keys(stated).join() !== offered.join()) throw new ShapeError("an item's positions");
  return Object.fromEntries(
    offered.map((p) => [p, oneOf(stated[p], ON_CHOOSE, `what choosing ${p} does`)]),
  );
}

function consequence(value: unknown, source: QueueSource): Consequence | null {
  if (value === undefined || value === null) return null;
  const c = object(value, "an item's consequence");
  const commit = optionalText(c.attempt_commit, "an attempt's commit");
  if (commit !== null && !/^[0-9a-f]{40}$/.test(commit))
    throw new ShapeError("an attempt's commit");
  return {
    attempt: optionalCount(c.attempt, "the attempt an item concerns"),
    attemptCommit: commit,
    onApprove: oneOf(c.on_approve, ON_APPROVE, "what approve does"),
    onReject: oneOf(c.on_reject, ON_REJECT, "what reject does"),
    whyRecordOnly:
      c.why_record_only === null || c.why_record_only === undefined
        ? null
        : oneOf(c.why_record_only, WHY_RECORD_ONLY, "why approve records only"),
    confirmedIndicators: list(c.confirmed_indicators, "the confirmed indicators").map((raw) => {
      const i = object(raw, "a confirmed indicator");
      return {
        attempt: count(i.attempt, "an indicator's attempt"),
        kind: text(i.kind, "an indicator's kind"),
      };
    }),
    scanHits: list(c.scan_hits, "the scan's hits").length,
    onChoose: onChoose(c.on_choose, source),
  };
}

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
  /** What each verb will do; ``null`` on an item no run that acts on decisions listed. */
  readonly consequence: Consequence | null;
}

export function queueItem(value: unknown): QueueItem {
  const item = object(value, "a queue item");
  const source = oneOf(item.source, SOURCES, "a queue source");
  return {
    itemId: text(item.item_id, "an item id"),
    ts: text(item.ts, "a time"),
    runId: text(item.run_id, "a run id"),
    subtaskId: text(item.subtask_id, "a subtask id"),
    source,
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
    consequence: consequence(item.consequence, source),
  };
}

export const EFFECTS = ["merge", "retry", "fix", "end_subtask", "resize", "none"] as const;
export type Effect = (typeof EFFECTS)[number];

/** What the run did with a decision, from its own record; absent until it takes it. */
export interface Taken {
  readonly effect: Effect;
  readonly acts: boolean;
  /** Why it did not act, in the record's own words. */
  readonly whyNot: string | null;
  /** The operator who confirmed a held decision on the command line, if one did. */
  readonly confirmedBy: string | null;
  /** A reject that ended the subtask in place of the session it would order, because that
   * session's reviewer could not have read what it would be told whole. */
  readonly orderTooLong: boolean;
}

export interface Decided {
  readonly itemId: string;
  readonly ts: string;
  readonly decision: string;
  readonly resolvedBy: string;
  /** The queue's own mark for a decision written while a session ran, word for word. */
  readonly flag: string | null;
  readonly taken: Taken | null;
}

function taken(value: unknown): Taken | null {
  if (value === undefined || value === null) return null;
  const t = object(value, "what the run did with a decision");
  return {
    effect: oneOf(t.effect, EFFECTS, "a decision's effect"),
    acts: flag(t.acts, "whether a decision acted"),
    whyNot: optionalText(t.why_not, "why a decision did not act"),
    confirmedBy: optionalText(t.confirmed_by, "who confirmed a decision"),
    orderTooLong: flag(t.order_too_long, "whether a reject's order was too long to review"),
  };
}

function decided(value: unknown): Decided {
  const d = object(value, "a decision");
  return {
    itemId: text(d.item_id, "an item id"),
    ts: text(d.ts, "a time"),
    decision: text(d.decision, "a decision"),
    resolvedBy: text(d.resolved_by, "who decided"),
    flag: optionalText(d.flag, "a decision's mark"),
    taken: taken(d.taken),
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

export type Verb = "approve" | "reject" | "choose";

/**
 * The characters Python's ``str.strip()`` removes (those for which ``str.isspace()`` is true),
 * as code points. A note made only of these is blank to the server, so it is blank here, and
 * nothing else is: JavaScript's ``trim`` would also strip U+FEFF and keep U+001C–U+001F and U+0085,
 * and the confirmation would then show a different decision from the one written. A Python test
 * holds this list to the interpreter's own set.
 */
export const PYTHON_WHITESPACE: ReadonlySet<number> = new Set([
  0x0009, 0x000a, 0x000b, 0x000c, 0x000d, 0x001c, 0x001d, 0x001e, 0x001f, 0x0020, 0x0085, 0x00a0,
  0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a,
  0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
]);

/** Whether ``note`` is blank as the server judges it: nothing but Python's whitespace. */
export function isBlank(note: string): boolean {
  for (const char of note) {
    if (!PYTHON_WHITESPACE.has(char.codePointAt(0) ?? -1)) return false;
  }
  return true;
}

/**
 * The decision as recorded, exactly as the queue's own ``decision_text`` makes it: the verb, the
 * position a choice names, and the note after a colon when there is one. ``null`` for a rejection
 * without a note or a choice without a position, which the server refuses too.
 */
export function decisionText(verb: Verb, note: string, position?: Position): string | null {
  if ((verb === "choose") !== (position !== undefined)) return null;
  const said = position === undefined ? verb : `${verb} ${position}`;
  if (isBlank(note)) return verb === "reject" ? null : said;
  return `${said}: ${note}`;
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

/** The body of a decision request: the item, the verb, its position and note, and what was shown. */
export function decisionRequest(
  view: ItemView,
  verb: Verb,
  note: string,
  position?: Position,
): string {
  return JSON.stringify({
    item_id: view.item.itemId,
    verb,
    ...(position === undefined ? {} : { position }),
    note,
    shown: {
      item_sha256: view.itemSha256,
      trajectories: view.trajectories.map((t) => t.status),
    },
  });
}
