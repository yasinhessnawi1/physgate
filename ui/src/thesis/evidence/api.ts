/**
 * The Evidence screen's four read routes, and the guards their answers are held to. A guard takes
 * an answer exactly as the server sends it: a field missing, or one it does not know, refuses the
 * whole answer, so a view gets the record or a refusal and never a part of either. Nothing is
 * computed here. A held-out tier's field is refused wherever it would appear, so none reaches a
 * page even if a server sent one.
 */
import { ShapeError } from "../../api/client";
import { count, flag, list, object, oneOf, optionalText, text } from "../../api/check";
import { type CostRecord, costRecord } from "../../api/records";
import type { Refusal } from "../../design/components/status/States";

/** A run's kind as its record names it, in the order the screen shows them. */
export const KINDS = ["reportable", "development", "ablation"] as const;
export type Kind = (typeof KINDS)[number];

/** The held-out tier's fields, which no answer may carry. */
export const HELD_OUT: readonly string[] = ["held_out", "held_out_canaries", "held_out_sha256"];

export const RUNS_ROUTE = "/api/evidence/runs";
export const CATCHES_ROUTE = "/api/evidence/catches";
export const PRICES_ROUTE = "/api/prices";

/** A run by its place: its root's position and its directory's name. */
export interface Place {
  readonly root: number;
  readonly name: string;
}

/** The place's key in an address: ``root/name``. */
export function placeKey(place: Place): string {
  return `${String(place.root)}/${place.name}`;
}

/** The place a ``root/name`` key names, or ``null`` for anything else. */
export function parsePlace(key: string | null): Place | null {
  const found = key === null ? null : /^(\d{1,4})\/(.+)$/.exec(key);
  if (found === null) return null;
  return { root: Number(found[1]), name: found[2] ?? "" };
}

function at(place: Place): string {
  return `${String(place.root)}/${encodeURIComponent(place.name)}`;
}

export function spendRoute(place: Place, date: string): string {
  return `/api/evidence/spend/${at(place)}/${encodeURIComponent(date)}`;
}

export function compareRoute(a: Place, b: Place): string {
  return `/api/evidence/compare/${at(a)}/${at(b)}`;
}

/** ``value`` as an object holding every one of ``required``, and none but ``optional`` besides. */
function exact(
  value: unknown,
  what: string,
  required: readonly string[],
  optional: readonly string[] = [],
): Record<string, unknown> {
  const record = object(value, what);
  for (const key of required) if (!Object.hasOwn(record, key)) throw new ShapeError(what);
  for (const key of Object.keys(record))
    if (!required.includes(key) && !optional.includes(key)) throw new ShapeError(what);
  return record;
}

function integer(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) throw new ShapeError(what);
  return value;
}

function texts(value: unknown, what: string): readonly string[] {
  return list(value, what).map((item) => text(item, what));
}

/** A setting map as recorded: refused if it names a held-out tier's field. */
function settings(value: unknown, what: string): Readonly<Record<string, unknown>> {
  const record = object(value, what);
  for (const key of Object.keys(record)) if (HELD_OUT.includes(key)) throw new ShapeError(what);
  return record;
}

// -- where a figure came from ------------------------------------------------------------------

/** Where a figure came from, as the spend, the comparison and the catches name it. */
export interface EvidenceSource extends Place {
  readonly runId: string;
  readonly manifestId: string;
  readonly kind: Kind;
  readonly commit: string | null;
  readonly clean: boolean;
}

const SOURCE = [
  "root",
  "name",
  "run_id",
  "manifest_id",
  "kind",
  "harness_commit",
  "harness_clean",
] as const;

export function evidenceSource(value: unknown): EvidenceSource {
  const s = exact(value, "a figure's source", SOURCE);
  return {
    root: count(s.root, "a root's position"),
    name: text(s.name, "a run's name"),
    runId: text(s.run_id, "a run id"),
    manifestId: text(s.manifest_id, "a manifest id"),
    kind: oneOf(s.kind, KINDS, "a run's kind"),
    commit: optionalText(s.harness_commit, "a harness commit"),
    clean: flag(s.harness_clean, "whether the harness was clean"),
  };
}

