/**
 * How a run that stopped ended, read from its log, its queue and the completions the server
 * reads from the record. Completion is a declaration (ARCH-051), so "Complete" is said only of a
 * run that plans a subtask declaring it: when every module but sizing's has its completion line
 * and the queue was read and holds no open item a decision can act on. An item a reopen
 * superseded is not one: nothing waits on it, and a decision on it is recorded only. A run
 * without one never reads "Complete": with every planned subtask merged (as many as the
 * decomposition announced), the whole-design gate's verdict a pass and nothing open, it reads
 * "All merged · gate passed". A warn is not a pass here:
 * the harness itself accepts only "pass" (outside observe mode) as clearing the whole-design gate.
 * Anything else is "Ended", with what is left, and a module's completion withheld is named with
 * the server's own reasons. A run that records decisions only and ended escalated waits on no
 * one, whatever its queue holds: no decision acts there, and the sign-offs owed are named instead.
 * A run that acts and ended escalated owing a sign-off whose latest item was decided (a reject)
 * waits on no one for it either: nothing left in the run can sign it, and it is named so.
 * Counts are a view over the records, never a verdict.
 */
import type { RunEvent } from "../../api/events";
import type { QueueItem } from "../../api/queue";
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
      /**
       * In a run that records decisions and ended escalated, the modules whose sign-off is owed:
       * no decision acts there, so nothing waits for a person. ``null`` for any other run.
       */
      readonly recorded: readonly string[] | null;
      /**
       * In a run that acts and ended escalated, the modules whose sign-off is owed with nothing
       * left in the run that can sign it: each one's latest item was decided. ``null`` otherwise.
       */
      readonly unsigned: readonly string[] | null;
    };

/** A module not complete with nothing open: why, by the state the server read. */
const STATE_WORDS: Readonly<Record<ModuleCompletion["state"], string>> = {
  complete: "complete",
  sign_off_owed: "a person's sign-off is owed",
  not_declared: "integration did not declare it complete",
  owed: "its completion line is owed",
  withheld: "withheld",
};

/**
 * How many of the queue's open items wait for a person, or ``null`` when the queue could not be
 * read: every one but those a reopen superseded.
 */
export function waitingFor(
  open: readonly QueueItem[] | null,
  superseded: RunStatus["superseded"],
): number | null {
  return open === null ? null : open.filter((i) => !Object.hasOwn(superseded, i.itemId)).length;
}

/**
 * The modules whose sign-off is owed where the run records decisions only and ended escalated,
 * or ``null`` for any other run: there a person's decision acts, or the run has not ended so.
 */
export function recordedEnd(status: RunStatus): readonly string[] | null {
  return status.kind === "escalated" && status.acts === false ? (status.signOffsOwed ?? []) : null;
}

/**
 * The modules whose sign-off is owed with nothing left to sign it, where the run acts and ended
 * escalated and none of them has an item open to a decision; ``null`` for any other run, and
 * where the server did not say which are open.
 */
export function unsignedEnd(status: RunStatus): readonly string[] | null {
  const owed = status.signOffsOwed ?? [];
  const open = status.signOffsOpenToDecide;
  if (status.kind !== "escalated" || status.acts !== true || open === undefined) return null;
  return owed.length > 0 && owed.every((m) => !open.includes(m)) ? owed : null;
}

/**
 * ``openItems`` is what waits for a person (``waitingFor``), or ``null`` when the queue could not be
 * read; ``recorded``, what ``recordedEnd`` gives; ``unsigned``, what ``unsignedEnd`` gives.
 */
export function runEnd(
  events: readonly RunEvent[],
  openItems: number | null,
  completion: RunStatus["completion"],
  recorded: readonly string[] | null = null,
  unsigned: readonly string[] | null = null,
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
    recorded,
    unsigned,
  };
}

/** The words for the run list's "where it stands" column. */
export function runEndWords(end: RunEnd): string {
  if (end.kind === "complete") return "Complete";
  if (end.kind === "all-merged") return "All merged · gate passed";
  if (end.recorded !== null)
    return end.recorded.length === 0
      ? "Ended · decisions recorded, none acted on"
      : `Ended · decisions recorded, none acted on · sign-off owed: ${end.recorded.join(", ")}`;
  if (end.waiting !== null && end.waiting > 0)
    return `Ended · ${String(end.waiting)} waiting for you`;
  if (end.unsigned !== null) return `Ended · sign-off not given: ${end.unsigned.join(", ")}`;
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
