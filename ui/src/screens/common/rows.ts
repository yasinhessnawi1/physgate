/**
 * A run's event log as timeline rows: a sentence first, its actor, a short meta line and a
 * trailing verdict. Every sentence is built from the fields the line records and nothing else:
 * no cause, no advice, no comparison the record lacks. Lines that say nothing a person reads
 * (stage markers, token counts, worktree clean-ups) make no row.
 */
import type { RunEvent } from "../../api/events";
import type { GateMode } from "../../design/components/verdict/GateMode";
import type { Verdict } from "../../design/components/verdict/verdict";
import type { Quantity } from "../../design/quantity";
import { type Actor, eventActor, type Models } from "../../words/actors";
import { checkWords } from "../../words/checks";
import { setAsideWith } from "../../words/queue";

export type RowEnd =
  | { readonly kind: "gate"; readonly mode: GateMode; readonly outcome: Verdict }
  | { readonly kind: "gate-off" }
  | { readonly kind: "no-verdict" }
  | { readonly kind: "review"; readonly verdict: string };

export interface Row {
  readonly key: string;
  readonly seq: number;
  readonly ts: string;
  /** 0 the run, 1 a subtask, 2 an attempt. */
  readonly depth: 0 | 1 | 2;
  readonly actor: Actor;
  readonly sentence: string;
  /** A recorded value the sentence names, drawn as a quantity after it. */
  readonly value: Quantity | null;
  readonly meta: string;
  readonly end: RowEnd | null;
  readonly subtask: string | null;
  readonly attempt: number | null;
}

/** Each subtask's name as a person reads it: "Subtask 2", by the order the run planned them. */
export function subtaskNames(events: readonly RunEvent[]): ReadonlyMap<string, string> {
  const names = new Map<string, string>();
  for (const e of events)
    if (e.kind === "subtask_planned") names.set(e.subtask, `Subtask ${String(names.size + 1)}`);
  return names;
}

/** Each subtask's role, as planned. */
export function subtaskRoles(events: readonly RunEvent[]): Readonly<Record<string, string>> {
  const roles: Record<string, string> = {};
  for (const e of events) if (e.kind === "subtask_planned") roles[e.subtask] = e.role;
  return roles;
}

function capital(text: string): string {
  return `${(text[0] ?? "").toUpperCase()}${text.slice(1)}`;
}

const MODE_WORDS: Readonly<Record<GateMode, string>> = {
  on: "with the gate on",
  observe: "with the gate in observe mode",
  off: "with the gate off",
};

const SKIPPED_REASONS: Readonly<Record<string, string>> = {
  not_all_merged: "not every subtask merged",
  "gate_mode=off": "the gate is off for this run",
  nothing_planned: "nothing was planned",
};

function verdictOf(text: string): Verdict | null {
  return text === "pass" || text === "fail" || text === "warn" || text === "unchecked"
    ? text
    : null;
}

function gateMode(text: string): GateMode {
  return text === "observe" ? "observe" : text === "off" ? "off" : "on";
}