// -- the runs ---------------------------------------------------------------------------------

/** A run the server read: what it recorded, and the manifest id its first log line names. */
export interface ReadRun extends Place {
  readonly read: true;
  readonly runId: string;
  readonly seed: number;
  readonly manifestId: string;
  readonly kind: Kind;
  readonly flags: Readonly<Record<string, unknown>>;
  readonly pins: Readonly<Record<string, unknown>>;
}

/** A run the server could not read: its sentence, the record, and the reader's own reason. */
export interface UnreadRun extends Place {
  readonly read: false;
  readonly error: string;
  readonly record: string;
  readonly offset: string | null;
  readonly reason: string | null;
}

export type RunRow = ReadRun | UnreadRun;

const READ_ROW = ["root", "name", "run_id", "seed", "manifest_id", "kind", "flags", "pins"];
const UNREAD_ROW = ["root", "name", "error", "record"];
const UNREAD_OPTIONAL = ["offset", "reason"];

export function unreadRun(value: unknown): UnreadRun {
  const r = exact(value, "a run that was not read", UNREAD_ROW, UNREAD_OPTIONAL);
  return {
    read: false,
    root: count(r.root, "a root's position"),
    name: text(r.name, "a run's name"),
    error: text(r.error, "the reason a run was not read"),
    record: text(r.record, "the record a run was not read from"),
    offset: optionalText(r.offset, "a place in a record"),
    reason: optionalText(r.reason, "a reader's reason"),
  };
}

function runRow(value: unknown): RunRow {
  if (Object.hasOwn(object(value, "a run"), "error")) return unreadRun(value);
  const r = exact(value, "a run", READ_ROW);
  return {
    read: true,
    root: count(r.root, "a root's position"),
    name: text(r.name, "a run's name"),
    runId: text(r.run_id, "a run id"),
    seed: integer(r.seed, "a seed"),
    manifestId: text(r.manifest_id, "a manifest id"),
    kind: oneOf(r.kind, KINDS, "a run's kind"),
    flags: settings(r.flags, "a run's recorded settings"),
    pins: settings(r.pins, "a run's pinned settings"),
  };
}

export function evidenceRuns(value: unknown): readonly RunRow[] {
  const answer = exact(value, "the list of runs", ["runs"]);
  return list(answer.runs, "the list of runs").map(runRow);
}

/** The runs read, each kind's together, in the screen's order: never an ablation run first. */
export function byKind(rows: readonly RunRow[]): readonly ReadRun[] {
  const read = rows.filter((row): row is ReadRun => row.read);
  return KINDS.flatMap((kind) => read.filter((row) => row.kind === kind));
}

/** The harness commit a run recorded, or ``null`` when its record names none. */
export function commitOf(run: ReadRun): string | null {
  const harness = run.flags.harness;
  if (typeof harness !== "object" || harness === null) return null;
  const commit = (harness as Record<string, unknown>).commit;
  return typeof commit === "string" ? commit : null;
}

// -- the spend --------------------------------------------------------------------------------

export interface Tokens {
  readonly input: number;
  readonly output: number;
  readonly cacheRead: number;
  readonly cacheCreation: number;
}

const TOKENS = [
  "input_tokens",
  "output_tokens",
  "cache_read_input_tokens",
  "cache_creation_input_tokens",
];

function tokens(value: unknown): Tokens {
  const t = exact(value, "a call's tokens", TOKENS);
  return {
    input: count(t.input_tokens, "input tokens"),
    output: count(t.output_tokens, "output tokens"),
    cacheRead: count(t.cache_read_input_tokens, "cache read tokens"),
    cacheCreation: count(t.cache_creation_input_tokens, "cache creation tokens"),
  };
}

/** A sum the server made of a group's calls; ``lowerBound``: a call in it was not read whole. */
export interface Sum {
  readonly tokens: Tokens;
  readonly usd: string;
  readonly lowerBound: boolean;
}

