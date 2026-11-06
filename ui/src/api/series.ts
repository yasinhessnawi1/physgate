/**
 * A run's simulation records, as the server sends them, with a guard for each answer.
 *
 * **The guard checks only what the screen draws.** A column needs a unit and finite numbers of
 * one length with its x; a value needs its unit and is a number or a decimal numeral (an integer
 * larger than a browser's number holds exactly arrives as its numeral); an axis is time or
 * frequency; an id is text. A field the screen does not draw is never read, so a field the
 * server adds later cannot empty the screen.
 *
 * **Open words stay open.** Why an attempt was refused, a check's outcome, a gate record's
 * outcome and mode, the kind of a set-aside file and the kind of a refused record are shown as
 * written when the screen has no words for them: never refused, and never drawn as a verdict.
 *
 * **A malformed row is refused alone.** An attempt, a check, a record or a set-aside entry that
 * is not the shape the screen draws becomes a row that says it could not be read, and why; the
 * rest of the answer is still shown. Only an answer with no list of attempts or records at all is
 * refused whole.
 */
import { requireQuantity, type Quantity } from "../design/quantity";
import { count, flag, list, object, optionalText, text } from "./check";
import { ShapeError } from "./client";

/**
 * The traces a loop's frequency response is read from, as the harness's extractors name them.
 * A test holds both to the harness's own names.
 */
export const LOOP_MAGNITUDE = "loop_magnitude";
export const LOOP_PHASE = "loop_phase";

/** The extractors a graph quantity can be read off a record with; a test holds them to the schema. */
export const EXTRACTORS = [
  "phase_margin",
  "gain_crossover_frequency",
  "gain_margin_upper",
  "gain_margin_lower",
  "stability_margin",
  "sensitivity_peak",
  "complementary_sensitivity_peak",
  "delay_margin",
  "max",
  "min",
  "max_abs",
  "final",
] as const;
export type Extractor = (typeof EXTRACTORS)[number];

/** The run's listing: every attempt one of whose sessions ended, from the event log alone. */
export function seriesRoute(base: string): string {
  return `${base}/series`;
}

/** One attempt's records, each read through its seal. */
export function attemptRoute(base: string, subtask: string, attempt: number): string {
  return `${base}/series/${encodeURIComponent(subtask)}/${String(attempt)}`;
}

/** One record, as the very bytes its seal names. */
export function recordRoute(
  base: string,
  subtask: string,
  attempt: number,
  record: string,
): string {
  return `${attemptRoute(base, subtask, attempt)}/${encodeURIComponent(record)}`;
}

/** A row the page could not read: shown as such, in its place, never dropped and never mended. */
export interface Unread {
  readonly kind: "unread";
  /** Why, in the guard's words. */
  readonly error: string;
}

/** ``read(raw)``, or the row that says why it could not be read. */
function rowOf<T>(raw: unknown, read: (raw: unknown) => T): T | Unread {
  try {
    return read(raw);
  } catch (error) {
    if (error instanceof Error) return { kind: "unread", error: error.message };
    throw error;
  }
}

/** A value the screen draws: a value and its unit, the value a number or a decimal numeral. */
function quantity(value: unknown, unit: unknown): Quantity {
  return requireQuantity({ value, unit });
}

/** A recorded number: finite, or a decimal numeral exactly as the server sent it. */
function figure(value: unknown, what: string): number | string {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && /^-?(0|[1-9][0-9]*)(\.[0-9]+)?$/.test(value)) return value;
  throw new ShapeError(what);
}

function nonEmpty(value: unknown, what: string): string {
  const found = text(value, what);
  if (found.trim() === "") throw new ShapeError(what);
  return found;
}

function axis(value: unknown): "time" | "frequency" {
  if (value === "time" || value === "frequency") return value;
  throw new ShapeError("a record's axis, time or frequency");
}

// -- the run's listing ---------------------------------------------------------------------------

/** One session of an attempt that ended, with the commit its attempt made, if any. */
export interface SessionEnd {
  readonly sessionId: string;
  /** As written: ``completed`` or ``infrastructure`` today. */
  readonly outcome: string;
  readonly attemptCommit: string | null;
}

/** A record the attempt's sessions sealed, and the session whose end sealed it. */
export interface SealedName {
  readonly kind: "sealed";
  readonly recordId: string;
  readonly sessionId: string;
}

/** A record an earlier session sealed and a later one recorded again. */
export interface Superseded {
  readonly kind: "superseded";
  readonly recordId: string;
  readonly sessionId: string;
}

/** A file a session's end did not seal, with the collector's reason. */
export interface SetAside {
  readonly kind: "set-aside";
  readonly sessionId: string;
  /** As written: ``refused`` or ``discarded`` today. */
  readonly how: string;
  /** The file's name, as data. */
  readonly name: string;
  readonly reason: string;
}

