/**
 * A run's timeline records as the server sends them: the trace, the decision sequence, where
 * the run stands, the token account and the gate checks with what each said, plus the few
 * event lines the timeline names directly. Each guard checks the fields the views show. Every
 * number here is the server's: nothing is counted or summed in this module.
 */
import type { GateMode } from "../design/components/GateMode";
import type { Verdict } from "../design/components/VerdictBadge";
import type { Quantity } from "../design/quantity";
import { requireQuantity } from "../design/quantity";
import {
  count,
  flag,
  list,
  object,
  oneOf,
  optionalCount,
  optionalText,
  seconds,
  text,
} from "./check";
import { ShapeError } from "./client";

export interface Usage {
  readonly input: number;
  readonly output: number;
  readonly cacheRead: number;
  readonly cacheWrite: number;
}

export function usage(value: unknown): Usage {
  const u = object(value, "a token usage");
  return {
    input: count(u.input_tokens, "input tokens"),
    output: count(u.output_tokens, "output tokens"),
    cacheRead: count(u.cache_read_input_tokens, "cache-read tokens"),
    cacheWrite: count(u.cache_creation_input_tokens, "cache-write tokens"),
  };
}

export const STAGES = [
  "resolve",
  "spawn",
  "verify_reading",
  "implement",
  "gate",
  "review",
  "decide",
  "diff",
] as const;
export type Stage = (typeof STAGES)[number];

export interface StepTiming {
  readonly seq: number;
  readonly subtask: string;
  readonly attempt: number;
  readonly stage: Stage;
  readonly entered: string;
  readonly seconds: number;
}

export interface SessionTrace {
  readonly sessionId: string;
  readonly subtask: string | null;
  readonly attempt: number | null;
  readonly outcome: "completed" | "infrastructure" | "left_over";
  readonly cause: string | null;
  readonly wallClockS: number | null;
  readonly tokens: Usage;
  readonly partial: boolean;
}

export interface Trace {
  readonly manifestId: string;
  readonly runId: string;
  readonly started: string;
  readonly last: string;
  readonly steps: readonly StepTiming[];
  readonly sessions: readonly SessionTrace[];
  readonly decompositionTokens: Usage;
  readonly reviewerTokens: Readonly<Record<string, Usage>>;
  readonly routingTokens: Usage;
}

export function trace(value: unknown): Trace {
  const t = object(value, "a trace");
  return {
    manifestId: text(t.manifest_id, "a manifest id"),
    runId: text(t.run_id, "a run id"),
    started: text(t.started, "a timestamp"),
    last: text(t.last, "a timestamp"),
    steps: list(t.steps, "the steps").map((raw) => {
      const s = object(raw, "a step");
      return {
        seq: count(s.seq, "a sequence number"),
        subtask: text(s.subtask_id, "a subtask id"),
        attempt: count(s.attempt, "an attempt"),
        stage: oneOf(s.stage, STAGES, "a stage"),
        entered: text(s.entered, "a timestamp"),
        seconds: seconds(s.seconds, "a duration"),
      };
    }),
    sessions: list(t.sessions, "the sessions").map((raw) => {
      const s = object(raw, "a session");
      return {
        sessionId: text(s.session_id, "a session id"),
        subtask: optionalText(s.subtask_id, "a subtask id"),
        attempt: optionalCount(s.attempt, "an attempt"),
        outcome: oneOf(
          s.outcome,
          ["completed", "infrastructure", "left_over"] as const,
          "a session outcome",
        ),
        cause: optionalText(s.cause, "a cause"),
        wallClockS: s.wall_clock_s === null ? null : seconds(s.wall_clock_s, "a wall clock"),
        tokens: usage(s.tokens),
        partial: flag(s.partial, "a partial flag"),
      };
    }),
    decompositionTokens: usage(t.decomposition_tokens),
    reviewerTokens: Object.fromEntries(
      Object.entries(object(t.reviewer_tokens, "reviewer tokens")).map(([k, u]) => [k, usage(u)]),
    ),
    routingTokens: usage(t.routing_tokens),
  };
}

