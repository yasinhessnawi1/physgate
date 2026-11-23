/**
 * A run's timeline records as the server sends them: the trace, the decision sequence, where
 * the run stands, the token account and the gate checks with what each said, plus the few
 * event lines the timeline names directly. Each guard checks the fields the views show. Every
 * number here is the server's: nothing is counted or summed in this module.
 */
import type { GateMode } from "../design/components/verdict/GateMode";
import type { Verdict } from "../design/components/verdict/verdict";
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
import { instant } from "../words/runs";
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

/** One plan module's completion as the server reads it from the record and the registry. */
export interface ModuleCompletion {
  readonly subtask: string;
  /** Sizing's module, as the server tells it by the register's name for sizing. */
  readonly sizing: boolean;
  /** ``sign_off_owed``: a person's sign-off is open, whatever else is (ARCH-130). */
  readonly state: "complete" | "sign_off_owed" | "withheld" | "owed" | "not_declared";
  /** The precondition registry's open entries, each with its own reason. */
  readonly open: readonly { readonly name: string; readonly reason: string }[];
}

export interface RunStatus {
  readonly kind: string;
  readonly subtask: string | null;
  readonly halted: { readonly reason: string; readonly detail: string } | null;
  /** The incident on the record whose halt is owed, if any. */
  readonly owedHalt: { readonly cause: string; readonly subtask: string | null } | null;
  readonly completion: {
    /** Whether the run plans a subtask that declares completion. */
    readonly owner: boolean;
    readonly modules: readonly ModuleCompletion[];
  };
  /** The subtasks that wait for sizing's closing pass, in plan order. */
  readonly waiting: readonly string[];
  /** Each contract item a reopen superseded, by id: the item whose decision reopened its module. */
  readonly superseded: Readonly<Record<string, string>>;
  /** When the log's last line was written, or ``null`` when it holds none. */
  readonly lastLineAt?: string | null;
  /**
   * How long ago the last line was written, in seconds: the server's clock (``server_now``) less
   * the line's time, so the browser's clock is never read. ``null`` where either is not sent.
   */
  readonly silentS?: number | null;
  /**
   * The longest a living run goes without a line after its last one, in seconds: the session wall
   * clock after a session's spawn, a retry's delay after its schedule. ``null`` after any other
   * line, where a stage with no bound of its own (the physics gate) may be running.
   */
  readonly silenceBoundS?: number | null;
  /**
   * Whether a person's decision acts in this run; ``false`` in one that records decisions only,
   * where an escalated end waits on no one. Absent where the server did not say.
   */
  readonly acts?: boolean;
  /** The modules whose sign-off is owed, in plan order. */
  readonly signaturesOwed?: readonly string[];
  /**
   * Of those, each whose latest item a person may still decide; one not here was decided and
   * nothing left in the run can sign it. Absent where the server did not say.
   */
  readonly signaturesOpenToDecide?: readonly string[];
  /**
   * Whether an escalated end is for the sign-offs owed alone; ``false`` where another item is open
   * to a person as well (integration's call refused), which a decision there still answers.
   * Absent where the server did not say.
   */
  readonly endsOnSignaturesAlone?: boolean;
  /**
   * Each subtask that never ran, where the run ended as ``unrun``: why, and the readers that
   * merged without it. Absent where the server did not say.
   */
  readonly neverRan?: readonly {
    readonly subtask: string;
    readonly why: string;
    readonly ranWithout: readonly string[];
  }[];
}

function moduleCompletion(value: unknown): ModuleCompletion {
  const m = object(value, "a module's completion");
  return {
    subtask: text(m.subtask_id, "a subtask id"),
    sizing: flag(m.sizing, "whether it is sizing's"),
    state: oneOf(
      m.state,
      ["complete", "sign_off_owed", "withheld", "owed", "not_declared"] as const,
      "a completion state",
    ),
    open: list(m.open, "open preconditions").map((raw) => {
      const o = object(raw, "an open precondition");
      return { name: text(o.name, "a precondition"), reason: text(o.reason, "a reason") };
    }),
  };
}

