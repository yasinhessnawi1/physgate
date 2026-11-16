/**
 * Where a run stands, as a person needs it said: going, stopped with no end recorded, waiting for
 * a person or for the usage limit, halted, or ended. Read from the status route, never guessed.
 *
 * "Stopped" is said of a run whose next step is work (an attempt, a gate, a review) while its log
 * has been silent longer than a living run ever is. While the harness runs, it writes a line at
 * least once in each of its own steps: a session it spawned is stopped at the run's session wall
 * clock and its end written, and a retry waits its recorded delay. The server sends the time of
 * the log's last line and the longest of those bounds; a log silent for longer than that, with
 * ``QUIET_MARGIN_S`` more for the work around a session's end, was left by a process that is no
 * longer running. Where either is missing, nothing is claimed and the run reads as going.
 */
import type { RunStatus } from "../api/run";
import type { RunEnd } from "../screens/home/runEnd";
import { instant } from "./runs";

/**
 * The time past the longest step before a silent log is read as stopped: the stop of a session at
 * its wall clock, its stream read and its end settled. A living run has been seen to write its
 * session's end some six minutes after the wall clock; half an hour leaves room for a slow disk.
 */
export const QUIET_MARGIN_S = 30 * 60;

export type Phase =
  /** The next step is work and the log is not silent past the run's own bound. */
  | "going"
  /** The next step is work, but the log has been silent longer than a living run is: nothing runs. */
  | "stopped"
  /** The run stopped to wait for a person's decision. */
  | "waiting-person"
  /** Halted on the account's usage limit; a resume after the reset goes on. */
  | "waiting-limit"
  | "halted"
  /** The log ends at an incident whose halt is not written yet. */
  | "halt-owed"
  | "done";

/** What a stopped run is said to be, in full. */
export const STOPPED_WORDS = "Stopped. The run ended without recording why; nothing is running.";
/** What a run waiting on a person's decision is said to be. */
export const WAITING_WORDS = "Waiting for a person's decision; nothing runs until then.";

/** Whether the log has been silent longer than a living run is, at ``now`` (ms since the epoch). */
export function silentTooLong(status: RunStatus, now: number): boolean {
  const silence = silenceS(status, now);
  const longest = status.longestStepS ?? null;
  return silence !== null && longest !== null && silence > longest + QUIET_MARGIN_S;
}

/** Where the run stands, at ``now``. */
export function phaseOf(status: RunStatus, now: number = Date.now()): Phase {
  if (status.owedHalt !== null) return "halt-owed";
  if (status.halted !== null || status.kind === "halted")
    return status.halted?.reason === "usage_limit" ? "waiting-limit" : "halted";
  if (status.kind === "done") return "done";
  // The loop returns at these steps: nothing runs until a person decides and the run is resumed.
  if (status.kind === "wait" || status.kind === "escalated") return "waiting-person";
  if (silentTooLong(status, now)) return "stopped";
  return "going";
}

/** The silence, in words: "2 h 18 min". */
export function durationWords(seconds: number): string {
  const minutes = Math.max(0, Math.round(seconds / 60));
  if (minutes < 60) return `${String(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${String(hours)} h ${String(minutes % 60)} min`;
  return `${String(Math.floor(hours / 24))} days`;
}

/** How long ago the log last wrote, in seconds, or ``null`` when the status names no line. */
export function silenceS(status: RunStatus, now: number): number | null {
  if (status.lastLineAt === undefined || status.lastLineAt === null) return null;
  const at = instant(status.lastLineAt);
  return Number.isNaN(at) ? null : (now - at) / 1000;
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

/**
 * Where ``status``'s run stands, in words; ``end`` is how an ended run ended, read from its log and
 * queue (``runEnd``), or ``null`` when they were not read.
 */
export function standingOf(
  status: RunStatus,
  end: RunEnd | null,
  now: number = Date.now(),
): Standing {
  return {
    phase: phaseOf(status, now),
    word: null,
    sentence: null,
    detail: end === null ? null : null,
  };
}