function sum(value: unknown): Sum {
  const s = exact(value, "a sum of calls", ["tokens", "usd", "lower_bound"]);
  return {
    tokens: tokens(s.tokens),
    usd: text(s.usd, "an exact amount"),
    lowerBound: flag(s.lower_bound, "a lower-bound flag"),
  };
}

/** One priced call, as the cost line holds it. */
export interface PricedCall {
  readonly attribution: string;
  readonly model: string;
  readonly tokens: Tokens;
  readonly usd: string;
  readonly sealBroken: boolean;
  readonly lowerBound: boolean;
}

const CALL = [
  "attribution",
  "model",
  "tokens",
  "cache_writes",
  "usd",
  "binary_usd",
  "agrees",
  "seal_broken",
  "lower_bound",
];

function priced(c: Record<string, unknown>): PricedCall {
  if (c.cache_writes !== null)
    exact(c.cache_writes, "a call's cache writes", ["five_minute", "one_hour"]);
  optionalText(c.binary_usd, "an exact amount");
  if (c.agrees !== null) flag(c.agrees, "whether a call's figures agree");
  return {
    attribution: text(c.attribution, "a call's attribution"),
    model: text(c.model, "a model string"),
    tokens: tokens(c.tokens),
    usd: text(c.usd, "an exact amount"),
    sealBroken: flag(c.seal_broken, "a broken-seal flag"),
    lowerBound: flag(c.lower_bound, "a lower-bound flag"),
  };
}

function pricedCall(value: unknown): PricedCall {
  return priced(exact(value, "a priced call", CALL));
}

/** One session's priced call, with the subtask and attempt it ran for. */
export interface PricedSession extends PricedCall {
  readonly sessionId: string;
  readonly subtaskId: string;
  readonly attempt: number;
  readonly outcome: string;
}

const SESSION = [...CALL, "session_id", "subtask_id", "attempt", "outcome"];

function pricedSession(value: unknown): PricedSession {
  const s = exact(value, "a session's priced call", SESSION);
  return {
    ...priced(s),
    sessionId: text(s.session_id, "a session id"),
    subtaskId: text(s.subtask_id, "a subtask id"),
    attempt: count(s.attempt, "an attempt"),
    outcome: text(s.outcome, "a session's outcome"),
  };
}

/** One role's sessions, each with its call, and their sum: a view. */
export interface RoleSpend {
  readonly role: string;
  readonly sum: Sum;
  readonly sessions: readonly PricedSession[];
}

function roleSpend(value: unknown): RoleSpend {
  const r = exact(value, "a role's spend", ["role", "sum", "sessions"]);
  return {
    role: text(r.role, "a role"),
    sum: sum(r.sum),
    sessions: list(r.sessions, "a role's sessions").map(pricedSession),
  };
}

/** The groups of calls the server sends apart from the roles. */
export const APART = ["decomposition", "review", "routing", "left_over", "unplanned"] as const;
export type ApartGroup = (typeof APART)[number];

/** A group's calls and their sum; ``null`` when the group holds no call. */
export interface Apart {
  readonly sum: Sum | null;
  readonly calls: readonly PricedCall[];
}

function apart(value: unknown): Apart {
  const a = exact(value, "a group of calls", ["sum", "calls"]);
  return {
    sum: a.sum === null ? null : sum(a.sum),
    calls: list(a.calls, "a group's calls").map(pricedCall),
  };
}

/** What the sessions reported against what was priced, by call. */
export interface Reconciliation {
  readonly binaryUsd: string;
  readonly pricedUsd: string;
  readonly differs: readonly string[];
  readonly unread: readonly string[];
  readonly ttlUnread: readonly string[];
  readonly sealBroken: readonly string[];
}

const RECONCILIATION = ["binary_usd", "priced_usd", "differs", "unread", "ttl_unread"];

