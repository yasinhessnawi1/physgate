/**
 * Where a run stands, as a person needs it said: going, appearing stopped with no end recorded,
 * waiting for a person or for the usage limit, halted, or ended. Read from the status route.
 *
 * "Appears stopped" is an inference, said as one: the run's next step is work, and its log has
 * been silent longer than a living run is after the line it last wrote. The server sends that
 * line's time, its age by the server's own clock (the browser's clock is never read, so a skew
 * between the two changes nothing), and the bound after it: after a session's spawn, the run's
 * session wall clock, where the session is stopped and its end written; after a retry's schedule,
 * its delay. After any other line a stage with no bound of its own may be running (the physics
 * gate, the OS layer's start), so no bound is sent and nothing is claimed. A run with short bounds
 * reads as appearing stopped only past its own bound and ``QUIET_MARGIN_S``. The session clock does
 * not run while the machine sleeps, so after a laptop wakes a session may go on for up to its wall
 * clock: the page may say the run appears stopped until the session's end is written, and says it
 * is going again at its next read of the status.
 */
import type { RunStatus } from "../api/run";
import { type RunEnd, runEndWords } from "../screens/home/runEnd";
import { dayAndMinute } from "./runs";

/**
 * The time past the longest step before a silent log is read as stopped: the stop of a session at
 * its wall clock, its stream read and its end settled. A living run has been seen to write its
 * session's end some six minutes after the wall clock; half an hour leaves room for a slow disk.
 */
export const QUIET_MARGIN_S = 30 * 60;

export type Phase =
  /** The next step is work and the log is not silent past the run's own bound. */
  | "going"
  /** The next step is work, but the log has been silent longer than a living run is after its last line. */
  | "stopped"
  /** The run stopped to wait for a person's decision. */
  | "waiting-person"
  /** Halted on the account's usage limit; a resume after the reset goes on. */
  | "waiting-limit"
  | "halted"
  /** The log ends at an incident whose halt is not written yet. */
  | "halt-owed"
  | "done";

/** What a run that appears stopped is said to be, with the time of its last record. */
export function stoppedWords(lastLineAt: string): string {
  return (
    `No activity since ${dayAndMinute(lastLineAt)}. ` +
    "The run appears to have stopped; nothing has been recorded since."
  );
}
/** What a run waiting on a person's decision is said to be. */
export const WAITING_WORDS = "Waiting for a person's decision; nothing runs until then.";

/** Whether the log has been silent longer than a living run is after its last line. */
export function silentTooLong(status: RunStatus): boolean {
  const silence = status.silentS ?? null;
  const bound = status.silenceBoundS ?? null;
  return silence !== null && bound !== null && silence > bound + QUIET_MARGIN_S;
}

/** Where the run stands, as its status says it. */
export function phaseOf(status: RunStatus): Phase {
  if (status.owedHalt !== null) return "halt-owed";
  if (status.halted !== null || status.kind === "halted")
    return status.halted?.reason === "usage_limit" ? "waiting-limit" : "halted";
  if (status.kind === "done") return "done";
  // A run that records decisions acts on none: its escalated end waits on no one, and has ended.
  if (status.kind === "escalated" && status.acts === false) return "done";
  // The loop returns at these steps: nothing runs until a person decides and the run is resumed.
  if (status.kind === "wait" || status.kind === "escalated") return "waiting-person";
  if (silentTooLong(status)) return "stopped";
  return "going";
}

/** A duration in words: "2 h 18 min"; under a minute in seconds ("20 s"), never "0 min". */
export function durationWords(seconds: number): string {
  if (seconds < 1) return "under a second";
  if (Math.round(seconds) < 60) return `${String(Math.round(seconds))} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${String(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${String(hours)} h ${String(minutes % 60)} min`;
  return `${String(Math.floor(hours / 24))} days`;
}

/** What a person reads of where a run stands: a badge, one short sentence, and the full record. */
export interface Standing {
  readonly phase: Phase;
  /** The badge's word where it is finer than the phase's ("Complete"); ``null`` for the phase's. */
  readonly word: string | null;
  /** One short plain sentence; ``null`` while the run is going. */
  readonly sentence: string | null;
  /** The record's own words in full, shown on demand; ``null`` when the sentence says it all. */
  readonly detail: string | null;
}

/** Each halt reason a run records, as a plain sentence. */
export const HALT_SENTENCES: Readonly<Record<string, string>> = {
  decomposition_failed: "Halted: the brief could not be split into subtasks.",
  incident: "Halted: the harness recorded an incident and stopped the run.",
  infrastructure_exhausted: "Halted: an agent's session would not run, and every retry was used.",
  credential_refused: "Halted: the account's sign-in was refused.",
  os_layer_unavailable: "Halted: the sandbox the agents run in would not start.",
  disk_full: "Halted: the disk was full.",
  role_not_built: "Halted: the run needs an agent role that is not built yet.",
  usage_limit: "Waiting for the usage limit to reset; a resume after it goes on.",
};

/** A module as a person names it: its subtask id without the digest the plan gave it. */
export function moduleName(subtask: string): string {
  return subtask.replace(/-[0-9a-f]{6}$/, "").replace(/-/g, " ");
}

