/**
 * The active run's subtasks, each in one state read from the records: merged (the ledger holds
 * its merge commit), set aside for a decision (the log escalated it to the queue), running (the
 * run's next step is it), or not started (the ledger counts no attempt). A subtask that was
 * attempted and is none of these says so. The counts are a view over the ledger.
 */
import type { RunEvent } from "../../api/events";
import type { LedgerLine } from "../../api/records";
import type { RunStatus } from "../../api/run";

export const STRIP_STATES = ["merged", "set-aside", "running", "tried", "not-started"] as const;
export type StripState = (typeof STRIP_STATES)[number];

export const STRIP_WORDS: Readonly<Record<StripState, string>> = {
  merged: "merged",
  "set-aside": "set aside for a decision",
  running: "running",
  tried: "attempted, not merged",
  "not-started": "not started",
};

export interface StripCell {
  readonly subtask: string;
  readonly state: StripState;
  readonly attempts: number;
}

/** The ledger's latest line per subtask, in the order the subtasks first appear. */
export function latestLines(lines: readonly LedgerLine[]): readonly LedgerLine[] {
  const order: string[] = [];
  const latest = new Map<string, LedgerLine>();
  for (const line of lines) {
    if (!latest.has(line.id)) order.push(line.id);
    latest.set(line.id, line);
  }
  return order.flatMap((id) => {
    const line = latest.get(id);
    return line === undefined ? [] : [line];
  });
}

export function strip(
  lines: readonly LedgerLine[],
  events: readonly RunEvent[],
  status: RunStatus,
): readonly StripCell[] {
  const escalated = new Set(events.flatMap((e) => (e.kind === "escalated" ? [e.subtask] : [])));
  return latestLines(lines).map((line) => {
    const state: StripState =
      line.mergeCommit !== null
        ? "merged"
        : escalated.has(line.id)
          ? "set-aside"
          : status.subtask === line.id
            ? "running"
            : line.attempts === 0
              ? "not-started"
              : "tried";
    return { subtask: line.id, state, attempts: line.attempts };
  });
}

/** How many cells are in each state, every state listed. */
export function stripCounts(cells: readonly StripCell[]): Readonly<Record<StripState, number>> {
  const counts = Object.fromEntries(STRIP_STATES.map((s) => [s, 0])) as Record<StripState, number>;
  for (const cell of cells) counts[cell.state] += 1;
  return counts;
}