/** One decision of the run, as the decision sequence names it. */
export interface Decision {
  readonly step: string;
  readonly seq: number;
  readonly subtask: string | null;
  readonly attempt: number | null;
  readonly verdict: string | null;
  readonly failingCheck: string | null;
  readonly findingKey: string | null;
  readonly cause: string | null;
  readonly reason: string | null;
}

export function decisions(value: unknown): readonly Decision[] {
  return list(object(value, "a decision sequence").decisions, "decisions").map((raw) => {
    const d = object(raw, "a decision");
    return {
      step: text(d.step, "a decision step"),
      seq: count(d.seq, "a sequence number"),
      subtask: optionalText(d.subtask_id, "a subtask id"),
      attempt: optionalCount(d.attempt, "an attempt"),
      verdict: optionalText(d.verdict, "a verdict"),
      failingCheck: optionalText(d.failing_check, "a failing check"),
      findingKey: optionalText(d.finding_key, "a finding key"),
      cause: optionalText(d.cause, "a cause"),
      reason: optionalText(d.reason, "a reason"),
    };
  });
}

export interface RunStatus {
  readonly kind: string;
  readonly subtask: string | null;
  readonly halted: { readonly reason: string; readonly detail: string } | null;
}

export function runStatus(value: unknown): RunStatus {
  const s = object(value, "a run status");
  const next = object(s.next_step, "a next step");
  const halted = s.halted === null ? null : object(s.halted, "a halt");
  return {
    kind: text(next.kind, "a step kind"),
    subtask: optionalText(next.subtask_id, "a subtask id"),
    halted:
      halted === null
        ? null
        : { reason: text(halted.reason, "a halt reason"), detail: text(halted.detail, "a detail") },
  };
}

export interface Tokens {
  readonly byAttribution: Readonly<Record<string, Usage>>;
  readonly byKind: Readonly<Record<string, Usage>>;
  readonly total: Usage;
}

export function tokens(value: unknown): Tokens {
  const t = object(value, "a token account");
  const each = (raw: unknown, what: string) =>
    Object.fromEntries(Object.entries(object(raw, what)).map(([k, u]) => [k, usage(u)]));
  return {
    byAttribution: each(t.by_attribution, "tokens by attribution"),
    byKind: each(t.by_kind, "tokens by kind"),
    total: usage(t.total),
  };
}

export interface CheckDetails {
  readonly form: string;
  readonly evaluated: number | null;
  readonly quantities: readonly string[];
  readonly low: Quantity | null;
  readonly high: Quantity | null;
}

export interface GateCheck {
  readonly seq: number;
  readonly subtask: string;
  readonly attempt: number | null;
  readonly name: string;
  readonly scope: string;
  readonly mode: GateMode;
  readonly outcome: Verdict;
  readonly blocking: boolean;
  readonly value: Quantity | null;
  readonly node: string | null;
  readonly evaluated: number | null;
  readonly reviewerHadPassed: boolean | null;
  readonly expected: string | null;
  readonly message: string;
  readonly details: CheckDetails;
}

export function gateCheck(value: unknown): GateCheck {
  const c = object(value, "a gate check");
  const e = object(c.event, "a gate event");
  const d = object(c.details, "a check's details");
  const passed = e.reviewer_had_passed;
  if (passed !== null && typeof passed !== "boolean") throw new ShapeError("a reviewer verdict");
  return {
    seq: count(e.seq, "a sequence number"),
    subtask: text(e.subtask_id, "a subtask id"),
    attempt: optionalCount(e.attempt, "an attempt"),
    name: text(e.name, "a check name"),
    scope: text(e.scope, "a scope"),
    mode: oneOf(e.gate_mode, ["on", "observe"] as const, "a gate mode"),
    outcome: oneOf(e.outcome, ["pass", "fail", "warn", "unchecked"] as const, "a check outcome"),
    blocking: flag(e.blocking, "a blocking flag"),
    value: e.value === null ? null : requireQuantity(e.value),
    node: optionalText(e.node, "a node id"),
    evaluated: optionalCount(e.evaluated, "an evaluated count"),
    reviewerHadPassed: passed,
    expected: optionalText(c.expected, "a bound"),
    message: text(c.message, "a message"),
    details: {
      form: text(d.form, "a details form"),
      evaluated: optionalCount(d.evaluated, "an evaluated count"),
      quantities:
        d.quantities === undefined
          ? []
          : list(d.quantities, "quantities").map((q) => text(q, "a quantity name")),
      low: d.low === undefined ? null : requireQuantity(d.low),
      high: d.high === undefined ? null : requireQuantity(d.high),
    },
  };
}

