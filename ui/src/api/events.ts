/**
 * A run's event log, read for the lines the screens turn into sentences. Each line keeps its
 * sequence number, its time and its kind; the fields a sentence is built from are checked here,
 * and a line of a kind no screen reads is kept as its kind alone. Nothing is counted here.
 */
import type { GateMode } from "../design/components/verdict/GateMode";
import { type Quantity, requireQuantity } from "../design/quantity";
import { count, list, object, oneOf, optionalText, text } from "./check";

interface Line {
  readonly seq: number;
  readonly ts: string;
}

export type RunEvent = Line &
  (
    | { readonly kind: "run_started"; readonly runId: string; readonly mode: GateMode }
    | {
        readonly kind: "decomposed";
        readonly model: string;
        readonly subtasks: number;
        readonly interfaceNodes: readonly string[];
      }
    | { readonly kind: "subtask_planned"; readonly subtask: string; readonly role: string }
    | {
        readonly kind: "session_ended";
        readonly subtask: string;
        readonly attempt: number;
        readonly sessionId: string;
        readonly outcome: string;
        readonly cause: string | null;
        readonly sealed: boolean;
      }
    | {
        readonly kind: "gate_ran";
        readonly subtask: string;
        readonly attempt: number;
        readonly verdict: string;
        readonly mode: string;
        readonly finding: string;
        readonly failingCheck: string | null;
        readonly value: Quantity | null;
      }
    | { readonly kind: "gate_skipped"; readonly subtask: string; readonly attempt: number }
    | {
        readonly kind: "review_ran";
        readonly subtask: string;
        readonly attempt: number;
        readonly verdict: string;
        readonly finding: string | null;
        readonly reviewerModel: string | null;
        readonly sessionId: string | null;
      }
    | {
        readonly kind: "attempt_rejected";
        readonly subtask: string;
        readonly attempt: number;
        readonly findingSource: string;
        readonly finding: string;
      }
    | { readonly kind: "escalated"; readonly subtask: string; readonly itemId: string }
    | {
        readonly kind: "merged";
        readonly subtask: string;
        readonly attempt: number;
        readonly mergeCommit: string | null;
      }
    | { readonly kind: "integration_gate_ran"; readonly verdict: string; readonly mode: string }
    | { readonly kind: "integration_gate_skipped"; readonly reason: string }
    | {
        readonly kind: "stage_entered";
        readonly subtask: string;
        readonly attempt: number;
        readonly stage: string;
      }
    | { readonly kind: "other"; readonly recorded: string }
  );

/** One event line as the screens read it; a line of another shape is refused whole. */
export function runEvent(value: unknown): RunEvent {
  const e = object(value, "an event");
  const line = { seq: count(e.seq, "a sequence number"), ts: text(e.ts, "a timestamp") };
  const subtask = () => text(e.subtask_id, "a subtask id");
  const attempt = () => count(e.attempt, "an attempt");
  switch (e.kind) {
    case "run_started":
      return {
        ...line,
        kind: "run_started",
        runId: text(e.run_id, "a run id"),
        mode: oneOf(e.gate_mode, ["on", "observe", "off"] as const, "a gate mode"),
      };
    case "decomposed":
      return {
        ...line,
        kind: "decomposed",
        model: text(e.model, "a model"),
        subtasks: count(e.subtasks, "a subtask count"),
        interfaceNodes: list(e.interface_nodes, "interface nodes").map((n) => text(n, "a node")),
      };
    case "subtask_planned":
      return {
        ...line,
        kind: "subtask_planned",
        subtask: subtask(),
        role: text(e.assigned_role, "a role"),
      };
    case "session_ended":
      return {
        ...line,
        kind: "session_ended",
        subtask: subtask(),
        attempt: attempt(),
        sessionId: text(e.session_id, "a session id"),
        outcome: text(e.outcome, "a session outcome"),
        cause: optionalText(e.cause, "a cause"),
        sealed: e.trajectory_seal !== null && e.trajectory_seal !== undefined,
      };
    case "gate_ran": {
      const r = object(e.result, "a gate result");
      return {
        ...line,
        kind: "gate_ran",
        subtask: subtask(),
        attempt: attempt(),
        verdict: text(r.verdict, "a verdict"),
        mode: text(r.mode, "a gate mode"),
        finding: text(r.finding, "a finding"),
        failingCheck: optionalText(r.failing_check, "a check name"),
        value:
          r.numeric_output === null || r.numeric_output === undefined
            ? null
            : requireQuantity(r.numeric_output),
      };
    }
    case "gate_skipped":
      return { ...line, kind: "gate_skipped", subtask: subtask(), attempt: attempt() };
    case "review_ran": {
      const r = object(e.result, "a review result");
      return {
        ...line,
        kind: "review_ran",
        subtask: subtask(),
        attempt: attempt(),
        verdict: text(r.verdict, "a verdict"),
        finding: optionalText(r.finding, "a finding"),
        reviewerModel: optionalText(r.reviewer_model, "a model"),
        sessionId: optionalText(r.session_id, "a session id"),
      };
    }
    case "attempt_rejected": {
      const f = object(e.finding, "a finding");
      return {
        ...line,
        kind: "attempt_rejected",
        subtask: subtask(),
        attempt: attempt(),
        findingSource: text(f.source, "a finding's source"),
        finding: text(f.text, "a finding"),
      };
    }
    case "escalated":
      return {
        ...line,
        kind: "escalated",
        subtask: subtask(),
        itemId: text(e.item_id, "an item id"),
      };
    case "merged":
      return {
        ...line,
        kind: "merged",
        subtask: subtask(),
        attempt: attempt(),
        mergeCommit: optionalText(e.merge_commit, "a commit"),
      };
    case "integration_gate_ran": {
      const r = object(e.result, "a gate result");
      return {
        ...line,
        kind: "integration_gate_ran",
        verdict: text(r.verdict, "a verdict"),
        mode: text(r.mode, "a gate mode"),
      };
    }
    case "integration_gate_skipped":
      return { ...line, kind: "integration_gate_skipped", reason: text(e.reason, "a reason") };
    case "stage_entered":
      return {
        ...line,
        kind: "stage_entered",
        subtask: subtask(),
        attempt: attempt(),
        stage: text(e.stage, "a stage"),
      };
    default:
      return { ...line, kind: "other", recorded: text(e.kind, "an event kind") };
  }
}

/** The attempt a line names, when it names one. */
export function attemptOf(event: RunEvent): { subtask: string; attempt: number } | null {
  return "attempt" in event && "subtask" in event
    ? { subtask: event.subtask, attempt: event.attempt }
    : null;
}

/** The time the run's first line, its run_started, was written. */
export function startedAt(events: readonly RunEvent[]): string | null {
  return events.find((e) => e.kind === "run_started")?.ts ?? null;
}
