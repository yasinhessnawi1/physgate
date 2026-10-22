/**
 * The task ledger folded to one row per subtask, in the order the run planned them. The ledger
 * writes a new line at every step of every attempt, so one subtask has many lines; a row reads
 * the latest line for what the subtask stands at, and keeps every line, in the order written, as
 * its history.
 *
 * Every field is read from a record: the ledger's latest line, the event log (planning,
 * rejections, reviews with no verdict, escalations), the queue's listing and where the run
 * stands. Nothing is inferred past them. A stage the latest attempt has not recorded reads "not
 * run" only when the attempt is over; while the run is on that attempt it reads "not yet".
 */
import type { RunEvent } from "../../api/events";
import type { QueueListing } from "../../api/queue";
import type { LedgerLine } from "../../api/records";
import type { RunStatus } from "../../api/run";
import type { Verdict } from "../../design/components/verdict/verdict";

/** What the latest attempt recorded for one stage, the gate or the review. */
export type StageResult =
  /** The verdict the ledger recorded, or the stage skipped. */
  | { readonly kind: "recorded"; readonly result: Verdict | "skipped" }
  /** The review ran and reached no verdict: never a pass or a fail. */
  | { readonly kind: "no-verdict"; readonly cause: string }
  /** The run is on this attempt and the stage has not recorded yet. */
  | { readonly kind: "not-yet" }
  /** The attempt is over and the stage recorded nothing. */
  | { readonly kind: "not-run" }
  /** The subtask has had no attempt. */
  | { readonly kind: "no-attempt" };

/** Where a subtask stands, from its latest record. */
export type SubtaskState =
  | { readonly kind: "merged"; readonly commit: string }
  /** Escalated, and its queue item is open. */
  | { readonly kind: "waiting"; readonly itemId: string }
  /** Escalated, and a person decided its queue item. */
  | {
      readonly kind: "decided";
      readonly itemId: string;
      readonly decision: string;
      readonly by: string;
    }
  /** Escalated; the queue was not read, or does not list the item. */
  | { readonly kind: "sent"; readonly itemId: string }
  /** An attempt was rejected and the run's next step is this subtask's next attempt. */
  | { readonly kind: "repairing"; readonly rejected: number; readonly attempt: number }
  /** The run's next step is this subtask, with no rejection before it. */
  | { readonly kind: "in-progress"; readonly attempt: number }
  /** The latest attempt was rejected and the run is not on this subtask. */
  | { readonly kind: "rejected"; readonly attempt: number }
  | { readonly kind: "not-started" }
  /** Attempted, not merged, and none of the above recorded. */
  | { readonly kind: "attempted"; readonly attempt: number };

/** One ledger line as written, with its place in the whole ledger. */
export interface HistoryLine {
  /** 1-based, counted over the whole ledger. */
  readonly position: number;
  readonly line: LedgerLine;
}

export interface SubtaskRow {
  readonly id: string;
  readonly role: string;
  /** 1-based, in the order the run planned the subtasks. */
  readonly position: number;
  readonly of: number;
  readonly state: SubtaskState;
  /** The attempts the latest line counts. */
  readonly attempts: number;
  /** The attempts a subtask gets, as the server sent it; ``null`` when it sent none. */
  readonly budget: number | null;
  /** The latest attempt's gate and review. */
  readonly gate: StageResult;
  readonly review: StageResult;
  readonly mergeCommit: string | null;
  readonly history: readonly HistoryLine[];
}

export interface FoldContext {
  readonly events: readonly RunEvent[];
  /** Where the run stands, or ``null`` when it was not read. */
  readonly status: RunStatus | null;
  /** The approval queue's listing, or ``null`` when it was not read. */
  readonly queue: QueueListing | null;
  readonly budget: number | null;
}

/** The subtask ids in plan order: as planned, then any the ledger names that the log did not. */
function planOrder(lines: readonly LedgerLine[], events: readonly RunEvent[]): readonly string[] {
  const order: string[] = [];
  for (const e of events)
    if (e.kind === "subtask_planned" && !order.includes(e.subtask)) order.push(e.subtask);
  for (const line of lines) if (!order.includes(line.id)) order.push(line.id);
  return order;
}

function rejectedAt(events: readonly RunEvent[], id: string, attempt: number): boolean {
  return events.some(
    (e) => e.kind === "attempt_rejected" && e.subtask === id && e.attempt === attempt,
  );
}

