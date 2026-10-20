/**
 * How a run that stopped ended, read from its log and its queue. "Complete" is said only when
 * the log shows every planned subtask merged and the whole design gated; anything else is
 * "Ended", with what is left: items waiting for a person, subtasks not merged, or the whole
 * design not gated. Counts are a view over the records, never a verdict.
 */
import type { RunEvent } from "../../api/events";

export type RunEnd =
  | { readonly kind: "complete" }
  | {
      readonly kind: "ended";
      /** Open queue items, or the subtasks the log set aside when the queue was not read. */
      readonly waiting: number | null;
      readonly merged: number;
      readonly planned: number;
      readonly gated: boolean;
      readonly setAside?: number;
    };

/** ``openItems`` is the queue's open count, or ``null`` when the queue could not be read. */
export function runEnd(events: readonly RunEvent[], openItems: number | null): RunEnd {
  const planned = new Set(events.flatMap((e) => (e.kind === "subtask_planned" ? [e.subtask] : [])));
  const merged = new Set(events.flatMap((e) => (e.kind === "merged" ? [e.subtask] : [])));
  const gated = events.some((e) => e.kind === "integration_gate_ran");
  const allMerged = planned.size > 0 && [...planned].every((s) => merged.has(s));
  if (allMerged && gated) return { kind: "complete" };
  const setAside = new Set(events.flatMap((e) => (e.kind === "escalated" ? [e.subtask] : [])));
  return {
    kind: "ended",
    waiting: openItems,
    merged: [...planned].filter((s) => merged.has(s)).length,
    planned: planned.size,
    gated,
    ...(openItems === null ? { setAside: setAside.size } : {}),
  };
}

/** The words for the run list's "where it stands" column. */
export function runEndWords(end: RunEnd): string {
  if (end.kind === "complete") return "Complete";
  if (end.waiting !== null && end.waiting > 0)
    return `Ended · ${String(end.waiting)} waiting for you`;
  if (end.setAside !== undefined && end.setAside > 0)
    return `Ended · ${String(end.setAside)} set aside for a person`;
  if (end.planned === 0) return "Ended · nothing was planned";
  if (end.merged < end.planned)
    return `Ended · ${String(end.merged)} of ${String(end.planned)} ${end.planned === 1 ? "subtask" : "subtasks"} merged`;
  return "Ended · the whole design was not gated";
}