const plural = (n: number, one: string, many = `${one}s`) => `${String(n)} ${n === 1 ? one : many}`;

/** A list of module names in words: "a", "a and b", "a, b and c". */
function namesWords(modules: readonly string[]): string {
  const names = modules.map(moduleName);
  return names.length < 2
    ? names.join("")
    : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1] ?? ""}`;
}

/** How a run that records decisions and ended escalated ended: nothing waits on a person. */
export function recordedEndSentence(owed: readonly string[]): string {
  const base =
    "Ended: this run recorded its decisions and acted on none, so nothing waits for you.";
  if (owed.length === 0) return base;
  const which = owed.length === 1 ? "module still owes" : "modules still owe";
  return `${base} The ${namesWords(owed)} ${which} a person's sign-off.`;
}

/** How an ended run ended, in one short sentence. */
export function endSentence(end: RunEnd): string {
  if (end.kind === "complete") return "Complete: every module is declared complete.";
  if (end.kind === "all-merged")
    return "Ended: every subtask merged and the whole-design gate passed.";
  if (end.recorded !== null) return recordedEndSentence(end.recorded);
  if (end.waiting !== null && end.waiting > 0)
    return `Ended with ${plural(end.waiting, "decision")} still waiting for a person.`;
  if (end.announced !== null && end.announced !== end.planned)
    return "Ended: its log does not list every subtask the plan announced.";
  if (end.withheld !== null)
    return `Ended: the ${moduleName(end.withheld.module)} module was not completed.`;
  if (end.waiting === null && end.setAside > 0)
    return `Ended: ${plural(end.setAside, "subtask")} set aside for a person.`;
  if (end.planned === 0) return "Ended: nothing was planned.";
  if (end.merged < end.planned)
    return `Ended: ${String(end.merged)} of ${plural(end.planned, "subtask")} merged.`;
  if (end.gate === "not-run") return "Ended: the whole design was not gated.";
  if (end.gate === "not-pass") return "Ended: the whole-design gate did not pass.";
  return "Ended.";
}

/**
 * Where ``status``'s run stands, in words; ``end`` is how an ended run ended, read from its log and
 * queue (``runEnd``), or ``null`` when they were not read.
 */
export function standingOf(status: RunStatus, end: RunEnd | null): Standing {
  const phase = phaseOf(status);
  switch (phase) {
    case "going":
      return { phase, word: null, sentence: null, detail: null };
    case "stopped": {
      const silence = status.silentS ?? 0;
      const bound = status.silenceBoundS ?? 0;
      return {
        phase,
        word: null,
        sentence:
          status.lastLineAt == null
            ? "The run appears to have stopped; nothing has been recorded for a long while."
            : stoppedWords(status.lastLineAt),
        detail:
          `The last record was written ${durationWords(silence)} ago, by the server's clock. ` +
          `After a record of that kind, a run that is still going writes its next within ` +
          `${durationWords(bound)}, and half an hour more for the harness's own work; this one ` +
          "has not. This is read from the records alone: no process is looked at.",
      };
    }
    case "waiting-person":
      return { phase, word: null, sentence: WAITING_WORDS, detail: null };
    case "waiting-limit":
    case "halted": {
      const halt = status.halted;
      if (halt === null) return { phase, word: null, sentence: "Halted.", detail: null };
      return {
        phase,
        word: null,
        sentence: HALT_SENTENCES[halt.reason] ?? `Halted: ${halt.reason.replace(/_/g, " ")}.`,
        detail: phase === "waiting-limit" ? null : `${halt.reason}: ${halt.detail}`,
      };
    }
    case "halt-owed":
      return {
        phase,
        word: null,
        sentence: "Halted: the harness recorded an incident; the run stops there.",
        detail: status.owedHalt === null ? null : `Halt owed · ${status.owedHalt.cause}`,
      };
    case "done":
      if (end === null) {
        const sentence =
          status.kind === "escalated" ? recordedEndSentence(status.signOffsOwed ?? []) : "Ended.";
        return { phase, word: null, sentence, detail: null };
      }
      return {
        phase,
        word: end.kind === "complete" ? "Complete" : "Ended",
        sentence: endSentence(end),
        detail: end.kind === "ended" ? runEndWords(end) : null,
      };
  }
}

/** What happens to a decision on a run that is not going, after the run's state. */
export const DECISION_RESUMED =
  "The decision is recorded now and taken up when the run is resumed.";

/**
 * Where the run stands, said beside an open item's decision, or ``null`` while the run is going.
 * A decision is offered in every state: the loop takes a queued decision up at its next boundary,
 * and the end of a run is one, so on a run that is not going a decision is recorded now and taken
 * up when the run is resumed.
 */
export function decisionPendingWords(phase: Phase): string | null {
  const state = RUN_STATE_WORDS[phase];
  return state === null ? null : `${state} ${DECISION_RESUMED}`;
}

const RUN_STATE_WORDS: Readonly<Record<Phase, string | null>> = {
  going: null,
  stopped: "This run appears to have stopped.",
  "waiting-person": "This run is waiting for a person's decision.",
  "waiting-limit": "This run is halted until the usage limit resets.",
  halted: "This run is halted.",
  "halt-owed": "This run is halted.",
  done: "This run has ended.",
};
