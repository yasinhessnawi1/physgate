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
export const APART = ["decomposition", "review", "routing", "left_over"] as const;
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
  /** What the comparison says beside its numbers: a tier version seen since a run, in words. */
  readonly notes: readonly string[];
}

export function evidenceComparison(value: unknown): Comparison {
  const c = exact(value, "a comparison", ["a", "b", "comparison"]);
  const side = exact(
    c.comparison,
    "a side by side",
    ["baseline", "candidate", "differs_in"],
    ["notes"],
  );
  return {
    a: evidenceSource(c.a),
    b: evidenceSource(c.b),
    baseline: runNumbers(side.baseline),
    candidate: runNumbers(side.candidate),
    differsIn: texts(side.differs_in, "the settings that differ"),
    notes: Object.hasOwn(side, "notes") ? notesOf(side.notes) : [],
  };
}

/** The longest note a comparison's server writes is far shorter: a longer one is refused. */
export const MOST_NOTE = 500;

function notesOf(value: unknown): readonly string[] {
  const notes = texts(value, "the comparison's notes");
  if (notes.some((note) => note.length > MOST_NOTE)) throw new ShapeError("a comparison's note");
  return notes;
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
  /** The ablation arms of the runs the row counts, as ``reviewers: off``; empty for a full
   * harness, whose row names none. */
  readonly arms: string;
}

/** The arms a row names when its runs dropped a component; a full harness's row names none. */
const CATCH_ARMS = ["reviewers", "skills", "hooks"];

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
  const r = exact(value, "a catch count", CATCH_ROW, CATCH_ARMS);
  const arms = CATCH_ARMS.filter((key) => Object.hasOwn(r, key))
    .map((key) => `${key}: ${text(r[key], "an ablation arm")}`)
    .join(", ");
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
    arms,
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

// -- the gap trend ----------------------------------------------------------------------------

export const GAPS_ROUTE = "/api/evidence/gaps";

/** The roles a trend is published for, in the order the server sends them. */
export const TREND_ROLES = ["control", "firmware"] as const;
export type TrendRole = (typeof TREND_ROLES)[number];

/** A tier's rate as the reader wrote it, and how many of its fails were unscored or flaky. */
export interface TierCount {
  readonly rate: string;
  readonly unscored: number;
  readonly flaky: number;
}

/** A gap as a fraction of a rate, its interval or none, and the reader's words for both. */
export interface Gap {
  readonly gap: number;
  readonly interval: readonly [number, number] | null;
  readonly words: string;
  readonly label: string | null;
}

export interface GapNumbers {
  readonly visible: TierCount;
  readonly validation: TierCount | null;
  readonly heldOut: TierCount;
  readonly rewardHacking: Gap;
  readonly optimiserOverfit: Gap | null;
}

/** A trend line as the route serves it: its numbers, or why they are withheld. */
export interface GapLine {
  readonly week: string;
  readonly version: string;
  readonly measurements: number;
  readonly numbers: GapNumbers | null;
  readonly unverified: string | null;
  readonly exposedSince: string | null;
}

/** An ISO week of the trend: its lines, or none, and then it is missing. */
export interface GapWeek {
  readonly week: string;
  readonly lines: readonly GapLine[];
  readonly missing: boolean;
}

/** A role's trend: none published, its weeks as read, or why it is not shown. */
export type RoleTrend =
  | { readonly role: TrendRole; readonly state: "none" }
  | {
      readonly role: TrendRole;
      readonly state: "read";
      readonly readAt: string;
      readonly weeks: readonly GapWeek[];
    }
  | {
      readonly role: TrendRole;
      readonly state: "refused";
      readonly error: string;
      readonly reason: string;
      readonly readAt: string | null;
    };

export interface GapTrend {
  readonly roles: readonly RoleTrend[];
}

const WEEK = /^\d{4}-W\d{2}$/;
const VERSION = /^[0-9a-f]{64}$/;

function matching(value: unknown, pattern: RegExp, what: string): string {
  const found = text(value, what);
  if (!pattern.test(found)) throw new ShapeError(what);
  return found;
}

function finite(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new ShapeError(what);
  return value;
}

/** What the route serves of a tier's count: only what the page shows. */
const TIER_COUNT = ["rate", "unscored", "flaky"];

function tierCount(value: unknown, what: string): TierCount {
  const c = exact(value, what, TIER_COUNT);
  return {
    rate: text(c.rate, what),
    unscored: count(c.unscored, what),
    flaky: count(c.flaky, what),
  };
}

function gap(value: unknown, what: string): Gap {
  const g = exact(value, what, ["gap", "interval", "words", "label"]);
  let interval: readonly [number, number] | null = null;
  if (g.interval !== null) {
    const ends = list(g.interval, what);
    if (ends.length !== 2) throw new ShapeError(what);
    interval = [finite(ends[0], what), finite(ends[1], what)];
  }
  return {
    gap: finite(g.gap, what),
    interval,
    words: text(g.words, what),
    label: optionalText(g.label, what),
  };
}