/** One gate record that names a checked quantity, as the gate wrote it. */
export interface GateEntry {
  readonly seq: number;
  readonly check: number;
  readonly name: string;
  /** As written: pass, fail, warn or unchecked today. */
  readonly outcome: string;
  /** As written: on or observe today. */
  readonly gateMode: string;
  readonly blocking: boolean;
  readonly expected: string | null;
  readonly low: Quantity | null;
  readonly high: Quantity | null;
}

/** One graph quantity held to the record it names, as the change check recorded it. */
export interface SeriesCheck {
  readonly kind: "check";
  readonly nodeId: string;
  readonly quantity: string;
  readonly recordId: string;
  /** As written; an extractor the screen has no words for reads as written. */
  readonly extract: string;
  readonly trace: string | null;
  readonly sessionId: string | null;
  readonly declared: Quantity;
  /** ``null`` when nothing could be read off the record. */
  readonly read: Quantity | null;
  /** As written: agrees, differs or unreadable today. */
  readonly outcome: string;
  readonly reason: string | null;
  /** The gate records that name the quantity, in log order, or the words for why there are none. */
  readonly gate: readonly GateEntry[] | string;
}

export interface ListedAttempt {
  readonly kind: "attempt";
  readonly subtaskId: string;
  readonly attempt: number;
  /** The role the subtask was planned for, or ``null`` when the log names none. */
  readonly ownerRole: string | null;
  readonly merged: boolean;
  readonly rejected: boolean;
  /** As written; ``null`` when the attempt's last change check refused nothing. */
  readonly refusedBy: string | null;
  readonly sessions: readonly SessionEnd[];
  readonly records: readonly (SealedName | Unread)[];
  readonly superseded: readonly (Superseded | Unread)[];
  readonly setAside: readonly (SetAside | Unread)[];
  readonly checks: readonly (SeriesCheck | Unread)[];
}

export interface SeriesListing {
  /** The relative tolerance a quantity is held to its record within, as the harness writes it. */
  readonly tolerance: string;
  readonly attempts: readonly (ListedAttempt | Unread)[];
}

function sessionEnd(raw: unknown): SessionEnd {
  const session = object(raw, "a session's end");
  return {
    sessionId: text(session.session_id, "a session id"),
    outcome: text(session.outcome, "how a session ended"),
    attemptCommit: optionalText(session.attempt_commit, "an attempt commit"),
  };
}

function sealedName(raw: unknown): SealedName {
  const row = object(raw, "a sealed record");
  return {
    kind: "sealed",
    recordId: text(row.record_id, "a record id"),
    sessionId: text(row.session_id, "a session id"),
  };
}

function superseded(raw: unknown): Superseded {
  const row = object(raw, "a superseded record");
  return {
    kind: "superseded",
    recordId: text(row.record_id, "a record id"),
    sessionId: text(row.session_id, "a session id"),
  };
}

function setAside(raw: unknown): SetAside {
  const row = object(raw, "a file set aside");
  return {
    kind: "set-aside",
    sessionId: text(row.session_id, "a session id"),
    how: text(row.kind, "how a file was set aside"),
    name: text(row.name, "a file's name"),
    reason: text(row.reason, "why a file was set aside"),
  };
}

function bound(value: unknown, what: string): Quantity | null {
  if (value === null || value === undefined) return null;
  const given = object(value, what);
  return quantity(given.value, given.unit);
}

function gateEntry(raw: unknown): GateEntry {
  const entry = object(raw, "a gate record");
  return {
    seq: count(entry.seq, "a gate line's sequence number"),
    check: count(entry.check, "a check's number"),
    name: text(entry.name, "a check's name"),
    outcome: text(entry.outcome, "a check's outcome"),
    gateMode: text(entry.gate_mode, "a gate mode"),
    blocking: flag(entry.blocking, "whether a check blocks"),
    expected: optionalText(entry.expected, "what a check expected"),
    low: bound(entry.low, "a range's low end"),
    high: bound(entry.high, "a range's high end"),
  };
}

function seriesCheck(raw: unknown): SeriesCheck {
  const check = object(raw, "a checked quantity");
  const readValue = check.read_value;
  const gate = check.gate;
  return {
    kind: "check",
    nodeId: text(check.node_id, "a node id"),
    quantity: text(check.quantity, "a quantity's name"),
    recordId: text(check.record_id, "a record id"),
    extract: text(check.extract, "an extractor"),
    trace: optionalText(check.trace, "a trace's name"),
    sessionId: optionalText(check.session_id, "a session id"),
    declared: quantity(check.declared_value, check.declared_unit),
    read:
      readValue === null || readValue === undefined ? null : quantity(readValue, check.read_unit),
    outcome: text(check.outcome, "a check's outcome"),
    reason: optionalText(check.reason, "why a quantity could not be read"),
    gate: typeof gate === "string" ? gate : list(gate, "what the gate said").map(gateEntry),
  };
}

