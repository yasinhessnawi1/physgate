/**
 * How a run that stopped ended, read from its log and its queue. "Complete" is said only when
 * the log shows every planned subtask merged (as many as the decomposition announced), the
 * whole-design gate ran and its verdict is a pass, and the queue was read and holds no open
 * item. A warn is not a pass here: the harness itself accepts only "pass" (outside observe mode)
 * as clearing the whole-design gate, so the screen does not count a warn as complete either.
 * Anything else is "Ended", with what is left. Counts are a view over the records, never a verdict.
 */
import type { RunEvent } from "../../api/events";

/** What the log says of the whole-design gate. */
export type IntegrationGate = "pass" | "not-pass" | "not-run";

export type RunEnd =
  | { readonly kind: "complete" }
  | {
      readonly kind: "ended";
      /** Open queue items, or ``null`` when the queue could not be read. */
      readonly waiting: number | null;
      readonly merged: number;
      readonly planned: number;
      /** How many subtasks the decomposition announced, or ``null`` when no such line exists. */
      readonly announced: number | null;
      readonly gate: IntegrationGate;
      /** Subtasks the log set aside for a person. */
      readonly setAside: number;
    };

/** ``openItems`` is the queue's open count, or ``null`` when the queue could not be read. */
export function runEnd(events: readonly RunEvent[], openItems: number | null): RunEnd {
  const planned = new Set(events.flatMap((e) => (e.kind === "subtask_planned" ? [e.subtask] : [])));
  const merged = new Set(events.flatMap((e) => (e.kind === "merged" ? [e.subtask] : [])));
  const setAside = new Set(events.flatMap((e) => (e.kind === "escalated" ? [e.subtask] : [])));
  const announced = events.find((e) => e.kind === "decomposed");
  const count = announced?.kind === "decomposed" ? announced.subtasks : null;
  const ran = events.findLast((e) => e.kind === "integration_gate_ran");
  const gate: IntegrationGate =
    ran?.kind !== "integration_gate_ran" ? "not-run" : ran.verdict === "pass" ? "pass" : "not-pass";
  const mergedCount = [...planned].filter((s) => merged.has(s)).length;
  const consistent = count === null || count === planned.size;
  if (
    planned.size > 0 &&
    mergedCount === planned.size &&
    consistent &&
    gate === "pass" &&
    openItems === 0
  )
    return { kind: "complete" };
  return {
    kind: "ended",
    waiting: openItems,
    merged: mergedCount,
    planned: planned.size,
    announced: count,
    gate,
    setAside: setAside.size,
  };
}

/** The words for the run list's "where it stands" column. */
export function runEndWords(end: RunEnd): string {
  if (end.kind === "complete") return "Complete";
  if (end.waiting !== null && end.waiting > 0)
    return `Ended · ${String(end.waiting)} waiting for you`;
  if (end.announced !== null && end.announced !== end.planned)
    return `Ended · log incomplete: ${String(end.planned)} of ${String(end.announced)} subtasks planned`;
  if (end.waiting === null && end.setAside > 0)
    return `Ended · ${String(end.setAside)} set aside for a person`;
  if (end.planned === 0) return "Ended · nothing was planned";
  if (end.merged < end.planned) {
    const base = `${String(end.merged)} of ${String(end.planned)} merged`;
    return `Ended · ${base}${end.setAside > 0 ? ` · ${String(end.setAside)} set aside, decided` : ""}`;
  }
  if (end.gate === "not-run") return "Ended · the whole design was not gated";
  if (end.gate === "not-pass") return "Ended · the whole-design gate did not pass";
  return "Ended · its queue was not read";
}