function reconciliation(value: unknown): Reconciliation | null {
  if (value === null || value === undefined) return null;
  const r = exact(value, "a cost line's reconciliation", RECONCILIATION, ["seal_broken"]);
  return {
    binaryUsd: text(r.binary_usd, "an exact amount"),
    pricedUsd: text(r.priced_usd, "an exact amount"),
    differs: texts(r.differs, "the calls whose figures differ"),
    unread: texts(r.unread, "the calls with no result read"),
    ttlUnread: texts(r.ttl_unread, "the calls with no cache lifetime read"),
    sealBroken: r.seal_broken === undefined ? [] : texts(r.seal_broken, "the broken streams"),
  };
}

export interface Spend {
  readonly source: EvidenceSource;
  readonly line: CostRecord;
  readonly reconciliation: Reconciliation | null;
  /** The server's sentence for what a role's sum is: shown beside every one. */
  readonly view: string;
  readonly roles: readonly RoleSpend[];
  readonly apart: Readonly<Record<ApartGroup, Apart>>;
}

export function evidenceSpend(value: unknown): Spend {
  const s = exact(value, "a run's spend", ["source", "line", "view", "roles", "apart"]);
  const groups = exact(s.apart, "the calls apart from the roles", APART);
  return {
    source: evidenceSource(s.source),
    line: costRecord(s.line),
    reconciliation: reconciliation(object(s.line, "a cost line").reconciliation),
    view: text(s.view, "what a role's sum is"),
    roles: list(s.roles, "the roles' spend").map(roleSpend),
    apart: {
      decomposition: apart(groups.decomposition),
      review: apart(groups.review),
      routing: apart(groups.routing),
      left_over: apart(groups.left_over),
      unplanned: apart(groups.unplanned),
    },
  };
}

/** The newest of the server's price sheet dates, or ``null`` when it holds none. */
export function newestDate(dates: readonly string[]): string | null {
  return [...dates].sort().at(-1) ?? null;
}

// -- the comparison ---------------------------------------------------------------------------

/** How each of a run's numbers in a comparison is held, and so shown. */
type Held = "text" | "optional" | "count" | "flag" | "tokens" | "seconds";

/** A run's numbers in a comparison, field by field, as the comparison names them. */
export const RUN_NUMBERS = {
  manifest_id: "text",
  run_id: "text",
  gate_mode: "text",
  auth: "text",
  effort: "text",
  max_output_tokens: "count",
  thinking_display: "text",
  escalation_backend: "optional",
  queue_decisions: "text",
  design_review: "text",
  reviewers: "text",
  skills: "text",
  hooks: "text",
  ablation: "flag",
  harness_commit: "optional",
  harness_clean: "flag",
  reportable: "flag",
  tokens: "tokens",
  sessions: "count",
  attempts_merged: "count",
  attempts_rejected: "count",
  subtasks_escalated: "count",
  integration: "optional",
  wall_clock_s: "seconds",
} as const satisfies Readonly<Record<string, Held>>;
export type NumberField = keyof typeof RUN_NUMBERS;
export const NUMBER_FIELDS = Object.keys(RUN_NUMBERS) as readonly NumberField[];

/** One of a run's numbers: text, a count, a flag, tokens by kind, seconds, or not recorded. */
export type Cell = string | number | boolean | null | Readonly<Record<string, number>>;

function cell(value: unknown, held: Held, what: string): Cell {
  switch (held) {
    case "text":
      return text(value, what);
    case "optional":
      return optionalText(value, what);
    case "count":
      return count(value, what);
    case "flag":
      return flag(value, what);
    case "tokens":
      return Object.fromEntries(
        Object.entries(object(value, what)).map(([key, n]) => [key, count(n, what)]),
      );
    case "seconds":
      if (typeof value !== "number" || !Number.isFinite(value)) throw new ShapeError(what);
      return value;
  }
}

export type RunNumbers = Readonly<Record<NumberField, Cell>>;

function runNumbers(value: unknown): RunNumbers {
  const r = exact(value, "a run's numbers", NUMBER_FIELDS);
  const numbers: Partial<Record<NumberField, Cell>> = {};
  for (const field of NUMBER_FIELDS) numbers[field] = cell(r[field], RUN_NUMBERS[field], field);
  return numbers as RunNumbers;
}

