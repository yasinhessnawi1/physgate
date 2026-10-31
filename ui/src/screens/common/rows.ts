/**
 * A run's event log as timeline rows: a sentence first, its actor, a short meta line and a
 * trailing verdict. Every sentence is built from the fields the line records and nothing else:
 * no cause, no advice, no comparison the record lacks. Lines that say nothing a person reads
 * (stage markers, token counts, worktree clean-ups) make no row.
 */
import type { RunEvent } from "../../api/events";
import type { GateCheck } from "../../api/run";
import type { GateMode } from "../../design/components/verdict/GateMode";
import type { Verdict } from "../../design/components/verdict/verdict";
import type { Quantity } from "../../design/quantity";
import { type Actor, eventActor, type Models } from "../../words/actors";
import { checkWords } from "../../words/checks";
import { nodeLabel, quantityLabel } from "../../words/humanise";
import { causeWords, triesWords } from "../../words/review";
import { setAsideWith } from "../../words/queue";

export type RowEnd =
  | { readonly kind: "gate"; readonly mode: GateMode; readonly outcome: Verdict }
  /** A gate line whose recorded mode the interface does not know: shown as written, never as on. */
  | { readonly kind: "gate-unknown-mode"; readonly mode: string; readonly outcome: Verdict }
  | { readonly kind: "gate-off" }
  | { readonly kind: "no-verdict" }
  | { readonly kind: "review"; readonly verdict: string };

export interface Row {
  readonly key: string;
  readonly seq: number;
  readonly ts: string;
  /** 0 the run, 1 a subtask, 2 an attempt. */
  readonly depth: 0 | 1 | 2;
  /** Who wrote the line, or none when the record maps to no actor. */
  readonly actor: Actor | null;
  readonly sentence: string;
  /** The rest of a long finding the sentence opens with, shown folded; ``null`` when it fits. */
  readonly more: string | null;
  /** What the fold's control says, when it folds something other than the rest of a finding. */
  readonly moreLabel?: string;
  /** A recorded value the sentence names, drawn as a quantity after it. */
  readonly value: Quantity | null;
  /** A value the sentence ends on, drawn straight after it rather than as recorded beside it. */
  readonly valueInline?: boolean;
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
  plan_rejected: "a person rejected the plan",
};

/** The longest first line a finding gets on a row before the rest is folded away. */
const FIRST_LINE = 160;

/**
 * A finding as a short first line and the rest: the first sentence (or line), cut at a word when
 * it is still long. Nothing is dropped; the rest is every character after the first line.
 */
export function firstLine(text: string): { readonly head: string; readonly rest: string | null } {
  const whole = text.trim();
  const end = /[.!?](\s|$)|\n/.exec(whole);
  let cut = end === null ? whole.length : end.index + (whole[end.index] === "\n" ? 0 : 1);
  let ellipsis = false;
  if (cut > FIRST_LINE) {
    const space = whole.lastIndexOf(" ", FIRST_LINE);
    cut = space > 0 ? space : FIRST_LINE;
    ellipsis = true;
  }
  const rest = whole.slice(cut).trim();
  const head = whole.slice(0, cut).trim();
  return { head: ellipsis ? `${head}…` : head, rest: rest === "" ? null : rest };
}

function verdictOf(text: string): Verdict | null {
  return text === "pass" || text === "fail" || text === "warn" || text === "unchecked"
    ? text
    : null;
}

/** A gate line's end in the mode it records; a mode not known is shown as written, never as on. */
function gateEnd(mode: string, outcome: Verdict): RowEnd {
  return mode === "on" || mode === "observe" || mode === "off"
    ? { kind: "gate", mode, outcome }
    : { kind: "gate-unknown-mode", mode, outcome };
}

/** A quantity of a node in words: "Current draw on Drive motor". */
function named(quantity: string, node: string): string {
  return `${quantityLabel(quantity)} on ${nodeLabel(node)}`;
}

/** A dispute's ruling, by the level that stands. */
function rulingWords(level: string, attempt: number, what: string): string {
  const a = `attempt ${String(attempt)}`;
  switch (level) {
    case "gate":
      return `The gate refused ${a}, so its refusal stands over the dispute of ${what}`;
    case "person":
      return `A person's choice stands: ${a} holds the value chosen for ${what}`;
    case "sizing":
      return `Sizing's value of ${what} stands over ${a}'s dispute`;
    default:
      return `The dispute of ${what} goes to a person`;
  }
}

