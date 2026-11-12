/**
 * What the Simulation screen shows, worked out from the server's answers and nothing else: which
 * attempt and record it opens on, each attempt's tag, the rail's groups, and each record's plots.
 *
 * Nothing here computes over a record's samples. A plot is the sealed columns as they are, split
 * by unit and in recorded order; its summary is the server's summary of the same columns.
 */
import {
  type AttemptRecord,
  type ColumnSummary,
  type ListedAttempt,
  LOOP_MAGNITUDE,
  LOOP_PHASE,
  type RecordSamples,
  type SeriesListing,
  type ShownRecord,
  type Column,
} from "../../api/series";
import type { PlotSpec } from "../../design/components/plot/Plot";
import type { Source } from "../../design/components/data/source";
import {
  againstWords,
  type AttemptTag,
  groupLabel,
  joinedLabels,
  plotSummary,
  SERIES_COPY,
  traceLabel,
} from "../../words/series";

/** The most traces one plot holds; more of one unit are split across plots in recorded order. */
export const MAX_TRACES = 6;

/** The attempts the listing could read, in the order their first session ended. */
export function readAttempts(listing: SeriesListing): readonly ListedAttempt[] {
  return listing.attempts.filter((a): a is ListedAttempt => a.kind === "attempt");
}

/** Each subtask, in the order its first attempt is listed, with its attempts in that order. */
export function subtasksOf(
  listing: SeriesListing,
): readonly { readonly subtaskId: string; readonly attempts: readonly ListedAttempt[] }[] {
  const found = new Map<string, ListedAttempt[]>();
  for (const attempt of readAttempts(listing)) {
    const kept = found.get(attempt.subtaskId);
    if (kept === undefined) found.set(attempt.subtaskId, [attempt]);
    else kept.push(attempt);
  }
  return [...found].map(([subtaskId, attempts]) => ({ subtaskId, attempts }));
}

function sealedAny(attempt: ListedAttempt): boolean {
  return attempt.records.length > 0;
}

/** The merged attempt of a subtask, or else its latest. */
function openingAttempt(attempts: readonly ListedAttempt[]): ListedAttempt | undefined {
  return (
    attempts.find((a) => a.merged) ??
    attempts.reduce<ListedAttempt | undefined>(
      (latest, a) => (latest === undefined || a.attempt > latest.attempt ? a : latest),
      undefined,
    )
  );
}

export interface Choice {
  readonly attempt: ListedAttempt;
  /** The record the address names, or ``null`` to open the attempt's first. */
  readonly record: string | null;
}

/**
 * What the screen opens on. A choice the address makes always wins; with none, the first
 * subtask in log order that sealed a record, at its merged attempt or else its latest.
 */
export function chooseView(listing: SeriesListing, query: URLSearchParams): Choice | null {
  const subtasks = subtasksOf(listing);
  const wanted = query.get("subtask");
  const subtask =
    subtasks.find((s) => s.subtaskId === wanted) ??
    subtasks.find((s) => s.attempts.some(sealedAny)) ??
    subtasks[0];
  if (subtask === undefined) return null;
  const n = Number(query.get("attempt"));
  const attempt =
    (subtask.subtaskId === wanted ? subtask.attempts.find((a) => a.attempt === n) : undefined) ??
    openingAttempt(subtask.attempts);
  if (attempt === undefined) return null;
  return { attempt, record: query.get("record") };
}

/**
 * An attempt's tag, each from a line of the run's log: merged; refused before the gate, when
 * its change check refused it and no gate record names its quantities; not merged, when a
 * reviewer rejected it or a later attempt of its subtask exists; in progress while the run is;
 * not merged once the run has ended.
 */
export function attemptTag(
  attempt: ListedAttempt,
  siblings: readonly ListedAttempt[],
  runGoing: boolean,
): AttemptTag {
  if (attempt.merged) return "merged";
  const gateRan = attempt.checks.some(
    (c) =>
      c.kind === "check" &&
      (typeof c.gate !== "string" || c.gate === "not_named" || c.gate === "unmatched"),
  );
  if (attempt.refusedBy !== null && !gateRan) return "refused-before-gate";
  if (attempt.rejected || siblings.some((a) => a.attempt > attempt.attempt)) return "not-merged";
  return runGoing ? "in-progress" : "not-merged";
}

/** One of the rail's groups: its label, and its records in the order the server sent them. */
export interface RecordGroup {
  readonly key: string;
  readonly label: string;
  readonly records: readonly AttemptRecord[];
}

/**
 * The rail's groups of an attempt's records: the role's own groups, in first-seen order, with
 * "Not grouped" for a record the role gave none; then every record that is not shown (refused
 * on its seal, held as unreadable, or not readable here), whose group the screen cannot know.
 */