const NUMBERS = ["visible", "validation", "held_out", "reward_hacking", "optimiser_overfit"];

function gapNumbers(value: unknown): GapNumbers {
  const n = exact(value, "a line's numbers", NUMBERS);
  return {
    visible: tierCount(n.visible, "the visible tier's count"),
    validation: n.validation === null ? null : tierCount(n.validation, "the validation count"),
    heldOut: tierCount(n.held_out, "the held-out tier's count"),
    rewardHacking: gap(n.reward_hacking, "the reward-hacking gap"),
    optimiserOverfit:
      n.optimiser_overfit === null ? null : gap(n.optimiser_overfit, "the optimiser-overfit gap"),
  };
}

/** What the route serves of a trend line: only what the page shows, no run set's id. */
const LINE = ["week", "version", "measurements", "numbers", "unverified", "exposed_since"];

function gapLine(value: unknown): GapLine {
  const l = exact(value, "a trend line", LINE);
  const numbers = l.numbers === null ? null : gapNumbers(l.numbers);
  const unverified = optionalText(l.unverified, "why a line's numbers are withheld");
  // The reader gives a line's numbers, or says why it does not: never both, never neither.
  if ((numbers === null) === (unverified === null)) throw new ShapeError("a line's numbers");
  return {
    week: matching(l.week, WEEK, "a line's week"),
    version: matching(l.version, VERSION, "a task version"),
    measurements: count(l.measurements, "a version's measurement count"),
    numbers,
    unverified,
    exposedSince: optionalText(l.exposed_since, "a version seen since"),
  };
}

function gapWeek(value: unknown): GapWeek {
  const w = exact(value, "a week of the trend", ["week", "lines", "missing"]);
  const week = matching(w.week, WEEK, "a week of the trend");
  const lines = list(w.lines, "a week's lines").map(gapLine);
  const missing = flag(w.missing, "whether a week is missing");
  if (missing !== (lines.length === 0) || lines.some((line) => line.week !== week))
    throw new ShapeError("a week of the trend");
  return { week, lines, missing };
}

function roleTrend(value: unknown): RoleTrend {
  const r = object(value, "a role's trend");
  const role = oneOf(r.role, TREND_ROLES, "a role");
  switch (r.state) {
    case "none":
      exact(value, "a role with no trend", ["role", "state"]);
      return { role, state: "none" };
    case "read": {
      const read = exact(value, "a role's trend", ["role", "state", "read_at", "weeks"]);
      return {
        role,
        state: "read",
        readAt: text(read.read_at, "when the trend was read"),
        weeks: list(read.weeks, "the trend's weeks").map(gapWeek),
      };
    }
    case "refused": {
      const no = exact(value, "a refused trend", ["role", "state", "error", "reason", "read_at"]);
      return {
        role,
        state: "refused",
        error: text(no.error, "why a trend is not shown"),
        reason: text(no.reason, "a reader's reason"),
        readAt: optionalText(no.read_at, "when the trend was read"),
      };
    }
    default:
      throw new ShapeError("a role's trend");
  }
}

export function evidenceGaps(value: unknown): GapTrend {
  const answer = exact(value, "the gap trend", ["roles"]);
  const roles = list(answer.roles, "the roles' trends").map(roleTrend);
  if (new Set(roles.map((r) => r.role)).size !== roles.length)
    throw new ShapeError("each role once");
  return { roles };
}

// -- the tier versions ----------------------------------------------------------------------

export const TIERS_ROUTE = "/api/evidence/tiers";

/** The words a version's exposure, its state and its check's source are sent in, and no other. */
export const EXPOSURES = ["none", "exposed", "exposed_unchecked"] as const;
export type Exposure = (typeof EXPOSURES)[number];
export const VERSION_STATES = ["fresh", "stale"] as const;
export type VersionState = (typeof VERSION_STATES)[number];
export const CHECK_SOURCES = ["check", "imported"] as const;
export type CheckSource = (typeof CHECK_SOURCES)[number];
/** Why a version's check record is refused, as the server sends it. */
export const CHECK_REFUSALS = [
  "check_record_changed",
  "check_record_invalid",
  "check_record_not_the_version",
  "check_record_unreadable",
  "check_record_unsynced",
  "check_record_unwritten",
] as const;
export type CheckRefusal = (typeof CHECK_REFUSALS)[number];
/** The most tasks a tier's or a check's count may say: the publisher's own bound, generous. */
export const MOST_TASKS = 10_000;
/** The one form the time a status was read is written in: UTC, to the second. */
export const READ_AT_FORM = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** The three tiers' task counts: the tiers' sizes, never a result. */
export interface TierCounts {
  readonly visible: number;
  readonly validation: number;
  readonly heldOut: number;
}