/** A failed contract clause's ruling: the gate's, or a person's. */
function clauseWords(event: Extract<RunEvent, { kind: "contract_ruled" }>): string {
  const iface = nodeLabel(event.interface);
  if (event.quantity === null && event.level !== "gate")
    return `Interface ${iface} has no quantity, and a side is not joined to it: ruled for a person`;
  const clause =
    event.quantity === null
      ? `interface ${iface}`
      : `the contract clause ${quantityLabel(event.quantity)} on interface ${iface}`;
  return event.level === "gate"
    ? `The gate's refusal stands over ${clause}`
    : `${capital(clause)} failed: ruled for a person`;
}

const REJECTED_WORDS: Readonly<Record<string, string>> = {
  person: "as a person's decision ordered",
  fix_not_accepted: "the fix a person ordered was not accepted",
  closing_pass: "sizing's closing pass ended without merging the value a person chose",
};

/** One line as a row, or ``null`` for a line no person reads as an event. */
export function rowOf(
  event: RunEvent,
  names: ReadonlyMap<string, string>,
  roles: Readonly<Record<string, string>>,
  models: Models,
  checks?: readonly GateCheck[],
): Row | null {
  const actor = eventActor(event, roles, models);
  const base = {
    key: String(event.seq),
    seq: event.seq,
    ts: event.ts,
    actor,
    value: null,
    more: null,
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
        end: outcome === null ? null : gateEnd(event.mode, outcome),
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
    case "review_ran": {
      const first = event.finding === null ? null : firstLine(event.finding);
      return {
        ...base,
        depth: 2,
        sentence:
          event.verdict === "pass"
            ? `The reviewer passed attempt ${String(event.attempt)}`
            : event.verdict === "fail"
              ? `The reviewer refused attempt ${String(event.attempt)}${first === null ? "" : `: ${first.head}`}`
              : `The review of attempt ${String(event.attempt)} ended ${event.verdict}${first === null ? "" : `: ${first.head}`}`,
        more: first?.rest ?? null,
        meta: `${subtaskName(event.subtask)} · attempt ${String(event.attempt)}${event.sessionId === null ? "" : ` · session ${event.sessionId}`}`,
        end: { kind: "review", verdict: event.verdict },
        subtask: event.subtask,
        attempt: event.attempt,
      };
    }
    case "review_unavailable":
      return {
        ...base,
        depth: 2,
        sentence: `Review of attempt ${String(event.attempt)} reached no verdict: ${causeWords(event.cause)}${triesWords(event.detail)}`,
        meta: `${subtaskName(event.subtask)} · attempt ${String(event.attempt)} · cause ${event.cause}`,
        end: { kind: "review", verdict: "no verdict" },
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "attempt_rejected":
      return {
        ...base,
        depth: 2,
        sentence: `Attempt ${String(event.attempt)} rejected: ${event.finding}`,
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
      const left = (checks ?? []).filter(
        (c) => c.subtask === "integration" && c.seq === event.seq && c.outcome === "unchecked",
      ).length;
      return {
        ...base,
        depth: 0,
        sentence: "The gate checked the whole design",
        meta: left === 0 ? "integration" : `integration · ${String(left)} left unchecked`,
        end: outcome === null ? null : gateEnd(event.mode, outcome),
      };
    }
    case "integration_gate_skipped":
      return {
        ...base,
        depth: 0,
        sentence: `The whole design was not gated: ${SKIPPED_REASONS[event.reason] ?? event.reason}`,
        meta: "integration",
      };
    case "completion_declared":
      return {
        ...base,
        depth: 2,
        sentence:
          event.modules.length === 0
            ? `Attempt ${String(event.attempt)} declared no module complete`
            : `Attempt ${String(event.attempt)} declared complete: ${event.modules.map(subtaskName).join(", ")}`,
        meta: `${subtaskName(event.subtask)} · attempt ${String(event.attempt)}`,
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "module_completed":
      return {
        ...base,
        depth: 1,
        sentence: `${subtaskName(event.subtask)} recorded complete`,
        meta: `${event.subtask} · declared by attempt ${String(event.attempt)} of ${subtaskName(event.declaredBy)}`,
        subtask: event.subtask,
      };
    case "contract_pairs_planned":
      return {
        ...base,
        depth: 0,
        sentence: `Planned ${String(event.pairs.length)} contract ${event.pairs.length === 1 ? "pair" : "pairs"}`,
        meta: event.pairs.map((p) => `${p.producer} to ${p.consumer}`).join(", "),
      };
    case "contract_tested":
      return {
        ...base,
        depth: 0,
        sentence: `The contract of ${event.pair.producer} to ${event.pair.consumer} ${event.outcome === "pass" ? "held" : event.outcome === "fail" ? "failed" : `recorded ${event.outcome}`}`,
        meta: `${event.first ? "first test" : "retest"} · ${event.pair.interfaces.join(", ")}`,
      };
    case "integration_state_issued":
      return {
        ...base,
        depth: 2,
        sentence: `Issued the design's state to attempt ${String(event.attempt)}`,
        meta: `${subtaskName(event.subtask)} · ${String(event.length)} bytes`,
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "dispute_recorded":
      return {
        ...base,
        depth: 2,
        sentence: `Attempt ${String(event.attempt)} disputes sizing's value of ${named(event.quantity, event.node)}, proposing`,
        value: event.proposed,
        valueInline: true,
        // The agent's own text, which nothing checks: folded, and said to be the agent's.
        more: `The agent's reason, in its own words, which nothing checks: ${event.reason}`,
        moreLabel: "The agent's reason",
        meta: `${subtaskName(event.subtask)} · attempt ${String(event.attempt)} · ${event.node} · ${event.quantity}`,
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "arbitration_decided":
      return {
        ...base,
        depth: 2,
        sentence: rulingWords(event.level, event.attempt, named(event.quantity, event.node)),
        meta: `${subtaskName(event.subtask)} · attempt ${String(event.attempt)} · sizing's value from revision ${String(event.heldRevision)}`,
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "contract_ruled":
      return {
        ...base,
        depth: 0,
        sentence: clauseWords(event),
        meta: `contract · ${String(event.failing)} failing ${event.failing === 1 ? "node" : "nodes"}`,
      };
    case "contract_item_raised":
      return {
        ...base,
        depth: 0,
        sentence: `A failed contract was sent to a person (${event.itemId})`,
        meta: "contract",
      };
    case "attempt_returned":
      return {
        ...base,
        depth: 2,
        sentence: `Sizing's closing pass merged; attempt ${String(event.attempt)} is judged again from its finished session, with no new session (${event.itemId})`,
        meta: `${subtaskName(event.subtask)} · attempt ${String(event.attempt)}`,
        subtask: event.subtask,
        attempt: event.attempt,
      };
    case "subtask_reopened":
      return {
        ...base,
        depth: 1,
        sentence: `${subtaskName(event.subtask)} reopened for attempt ${String(event.attempt)}, as a person's choice on ${event.itemId} ordered; its earlier merge stays on the record`,
        meta: `${event.subtask} · earlier merge ${event.mergeCommit.slice(0, 7)}`,
        subtask: event.subtask,
      };
    case "subtask_rejected": {
      const why = REJECTED_WORDS[event.by] ?? event.by;
      const item = event.itemId === null ? "" : ` (${event.itemId})`;
      return {
        ...base,
        depth: 1,
        sentence:
          event.by === "person"
            ? `${subtaskName(event.subtask)} ended rejected, ${why}${item}`
            : `${subtaskName(event.subtask)} ended rejected: ${why}${item}`,
        meta: `${event.subtask} · attempt ${String(event.attempt)}`,
        subtask: event.subtask,
      };
    }
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
    more: null,
    value: null,
    meta: `${names.get(event.subtask) ?? event.subtask} · attempt ${String(event.attempt)}`,
    end: { kind: "no-verdict" },
    subtask: event.subtask,
    attempt: event.attempt,
  };
}

/** Every row of a run's log, in the log's order. */
export function rowsOf(
  events: readonly RunEvent[],
  models: Models,
  checks?: readonly GateCheck[],
): readonly Row[] {
  const names = subtaskNames(events);
  const roles = subtaskRoles(events);
  return events.flatMap((event) => {
    const row = rowOf(event, names, roles, models, checks) ?? unfinishedGate(event, events, names);
    if (row === null) return [];
    if (event.kind !== "attempt_rejected") return [row];
    // A rejection that repeats the finding an earlier row of the same attempt already shows says
    // so, and does not print the text a second time.
    const earlier = events.find(
      (e) =>
        (e.kind === "review_ran" || e.kind === "gate_ran") &&
        e.seq < event.seq &&
        e.subtask === event.subtask &&
        e.attempt === event.attempt &&
        e.finding === event.finding,
    );
    if (earlier === undefined) return [row];
    const by = earlier.kind === "review_ran" ? "reviewer's" : "gate's";
    return [
      { ...row, sentence: `Attempt ${String(event.attempt)} rejected on the ${by} finding above` },
    ];
  });
}