export interface Comparison {
  readonly a: EvidenceSource;
  readonly b: EvidenceSource;
  readonly baseline: RunNumbers;
  readonly candidate: RunNumbers;
  readonly differsIn: readonly string[];
}

export function evidenceComparison(value: unknown): Comparison {
  const c = exact(value, "a comparison", ["a", "b", "comparison"]);
  const side = exact(c.comparison, "a side by side", ["baseline", "candidate", "differs_in"]);
  return {
    a: evidenceSource(c.a),
    b: evidenceSource(c.b),
    baseline: runNumbers(side.baseline),
    candidate: runNumbers(side.candidate),
    differsIn: texts(side.differs_in, "the settings that differ"),
  };
}

/** The settings a refused comparison names, by path, or ``null`` for any other refusal. */
export function driftedOf(refusal: Refusal): readonly string[] | null {
  const drifted = refusal.context.drifted;
  if (refusal.status !== 422 || drifted === undefined) return null;
  const paths = drifted.split(",").filter((path) => path !== "");
  return paths.length === 0 ? null : paths;
}

// -- the catches ------------------------------------------------------------------------------

export interface CatchRow {
  readonly gateMode: string;
  /** The check's number, or ``null`` for the row over every check. */
  readonly check: number | null;
  readonly name: string;
  readonly checksRun: number;
  readonly blockingFailures: number;
  readonly reviewerHadPassed: number;
  readonly reviewerHadFailed: number;
  readonly noReview: number;
  readonly artefactsCaught: number;
  readonly caughtAfterReviewerPassed: number;
}

const CATCH_ROW = [
  "gate_mode",
  "check",
  "name",
  "checks_run",
  "blocking_failures",
  "reviewer_had_passed",
  "reviewer_had_failed",
  "no_review",
  "artefacts_caught",
  "caught_after_reviewer_passed",
];

function catchRow(value: unknown): CatchRow {
  const r = exact(value, "a catch count", CATCH_ROW);
  return {
    gateMode: text(r.gate_mode, "a gate mode"),
    check: r.check === null ? null : count(r.check, "a check's number"),
    name: text(r.name, "a check's name"),
    checksRun: count(r.checks_run, "a count of checks run"),
    blockingFailures: count(r.blocking_failures, "a count of blocking failures"),
    reviewerHadPassed: count(r.reviewer_had_passed, "a count"),
    reviewerHadFailed: count(r.reviewer_had_failed, "a count"),
    noReview: count(r.no_review, "a count"),
    artefactsCaught: count(r.artefacts_caught, "a count of artefacts caught"),
    caughtAfterReviewerPassed: count(r.caught_after_reviewer_passed, "a count"),
  };
}

/** One kind's count: over that kind's runs alone, never added to another kind's. */
export interface KindCatches {
  readonly kind: Kind;
  readonly runs: readonly EvidenceSource[];
  readonly rows: readonly CatchRow[];
}

export interface Catches {
  readonly kinds: readonly KindCatches[];
  readonly unread: readonly UnreadRun[];
}

function kindCatches(value: unknown, kind: Kind): KindCatches {
  const k = exact(value, "a kind's catch count", ["kind", "runs", "rows"]);
  if (k.kind !== kind) throw new ShapeError("the kinds in their order");
  return {
    kind,
    runs: list(k.runs, "the runs a kind counted").map(evidenceSource),
    rows: list(k.rows, "a kind's catch counts").map(catchRow),
  };
}

export function evidenceCatches(value: unknown): Catches {
  const c = exact(value, "the catch count", ["kinds", "unread"]);
  const kinds = list(c.kinds, "the kinds of run");
  if (kinds.length !== KINDS.length) throw new ShapeError("the kinds in their order");
  return {
    kinds: KINDS.map((kind, i) => kindCatches(kinds[i], kind)),
    unread: list(c.unread, "the runs not counted").map(unreadRun),
  };
}