function listedAttempt(raw: unknown): ListedAttempt {
  const entry = object(raw, "an attempt");
  const attempt = count(entry.attempt, "an attempt number");
  if (attempt < 1) throw new ShapeError("an attempt number");
  return {
    kind: "attempt",
    subtaskId: text(entry.subtask_id, "a subtask id"),
    attempt,
    ownerRole: optionalText(entry.owner_role, "a role"),
    merged: flag(entry.merged, "whether an attempt merged"),
    rejected: flag(entry.rejected, "whether an attempt was rejected"),
    refusedBy: optionalText(entry.refused_by, "what refused an attempt"),
    sessions: list(entry.sessions, "an attempt's sessions").map(sessionEnd),
    records: list(entry.records, "an attempt's records").map((r) => rowOf(r, sealedName)),
    superseded: list(entry.superseded, "an attempt's superseded records").map((r) =>
      rowOf(r, superseded),
    ),
    setAside: list(entry.set_aside, "an attempt's files set aside").map((r) => rowOf(r, setAside)),
    checks: list(entry.checks, "an attempt's checked quantities").map((r) => rowOf(r, seriesCheck)),
  };
}

/** The run's listing, every attempt and every row held alone. */
export function seriesListing(value: unknown): SeriesListing {
  const answer = object(value, "a run's simulation listing");
  return {
    tolerance: text(answer.tolerance, "a tolerance"),
    attempts: list(answer.attempts, "a list of attempts").map((a) => rowOf(a, listedAttempt)),
  };
}

// -- one attempt's records -------------------------------------------------------------------------

/** One column of a record as the review's listing summarises it. */
export interface ColumnSummary {
  readonly name: string;
  readonly unit: string;
  readonly samples: number;
  readonly first: number | string;
  readonly last: number | string;
  readonly smallest: number | string;
  readonly largest: number | string;
}

export interface CodeFile {
  readonly path: string;
  readonly sha256: string;
  /** The file's git blob id, sealed with the record; ``null`` when none was recorded. */
  readonly blob: string | null;
}

/** A record read as sealed: what it is, how it was produced, and each column's summary. */
export interface ShownRecord {
  readonly kind: "shown";
  readonly recordId: string;
  readonly sessionId: string;
  readonly sha256: string;
  readonly length: number;
  /** The role's own words for the record. */
  readonly title: string;
  readonly group: string | null;
  readonly axis: "time" | "frequency";
  /** A frequency record holding the loop's two traces, drawn as the loop's frequency response. */
  readonly loop: boolean;
  readonly x: ColumnSummary;
  readonly traces: readonly ColumnSummary[];
  readonly inputs: readonly (readonly [string, Quantity])[];
  readonly script: CodeFile;
  readonly loaded: readonly CodeFile[];
  /** Files of the interpreter's own installation the producing process loaded. */
  readonly environment: readonly { readonly path: string; readonly sha256: string }[];
  readonly attemptCommit: string | null;
}

/** A sealed record the server would not serve as sealed: why, its seal, and what it found. */
export interface RefusedRecord {
  readonly kind: "refused";
  readonly recordId: string;
  readonly sessionId: string;
  /** Where the record lies in the run, relative to it. */
  readonly record: string;
  /** As written: ``seal`` or ``format`` today. */
  readonly refused: string;
  readonly error: string;
  readonly sealedSha256: string;
  readonly sealedLength: number;
  readonly foundSha256: string | null;
  readonly foundLength: number | null;
}

/** A row of the attempt's answer the page could not read, by its record id where it has one. */
export interface UnreadRecord extends Unread {
  readonly recordId: string | null;
}

export type AttemptRecord = ShownRecord | RefusedRecord | UnreadRecord;

export interface AttemptRecords {
  readonly subtaskId: string;
  readonly attempt: number;
  readonly records: readonly AttemptRecord[];
}

function columnSummary(raw: unknown): ColumnSummary {
  const column = object(raw, "a column's summary");
  return {
    name: text(column.name, "a column's name"),
    unit: nonEmpty(column.unit, "a column's unit"),
    samples: count(column.samples, "a sample count"),
    first: figure(column.first, "a column's first value"),
    last: figure(column.last, "a column's last value"),
    smallest: figure(column.smallest, "a column's smallest value"),
    largest: figure(column.largest, "a column's largest value"),
  };
}

function codeFile(raw: unknown): CodeFile {
  const file = object(raw, "a file of code");
  return {
    path: text(file.path, "a file's path"),
    sha256: text(file.sha256, "a file's digest"),
    blob: optionalText(file.blob, "a file's blob id"),
  };
}

