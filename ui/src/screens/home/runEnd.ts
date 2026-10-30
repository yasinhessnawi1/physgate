/**
 * How a run that stopped ended, read from its log, its queue and the completions the server
 * reads from the record. Completion is a declaration (ARCH-051), so "Complete" is said only of a
 * run that plans a subtask declaring it: when every module but sizing's has its completion line
 * and the queue was read and holds no open item. A run without one never reads "Complete": with
 * every planned subtask merged (as many as the decomposition announced), the whole-design gate's
 * verdict a pass and nothing open, it reads "All merged · gate passed". A warn is not a pass here:
 * the harness itself accepts only "pass" (outside observe mode) as clearing the whole-design gate.
 * Anything else is "Ended", with what is left, and a module's completion withheld is named with
 * the server's own reasons. Counts are a view over the records, never a verdict.
 */
import type { RunEvent } from "../../api/events";
import type { ModuleCompletion, RunStatus } from "../../api/run";

/** What the log says of the whole-design gate. */
export type IntegrationGate = "pass" | "not-pass" | "not-run";

export type RunEnd =
  | { readonly kind: "complete" }
  | { readonly kind: "all-merged" }
  | {
      readonly kind: "ended";
      /** The first module, sizing's aside, not complete: the open reasons, or its state's words. */
      readonly withheld: { readonly module: string; readonly reasons: readonly string[] } | null;
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

/** A module not complete with nothing open: why, by the state the server read. */
const STATE_WORDS: Readonly<Record<ModuleCompletion["state"], string>> = {
  complete: "complete",
  not_declared: "integration did not declare it complete",
  owed: "its completion line is owed",
  withheld: "withheld",
};

/** ``openItems`` is the queue's open count, or ``null`` when the queue could not be read. */
export function runEnd(
  events: readonly RunEvent[],
  openItems: number | null,
  completion: RunStatus["completion"],
): RunEnd {
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
  const counted = completion.modules.filter((m) => !m.sizing);
  if (completion.owner) {
    if (counted.length > 0 && counted.every((m) => m.state === "complete") && openItems === 0)
      return { kind: "complete" };
  } else if (
    planned.size > 0 &&
    mergedCount === planned.size &&
    consistent &&
    gate === "pass" &&
    openItems === 0
  )
    return { kind: "all-merged" };
  const held = completion.owner ? counted.find((m) => m.state !== "complete") : undefined;
  return {
    kind: "ended",
    withheld:
      held === undefined
        ? null
        : {
            module: held.subtask,
            reasons:
              held.open.length > 0 ? held.open.map((o) => o.reason) : [STATE_WORDS[held.state]],
          },
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
  if (end.kind === "all-merged") return "All merged · gate passed";
  if (end.waiting !== null && end.waiting > 0)
    return `Ended · ${String(end.waiting)} waiting for you`;
  if (end.announced !== null && end.announced !== end.planned)
    return `Ended · log incomplete: ${String(end.planned)} of ${String(end.announced)} subtasks planned`;
  if (end.withheld !== null)
    return `Ended · ${end.withheld.module} not complete: ${end.withheld.reasons.join("; ")}`;
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