export function groupsOf(records: readonly AttemptRecord[]): readonly RecordGroup[] {
  const found = new Map<string, { label: string; records: AttemptRecord[] }>();
  const notShown: AttemptRecord[] = [];
  for (const record of records) {
    if (record.kind !== "shown") {
      notShown.push(record);
      continue;
    }
    const key = record.group === null ? "" : `group:${record.group}`;
    const kept = found.get(key);
    if (kept === undefined) found.set(key, { label: groupLabel(record.group), records: [record] });
    else kept.records.push(record);
  }
  const groups: RecordGroup[] = [...found].map(([key, g]) => ({ key, ...g }));
  if (notShown.length > 0)
    groups.push({ key: "not-shown", label: SERIES_COPY.notShownGroup, records: notShown });
  return groups;
}

/** One plot of a record, ready for its frame: what it is called, what it draws, its summary. */
export interface PlotPlan {
  readonly key: string;
  readonly title: string;
  readonly subtitle: string;
  /** Each trace's label, for the frame's legend. */
  readonly legend: readonly string[];
  readonly summary: string;
  /** Why a scale is linear where a log scale was the rule, or ``null``. */
  readonly note: string | null;
  readonly spec: PlotSpec;
}

/** Raised when a record's sealed columns are not the columns its summary describes. */
export class SamplesMismatchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SamplesMismatchError";
  }
}

function allAbove(values: readonly number[]): boolean {
  return values.every((v) => v > 0);
}

/** ``items`` in runs of at most ``size``, in order. */
function chunks<T>(items: readonly T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

function plan(
  key: string,
  traces: readonly Column[],
  summaries: readonly ColumnSummary[],
  x: Column,
  xSummary: ColumnSummary,
  xScale: "linear" | "log",
  yScale: "linear" | "log",
  note: string | null,
  source: Source,
): PlotPlan {
  const names = traces.map((t) => t.name);
  const unit = traces[0]?.unit ?? "";
  const title = joinedLabels(names);
  return {
    key,
    title,
    subtitle: againstWords(names, x.name),
    legend: names.map(traceLabel),
    summary: plotSummary(summaries, xSummary),
    note,
    spec: {
      title,
      x: { label: traceLabel(x.name), unit: x.unit, scale: xScale },
      xValues: x.values,
      y: { label: title, unit, scale: yScale },
      series: traces.map((t) => ({ label: traceLabel(t.name), unit: t.unit, y: t.values })),
      source,
    },
  };
}

/**
 * A record's plots: a loop's magnitude and phase on a log frequency axis; every other trace in
 * one plot per unit (split past ``MAX_TRACES``, in recorded order), on a log axis for a
 * frequency record. A log axis is used only where every value on it is above zero; elsewhere the
 * scale is linear and the plot says why.
 */
export function plotsOf(record: ShownRecord, samples: RecordSamples, source: Source): PlotPlan[] {
  if (
    samples.axis !== record.axis ||
    samples.x.name !== record.x.name ||
    samples.x.unit !== record.x.unit ||
    samples.traces.length !== record.traces.length ||
    samples.traces.some((t, i) => {
      const summary = record.traces[i];
      return summary === undefined || t.name !== summary.name || t.unit !== summary.unit;
    })
  )
    throw new SamplesMismatchError("the record's columns are not the ones its summary describes");
  const summaryOf = (t: Column): ColumnSummary => {
    const found = record.traces.find((s) => s.name === t.name);
    if (found === undefined) throw new SamplesMismatchError(`no summary of ${t.name}`);
    return found;
  };
  const frequency = record.axis === "frequency";
  const xLog = frequency && allAbove(samples.x.values);
  const xNote = frequency && !xLog ? SERIES_COPY.linearFrequency : null;
  const xScale = xLog ? "log" : "linear";
  const plans: PlotPlan[] = [];
  let rest = samples.traces;
  if (record.loop) {
    const magnitude = samples.traces.find((t) => t.name === LOOP_MAGNITUDE);
    const phase = samples.traces.find((t) => t.name === LOOP_PHASE);
    if (magnitude !== undefined && phase !== undefined) {
      const yLog = allAbove(magnitude.values);
      plans.push(
        plan(
          "loop-magnitude",
          [magnitude],
          [summaryOf(magnitude)],
          samples.x,
          record.x,
          xScale,
          yLog ? "log" : "linear",
          [xNote, yLog ? null : SERIES_COPY.linearMagnitude].filter((n) => n !== null).join(" ") ||
            null,
          source,
        ),
        plan(
          "loop-phase",
          [phase],
          [summaryOf(phase)],
          samples.x,
          record.x,
          xScale,
          "linear",
          xNote,
          source,
        ),
      );
      rest = samples.traces.filter((t) => t !== magnitude && t !== phase);
    }
  }
  const units: string[] = [];
  for (const t of rest) if (!units.includes(t.unit)) units.push(t.unit);
  for (const unit of units) {
    const ofUnit = rest.filter((t) => t.unit === unit);
    chunks(ofUnit, MAX_TRACES).forEach((part, i) => {
      plans.push(
        plan(
          `${unit}#${String(i)}`,
          part,
          part.map(summaryOf),
          samples.x,
          record.x,
          xScale,
          "linear",
          xNote,
          source,
        ),
      );
    });
  }
  return plans;
}