/** The blind check: none recorded, its counts and source, or why its record is refused. */
export type BlindCheck =
  | { readonly state: "none" }
  | {
      readonly state: "read";
      readonly tasks: number;
      readonly allYes: number;
      readonly leftOut: number;
      readonly source: CheckSource;
    }
  | { readonly state: "refused"; readonly refused: CheckRefusal };

/** A role's current tier version: none published, as published, or why it is not shown. */
export type RoleTiers =
  | { readonly role: TrendRole; readonly state: "none" }
  | {
      readonly role: TrendRole;
      readonly state: "read";
      readonly readAt: string;
      readonly version: string;
      readonly counts: TierCounts;
      readonly check: BlindCheck;
      readonly exposure: Exposure;
      readonly versionState: VersionState;
      readonly measured: boolean;
    }
  | {
      readonly role: TrendRole;
      readonly state: "refused";
      readonly error: string;
      readonly reason: string;
      readonly readAt: string | null;
    };

export interface TierStatus {
  readonly roles: readonly RoleTiers[];
}

/** A count of tasks: a whole number from nought to the publisher's bound. */
function tasksCount(value: unknown, what: string): number {
  const found = count(value, what);
  if (found > MOST_TASKS) throw new ShapeError(what);
  return found;
}

/** When a status was read: a time in its one form that a calendar holds, and nothing else. */
function readAt(value: unknown, what: string): string {
  const found = matching(value, READ_AT_FORM, what);
  const at = Date.parse(found);
  if (Number.isNaN(at) || `${new Date(at).toISOString().slice(0, 19)}Z` !== found)
    throw new ShapeError(what);
  return found;
}

function tierCounts(value: unknown): TierCounts {
  const c = exact(value, "the tiers' task counts", ["visible", "validation", "held_out"]);
  return {
    visible: tasksCount(c.visible, "the visible tier's task count"),
    validation: tasksCount(c.validation, "the validation tier's task count"),
    heldOut: tasksCount(c.held_out, "the held-out tier's task count"),
  };
}

function blindCheck(value: unknown, heldOut: number): BlindCheck {
  if (value === null) return { state: "none" };
  const record = object(value, "the blind check");
  if (Object.hasOwn(record, "refused")) {
    const no = exact(value, "a refused blind check", ["refused"]);
    return { state: "refused", refused: oneOf(no.refused, CHECK_REFUSALS, "why it is refused") };
  }
  const c = exact(value, "the blind check", ["tasks", "all_yes", "left_out", "source"]);
  const tasks = tasksCount(c.tasks, "the tasks checked");
  const allYes = tasksCount(c.all_yes, "the tasks with every answer yes");
  const leftOut = tasksCount(c.left_out, "the tasks left out");
  // The check reads every held-out task, and each is either kept or left out.
  if (tasks === 0 || allYes + leftOut !== tasks || tasks !== heldOut)
    throw new ShapeError("the blind check's counts");
  return {
    state: "read",
    tasks,
    allYes,
    leftOut,
    source: oneOf(c.source, CHECK_SOURCES, "where the check's answer came from"),
  };
}

const TIERS_READ = [
  "role",
  "state",
  "read_at",
  "version",
  "counts",
  "check",
  "exposure",
  "version_state",
  "measured",
];

function roleTiers(value: unknown): RoleTiers {
  const r = object(value, "a role's tier version");
  const role = oneOf(r.role, TREND_ROLES, "a role");
  switch (r.state) {
    case "none":
      exact(value, "a role with no tier status", ["role", "state"]);
      return { role, state: "none" };
    case "read": {
      const read = exact(value, "a role's tier version", TIERS_READ);
      const counts = tierCounts(read.counts);
      const exposure = oneOf(read.exposure, EXPOSURES, "a version's exposure");
      const versionState = oneOf(read.version_state, VERSION_STATES, "a version's state");
      // An exposed version is stale: a record that says otherwise is not the server's.
      if (exposure !== "none" && versionState !== "stale")
        throw new ShapeError("a version's exposure and state");
      return {
        role,
        state: "read",
        readAt: readAt(read.read_at, "when the status was read"),
        version: matching(read.version, VERSION, "a tier version"),
        counts,
        check: blindCheck(read.check, counts.heldOut),
        exposure,
        versionState,
        measured: flag(read.measured, "whether the version was measured"),
      };
    }
    case "refused": {
      const no = exact(value, "a refused tier status", [
        "role",
        "state",
        "error",
        "reason",
        "read_at",
      ]);
      return {
        role,
        state: "refused",
        error: text(no.error, "why a tier status is not shown"),
        reason: text(no.reason, "a reason"),
        readAt: no.read_at === null ? null : readAt(no.read_at, "when the status was read"),
      };
    }
    default:
      throw new ShapeError("a role's tier version");
  }
}

export function evidenceTiers(value: unknown): TierStatus {
  const answer = exact(value, "the tier versions", ["roles"]);
  const roles = list(answer.roles, "the roles' tier versions").map(roleTiers);
  if (new Set(roles.map((r) => r.role)).size !== roles.length)
    throw new ShapeError("each role once");
  return { roles };
}