function stateOf(
  id: string,
  latest: LedgerLine,
  { events, status, queue }: FoldContext,
): SubtaskState {
  if (latest.mergeCommit !== null) return { kind: "merged", commit: latest.mergeCommit };
  const escalation = events.findLast((e) => e.kind === "escalated" && e.subtask === id);
  if (escalation?.kind === "escalated") {
    const itemId = escalation.itemId;
    if (queue?.open.some((item) => item.itemId === itemId) === true)
      return { kind: "waiting", itemId };
    const decided = queue?.decided.findLast((d) => d.itemId === itemId);
    if (decided !== undefined)
      return { kind: "decided", itemId, decision: decided.decision, by: decided.resolvedBy };
    return { kind: "sent", itemId };
  }
  const k = latest.attempts;
  const current = status !== null && status.halted === null && status.subtask === id;
  if (current && status.kind === "attempt") {
    if (k > 0 && rejectedAt(events, id, k))
      return { kind: "repairing", rejected: k, attempt: k + 1 };
    if (k > 1 && rejectedAt(events, id, k - 1))
      return { kind: "repairing", rejected: k - 1, attempt: k };
    return { kind: "in-progress", attempt: Math.max(k, 1) };
  }
  if (k > 0 && rejectedAt(events, id, k)) return { kind: "rejected", attempt: k };
  if (current) return { kind: "in-progress", attempt: Math.max(k, 1) };
  if (k === 0) return { kind: "not-started" };
  return { kind: "attempted", attempt: k };
}

/** Whether the run is still on the latest attempt, so a stage it lacks may yet record. */
function onLatestAttempt(state: SubtaskState, attempts: number): boolean {
  return (state.kind === "in-progress" || state.kind === "repairing") && state.attempt === attempts;
}

function stageOf(
  recorded: Verdict | "skipped" | null,
  attempts: number,
  open: boolean,
  noVerdict: string | null,
): StageResult {
  if (attempts === 0) return { kind: "no-attempt" };
  if (recorded !== null) return { kind: "recorded", result: recorded };
  if (noVerdict !== null) return { kind: "no-verdict", cause: noVerdict };
  return open ? { kind: "not-yet" } : { kind: "not-run" };
}

/** The ledger as one row per subtask, in plan order, each with its whole history. */
export function foldLedger(
  lines: readonly LedgerLine[],
  context: FoldContext,
): readonly SubtaskRow[] {
  const order = planOrder(lines, context.events);
  const histories = new Map<string, HistoryLine[]>();
  lines.forEach((line, i) => {
    const mine = histories.get(line.id) ?? [];
    mine.push({ position: i + 1, line });
    histories.set(line.id, mine);
  });
  return order.flatMap((id, i) => {
    const history = histories.get(id) ?? [];
    const latest = history.at(-1)?.line;
    if (latest === undefined) return [];
    const state = stateOf(id, latest, context);
    const k = latest.attempts;
    const open = onLatestAttempt(state, k);
    const unavailable = context.events.findLast(
      (e) => e.kind === "review_unavailable" && e.subtask === id && e.attempt === k,
    );
    return [
      {
        id,
        role: latest.role,
        position: i + 1,
        of: order.length,
        state,
        attempts: k,
        budget: context.budget,
        gate: stageOf(latest.gate, k, open, null),
        review: stageOf(
          latest.review,
          k,
          open,
          unavailable?.kind === "review_unavailable" ? unavailable.cause : null,
        ),
        mergeCommit: latest.mergeCommit,
        history,
      },
    ];
  });
}

function capital(text: string): string {
  return `${(text[0] ?? "").toUpperCase()}${text.slice(1)}`;
}

/** A subtask's name as a person reads it: the module its role builds, from the plan. */
export function subtaskLabel(row: Pick<SubtaskRow, "role">): string {
  return `${capital(row.role.replaceAll("_", " "))} module`;
}

/**
 * "2 of 3" where the server sent the budget, otherwise the count alone. An attempt past the
 * budget is the one fix a person ordered after a review that blocked, which is outside it.
 */
export function attemptsWords(row: Pick<SubtaskRow, "attempts" | "budget">): string {
  if (row.budget === null) return String(row.attempts);
  if (row.attempts > row.budget)
    return `${String(row.budget)} of ${String(row.budget)}, then the one fix a person ordered`;
  return `${String(row.attempts)} of ${String(row.budget)}`;
}

const DECISION_WORDS: Readonly<Record<string, string>> = {
  approve: "approved",
  reject: "rejected",
};

/** Where a subtask stands, as a sentence no stronger than the record it is read from. */
export function stateWords(state: SubtaskState): string {
  switch (state.kind) {
    case "merged":
      return "Merged";
    case "waiting":
      return "Escalated: waiting for a person's decision";
    case "decided":
      return `Decided by ${state.by}: ${DECISION_WORDS[state.decision] ?? state.decision}. Not merged.`;
    case "sent":
      return "Escalated: sent to a person to decide";
    case "repairing":
      return `Rejected at attempt ${String(state.rejected)}; repairing in attempt ${String(state.attempt)}`;
    case "in-progress":
      return `In progress: attempt ${String(state.attempt)}`;
    case "rejected":
      return `Rejected at attempt ${String(state.attempt)}. Not merged.`;
    case "not-started":
      return "Not started";
    case "attempted":
      return `Not merged after attempt ${String(state.attempt)}`;
  }
}