/** One line as a row, or ``null`` for a line no person reads as an event. */
export function rowOf(
  event: RunEvent,
  names: ReadonlyMap<string, string>,
  roles: Readonly<Record<string, string>>,
  models: Models,
): Row | null {
  const actor = eventActor(event, roles, models);
  const base = {
    key: String(event.seq),
    seq: event.seq,
    ts: event.ts,
    actor,
    value: null,
    end: null,
    subtask: null,
    attempt: null,
  };
  const subtaskName = (id: string) => names.get(id) ?? id;
  switch (event.kind) {
    case "run_started":
      return {
        ...base,
        depth: 0,
        sentence: `Run started ${MODE_WORDS[event.mode]}`,
        meta: `run ${event.runId}`,
      };
    case "decomposed":
      return {
        ...base,
        depth: 0,
        sentence: `Split the brief into ${String(event.subtasks)} ${event.subtasks === 1 ? "subtask" : "subtasks"}`,
        meta:
          event.interfaceNodes.length === 0
            ? "no interface nodes"
            : `interface ${event.interfaceNodes.join(", ")}`,
      };
    case "subtask_planned":
      return {
        ...base,
        depth: 1,
        sentence: `Planned ${subtaskName(event.subtask)}, for the ${event.role} agent`,
        meta: event.subtask,
        subtask: event.subtask,
      };
    case "session_ended": {
      const sentence =
        event.outcome === "completed"
          ? `Attempt ${String(event.attempt)}: the agent's session ended`
          : event.outcome === "infrastructure"
            ? `Attempt ${String(event.attempt)}: the session stopped on an infrastructure fault${event.cause === null ? "" : ` (${event.cause})`}`
            : `Attempt ${String(event.attempt)}: the session ended as ${event.outcome}`;
      return {
        ...base,
        depth: 2,
        sentence,
        meta: `${subtaskName(event.subtask)} · session ${event.sessionId}`,
        subtask: event.subtask,
        attempt: event.attempt,
      };
    }
    case "gate_ran": {
      const mode = gateMode(event.mode);
      const outcome = verdictOf(event.verdict);
      const failed = event.verdict === "fail";
      const sentence = failed
        ? capital(event.finding)
        : event.verdict === "pass"
          ? `The gate passed attempt ${String(event.attempt)}`
          : `The gate recorded ${event.verdict} on attempt ${String(event.attempt)}`;
      return {
        ...base,
        depth: 2,
        sentence,
        value: failed ? event.value : null,
        meta: `${failed && event.failingCheck !== null ? `${checkWords(event.failingCheck).name.toLowerCase()} · ` : ""}${subtaskName(event.subtask)} · attempt ${String(event.attempt)}`,
        end: outcome === null ? null : { kind: "gate", mode, outcome },
        subtask: event.subtask,
        attempt: event.attempt,
      };
    }
    case "gate_skipped":
      return {
        ...base,
        depth: 2,
        sentence: `The gate did not run on attempt ${String(event.attempt)}`,
        meta: `${subtaskName(event.subtask)} · attempt ${String(event.attempt)}`,
        end: { kind: "gate-off" },
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "review_ran":
      return {
        ...base,
        depth: 2,
        sentence:
          event.verdict === "pass"
            ? `The reviewer passed attempt ${String(event.attempt)}`
            : event.verdict === "fail"
              ? `The reviewer refused attempt ${String(event.attempt)}${event.finding === null ? "" : `: ${event.finding}`}`
              : `The review of attempt ${String(event.attempt)} ended ${event.verdict}${event.finding === null ? "" : `: ${event.finding}`}`,
        meta: `${subtaskName(event.subtask)} · attempt ${String(event.attempt)}${event.sessionId === null ? "" : ` · session ${event.sessionId}`}`,
        end: { kind: "review", verdict: event.verdict },
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "attempt_rejected":
      return {
        ...base,
        depth: 2,
        sentence: `Attempt ${String(event.attempt)} sent back for repair: ${event.finding}`,
        meta: `finding from the ${event.findingSource} · ${subtaskName(event.subtask)}`,
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "escalated":
      return {
        ...base,
        depth: 1,
        sentence: setAsideWith(event.itemId),
        meta: `${subtaskName(event.subtask)} · ${event.subtask}`,
        subtask: event.subtask,
      };
    case "merged":
      return {
        ...base,
        depth: 1,
        sentence: `Merged attempt ${String(event.attempt)} of ${subtaskName(event.subtask)}`,
        meta:
          event.mergeCommit === null
            ? event.subtask
            : `${event.subtask} · commit ${event.mergeCommit.slice(0, 7)}`,
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "integration_gate_ran": {
      const outcome = verdictOf(event.verdict);
      return {
        ...base,
        depth: 0,
        sentence: "The gate checked the whole design",
        meta: "integration",
        end: outcome === null ? null : { kind: "gate", mode: gateMode(event.mode), outcome },
      };
    }
    case "integration_gate_skipped":
      return {
        ...base,
        depth: 0,
        sentence: `The whole design was not gated: ${SKIPPED_REASONS[event.reason] ?? event.reason}`,
        meta: "integration",
      };
    default:
      return null;
  }
}

/**
 * A gate stage the log entered but recorded no result for: the run stopped there, or is there
 * now. It reads as no verdict, never as a pass.
 */
function unfinishedGate(
  event: RunEvent,
  events: readonly RunEvent[],
  names: ReadonlyMap<string, string>,
): Row | null {
  if (event.kind !== "stage_entered" || event.stage !== "gate") return null;
  const answered = events.some(
    (e) =>
      e.seq > event.seq &&
      (e.kind === "gate_ran" || e.kind === "gate_skipped") &&
      e.subtask === event.subtask &&
      e.attempt === event.attempt,
  );
  if (answered) return null;
  return {
    key: String(event.seq),
    seq: event.seq,
    ts: event.ts,
    depth: 2,
    actor: { kind: "deterministic", name: "Gate" },
    sentence: `The gate stage of attempt ${String(event.attempt)} began; no result is recorded`,
    value: null,
    meta: `${names.get(event.subtask) ?? event.subtask} · attempt ${String(event.attempt)}`,
    end: { kind: "no-verdict" },
    subtask: event.subtask,
    attempt: event.attempt,
  };
}

/** Every row of a run's log, in the log's order. */
export function rowsOf(events: readonly RunEvent[], models: Models): readonly Row[] {
  const names = subtaskNames(events);
  const roles = subtaskRoles(events);
  return events.flatMap((event) => {
    const row = rowOf(event, names, roles, models) ?? unfinishedGate(event, events, names);
    return row === null ? [] : [row];
  });
}