/** The event lines the timeline names directly, read from the run's log. */
export interface TimelineEvents {
  readonly decomposed: {
    readonly seq: number;
    readonly ts: string;
    readonly model: string;
    readonly subtasks: number;
    readonly interfaceNodes: readonly string[];
  } | null;
  readonly roles: Readonly<Record<string, string>>;
  readonly reviews: readonly {
    readonly seq: number;
    readonly ts: string;
    readonly subtask: string;
    readonly attempt: number;
    readonly verdict: string;
    readonly reviewerModel: string;
    readonly sessionId: string;
    readonly readingVerified: boolean | null;
    readonly failingItem: string | null;
  }[];
  readonly rejections: readonly {
    readonly subtask: string;
    readonly attempt: number;
    readonly findingKey: string;
    readonly repeatsPrevious: boolean;
  }[];
  readonly integration: {
    readonly seq: number;
    readonly ts: string;
    readonly kind: "ran" | "skipped";
    readonly verdict: string | null;
    readonly reason: string | null;
  } | null;
  readonly gateSkipped: readonly { readonly subtask: string; readonly attempt: number }[];
}

export function timelineEvents(events: readonly unknown[]): TimelineEvents {
  let decomposed: TimelineEvents["decomposed"] = null;
  let integration: TimelineEvents["integration"] = null;
  const roles: Record<string, string> = {};
  const reviews: TimelineEvents["reviews"][number][] = [];
  const rejections: TimelineEvents["rejections"][number][] = [];
  const gateSkipped: TimelineEvents["gateSkipped"][number][] = [];
  for (const raw of events) {
    const e = object(raw, "an event");
    const seq = count(e.seq, "a sequence number");
    const ts = text(e.ts, "a timestamp");
    if (e.kind === "decomposed") {
      decomposed = {
        seq,
        ts,
        model: text(e.model, "a model"),
        subtasks: count(e.subtasks, "a subtask count"),
        interfaceNodes: list(e.interface_nodes, "interface nodes").map((n) => text(n, "a node")),
      };
    } else if (e.kind === "subtask_planned") {
      roles[text(e.subtask_id, "a subtask id")] = text(e.assigned_role, "a role");
    } else if (e.kind === "review_ran") {
      const result = object(e.result, "a review result");
      const verified = result.reading_verified;
      reviews.push({
        seq,
        ts,
        subtask: text(e.subtask_id, "a subtask id"),
        attempt: count(e.attempt, "an attempt"),
        verdict: text(result.verdict, "a verdict"),
        reviewerModel: text(result.reviewer_model, "a model"),
        sessionId: text(result.session_id, "a session id"),
        readingVerified:
          verified === undefined || verified === null ? null : flag(verified, "a flag"),
        failingItem: optionalText(result.failing_item, "a rubric item"),
      });
    } else if (e.kind === "attempt_rejected") {
      rejections.push({
        subtask: text(e.subtask_id, "a subtask id"),
        attempt: count(e.attempt, "an attempt"),
        findingKey: text(e.finding_key, "a finding key"),
        repeatsPrevious: flag(e.repeats_previous, "a repeat flag"),
      });
    } else if (e.kind === "integration_gate_ran") {
      const result = object(e.result, "a gate result");
      integration = {
        seq,
        ts,
        kind: "ran",
        verdict: text(result.verdict, "a verdict"),
        reason: null,
      };
    } else if (e.kind === "integration_gate_skipped") {
      integration = { seq, ts, kind: "skipped", verdict: null, reason: text(e.reason, "a reason") };
    } else if (e.kind === "gate_skipped") {
      gateSkipped.push({
        subtask: text(e.subtask_id, "a subtask id"),
        attempt: count(e.attempt, "an attempt"),
      });
    }
  }
  return { decomposed, roles, reviews, rejections, integration, gateSkipped };
}