function shownRecord(row: Record<string, unknown>): ShownRecord {
  const x = columnSummary(row.x);
  const traces = list(row.traces, "a record's traces").map(columnSummary);
  if (traces.length === 0) throw new ShapeError("a record with a trace");
  for (const trace of traces)
    if (trace.samples !== x.samples) throw new ShapeError("a trace with one value per x");
  const producer = object(row.producer, "how a record was produced");
  return {
    kind: "shown",
    recordId: text(row.record_id, "a record id"),
    sessionId: text(row.session_id, "a session id"),
    sha256: text(row.sha256, "a record's digest"),
    length: count(row.length, "a record's length"),
    title: text(row.title, "a record's title"),
    group: optionalText(row.group, "a record's group"),
    axis: axis(row.axis),
    loop: flag(row.loop, "whether a record is a loop's"),
    x,
    traces,
    inputs: Object.entries(object(row.inputs, "a record's inputs")).map(
      ([name, given]): readonly [string, Quantity] => {
        const pair = object(given, "an input");
        return [name, quantity(pair.value, pair.unit)];
      },
    ),
    script: codeFile(producer.script),
    loaded: list(producer.loaded, "the code a record's script loaded").map(codeFile),
    environment: list(row.environment, "the interpreter's files").map((raw) => {
      const file = object(raw, "an interpreter's file");
      return { path: text(file.path, "a file's path"), sha256: text(file.sha256, "a digest") };
    }),
    attemptCommit: optionalText(row.attempt_commit, "an attempt commit"),
  };
}

function refusedRecord(row: Record<string, unknown>): RefusedRecord {
  return {
    kind: "refused",
    recordId: text(row.record_id, "a record id"),
    sessionId: text(row.session_id, "a session id"),
    record: text(row.record, "a record's place in the run"),
    refused: text(row.refused, "why a record was refused"),
    error: text(row.error, "the reader's reason"),
    sealedSha256: text(row.sealed_sha256, "a sealed digest"),
    sealedLength: count(row.sealed_length, "a sealed length"),
    foundSha256: optionalText(row.found_sha256, "a digest found"),
    foundLength:
      row.found_length === undefined || row.found_length === null
        ? null
        : count(row.found_length, "a length found"),
  };
}

function attemptRecord(raw: unknown): AttemptRecord {
  const id =
    typeof raw === "object" &&
    raw !== null &&
    typeof (raw as { record_id?: unknown }).record_id === "string"
      ? (raw as { record_id: string }).record_id
      : null;
  try {
    const row = object(raw, "a record");
    return row.refused === undefined ? shownRecord(row) : refusedRecord(row);
  } catch (error) {
    if (error instanceof Error) return { kind: "unread", recordId: id, error: error.message };
    throw error;
  }
}

/** One attempt's records, each held alone. */
export function attemptRecords(value: unknown): AttemptRecords {
  const answer = object(value, "an attempt's records");
  const attempt = count(answer.attempt, "an attempt number");
  return {
    subtaskId: text(answer.subtask_id, "a subtask id"),
    attempt,
    records: list(answer.records, "a list of records").map(attemptRecord),
  };
}

// -- one record's samples ---------------------------------------------------------------------------

/** One column of a record: its name, its unit and every value, as sealed. */
export interface Column {
  readonly name: string;
  readonly unit: string;
  readonly values: readonly number[];
}

/** What the screen draws of a record's sealed bytes: its axis and its columns. */
export interface RecordSamples {
  readonly axis: "time" | "frequency";
  readonly x: Column;
  readonly traces: readonly Column[];
}

function column(raw: unknown, what: string): Column {
  const given = object(raw, what);
  const values = list(given.values, `${what}'s values`).map((v) => {
    if (typeof v !== "number" || !Number.isFinite(v))
      throw new ShapeError(`${what} of finite numbers`);
    return v;
  });
  return {
    name: text(given.name, `${what}'s name`),
    unit: nonEmpty(given.unit, `${what}'s unit`),
    values,
  };
}

/**
 * A record's sealed bytes, parsed: its axis and every column, each with a unit, finite numbers
 * and one value per x. Its inputs are taken from the attempt's answer, never from here, since a
 * browser's number cannot hold every integer a record may.
 */
export function recordSamples(value: unknown): RecordSamples {
  const record = object(value, "a record");
  const x = column(record.x, "a record's x column");
  const traces = list(record.traces, "a record's traces").map((t) => column(t, "a trace"));
  if (traces.length === 0) throw new ShapeError("a record with a trace");
  for (const trace of traces)
    if (trace.values.length !== x.values.length)
      throw new ShapeError("a record whose traces have one value per x");
  return { axis: axis(record.axis), x, traces };
}