/** A count of seconds the server sent, or ``null`` where it sent none. */
function secondsSent(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The seconds between the log's last line and the server's clock, both as the server sent them. */
function silenceOf(lastLineAt: unknown, serverNow: unknown): number | null {
  if (typeof lastLineAt !== "string" || typeof serverNow !== "string") return null;
  const silence = (instant(serverNow) - instant(lastLineAt)) / 1000;
  return Number.isFinite(silence) ? silence : null;
}

export function runStatus(value: unknown): RunStatus {
  const s = object(value, "a run status");
  const next = object(s.next_step, "a next step");
  const halted = s.halted === null ? null : object(s.halted, "a halt");
  const owed = s.owed_halt === null ? null : object(s.owed_halt, "a halt owed");
  const completion = object(s.completion, "a run's completion");
  return {
    kind: text(next.kind, "a step kind"),
    subtask: optionalText(next.subtask_id, "a subtask id"),
    halted:
      halted === null
        ? null
        : { reason: text(halted.reason, "a halt reason"), detail: text(halted.detail, "a detail") },
    owedHalt:
      owed === null
        ? null
        : {
            cause: text(owed.cause, "a cause"),
            subtask: optionalText(owed.subtask_id, "a subtask"),
          },
    completion: {
      owner: flag(completion.owner, "whether a subtask declares completion"),
      modules: list(completion.modules, "modules").map(moduleCompletion),
    },
    waiting: list(s.waiting ?? [], "the waiting subtasks").map((w) => text(w, "a subtask id")),
    superseded: Object.fromEntries(
      Object.entries(object(s.superseded ?? {}, "the superseded items")).map(([k, v]) => [
        k,
        text(v, "an item id"),
      ]),
    ),
    lastLineAt:
      s.last_line_at === undefined || s.last_line_at === null
        ? null
        : text(s.last_line_at, "a time"),
    silentS: silenceOf(s.last_line_at, s.server_now),
    silenceBoundS: secondsSent(s.silence_bound_s),
    ...(s.acts === undefined ? {} : { acts: flag(s.acts, "whether decisions act") }),
    signaturesOwed: list(s.sign_offs_owed ?? [], "the sign-offs owed").map((m) =>
      text(m, "a module"),
    ),
    ...(s.sign_offs_open_to_decide === undefined
      ? {}
      : {
          signaturesOpenToDecide: list(s.sign_offs_open_to_decide, "the sign-offs open").map((m) =>
            text(m, "a module"),
          ),
        }),
    ...(s.never_ran === undefined
      ? {}
      : {
          neverRan: list(s.never_ran, "the subtasks that never ran").map((raw) => {
            const n = object(raw, "a subtask that never ran");
            return {
              subtask: text(n.subtask_id, "a subtask id"),
              why: text(n.why, "why it never ran"),
              ranWithout: list(n.ran_without ?? [], "the readers that ran without it").map((r) =>
                text(r, "a subtask id"),
              ),
            };
          }),
        }),
    ...(s.ends_on_sign_offs_alone === undefined
      ? {}
      : {
          endsOnSignaturesAlone: flag(s.ends_on_sign_offs_alone, "whether only sign-offs are owed"),
        }),
  };
}

export interface Tokens {
  readonly byAttribution: Readonly<Record<string, Usage>>;
  readonly byKind: Readonly<Record<string, Usage>>;
  readonly total: Usage;
  /**
   * Per attribution, the tokens of responses cut off by a connection error: in none of the figures
   * above and none of the binary's totals, and whether they were billed is unknown.
   */
  readonly cutShort: Readonly<Record<string, Usage>>;
}

export function tokens(value: unknown): Tokens {
  const t = object(value, "a token account");
  const each = (raw: unknown, what: string) =>
    Object.fromEntries(Object.entries(object(raw, what)).map(([k, u]) => [k, usage(u)]));
  return {
    byAttribution: each(t.by_attribution, "tokens by attribution"),
    byKind: each(t.by_kind, "tokens by kind"),
    total: usage(t.total),
    cutShort: each(t.not_in_binary_totals_billing_unknown, "the cut-off responses' tokens"),
  };
}

/** The physics gate's eight checks, by the names its records use; a test holds this to the schema. */
export const CHECK_NAMES = [
  "units",
  "magnitude",
  "equilibrium",
  "power",
  "conservation",
  "thermal",
  "propagation",
  "laws",
] as const;
export type CheckName = (typeof CHECK_NAMES)[number];

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
  readonly name: CheckName;
  /** The check's number in the architecture's list, 1 to 8, as recorded. */
  readonly check: number | null;
  readonly ts: string | null;
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
    name: oneOf(e.name, CHECK_NAMES, "a check name"),
    check: optionalCount(e.check, "a check number"),
    ts: optionalText(e.ts, "a timestamp"),
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
