/**
 * The Simulation screen's words: the extractors in words, a record's labels, the sentences for
 * each state, and the plot summary.
 *
 * Every figure a sentence holds is a value the server sent, spelled by the one value label every
 * quantity uses, with its unit: none is computed here. A word the screen has no entry for (an
 * extractor, an outcome, a gate state) is shown as written, never guessed at.
 */
import type { ColumnSummary, Extractor } from "../api/series";
import { unitLabel, valueLabel } from "../design/quantity";
import { quantityLabel, word } from "./humanise";

/** Each extractor in words. A time extractor's words are followed by the trace it reads. */
export const EXTRACTOR_WORDS: Readonly<Record<Extractor, string>> = {
  phase_margin: "Phase margin",
  gain_crossover_frequency: "Gain crossover frequency",
  gain_margin_upper: "Upper gain margin",
  gain_margin_lower: "Lower gain margin",
  stability_margin: "Stability margin",
  sensitivity_peak: "Sensitivity peak",
  complementary_sensitivity_peak: "Complementary sensitivity peak",
  delay_margin: "Delay margin",
  max: "Largest value of",
  min: "Smallest value of",
  max_abs: "Largest magnitude of",
  final: "Final value of",
};

function known(extract: string): extract is Extractor {
  return Object.hasOwn(EXTRACTOR_WORDS, extract);
}

/** A name in words, mid-sentence: each token from the vocabulary or as written, none raised. */
export function inWords(name: string): string {
  const words = name
    .split(/[._]/)
    .filter((t) => t !== "")
    .map(word);
  return words.length === 0 ? name : words.join(" ");
}

/** A trace's or a column's label, leading: `motor_current` reads "Motor current". */
export function traceLabel(name: string): string {
  return quantityLabel(name);
}

/** How a quantity was read off its record: "Final value of position", or "Phase margin". */
export function extractorWords(extract: string, trace: string | null): string {
  const lead = known(extract) ? EXTRACTOR_WORDS[extract] : extract;
  return trace === null ? lead : `${lead} ${inWords(trace)}`;
}

/** A record's group in words, or that the role gave it none. */
export function groupLabel(group: string | null): string {
  return group === null ? "Not grouped" : quantityLabel(group);
}

export function axisWords(axis: "time" | "frequency"): string {
  return axis === "time" ? "Time record" : "Frequency record";
}

/** Who titled a record: the role its subtask was planned for. */
export function titledBy(role: string): string {
  return `titled by the ${role} role`;
}

/** Labels joined for a title: "Position", "Position and error", "Position, error and speed". */
export function joinedLabels(names: readonly string[]): string {
  const [first, ...rest] = names;
  if (first === undefined) return "";
  const words = [traceLabel(first), ...rest.map(inWords)];
  if (words.length === 1) return words[0] ?? "";
  return `${words.slice(0, -1).join(", ")} and ${words.at(-1) ?? ""}`;
}

/** What a plot draws against what: "Position and error against time". */
export function againstWords(traces: readonly string[], x: string): string {
  return `${joinedLabels(traces)} against ${inWords(x)}`;
}

function figure(value: number | string, unit: string): string {
  return `${valueLabel(value)} ${unitLabel(unit)}`;
}

/**
 * A trace's summary under its plot, from the server's summary of the record alone:
 * "Position against time: 501 samples from 0 s to 10 s. Smallest 0 m, largest 1.39 m, last 1 m."
 */
export function summarySentence(trace: ColumnSummary, x: ColumnSummary): string {
  return (
    `${traceLabel(trace.name)} against ${inWords(x.name)}: ${String(trace.samples)} samples ` +
    `from ${figure(x.first, x.unit)} to ${figure(x.last, x.unit)}. ` +
    `Smallest ${figure(trace.smallest, trace.unit)}, largest ${figure(trace.largest, trace.unit)}, ` +
    `last ${figure(trace.last, trace.unit)}.`
  );
}

/** A plot's summary: each of its traces' sentences, in recorded order. */
export function plotSummary(traces: readonly ColumnSummary[], x: ColumnSummary): string {
  return traces.map((t) => summarySentence(t, x)).join(" ");
}

/**
 * The tolerance a quantity is held to its record within, in words, keyed by the harness's own
 * spelling of it. One the screen has no words for reads as the harness wrote it.
 */
const TOLERANCE_WORDS: Readonly<Record<string, { readonly short: string; readonly full: string }>> =
  {
    "0.005": {
      short: "three significant figures",
      full: "three significant figures (0.5 % relative)",
    },
  };

export function toleranceWords(tolerance: string): {
  readonly short: string;
  readonly full: string;
} {
  return (
    TOLERANCE_WORDS[tolerance] ?? {
      short: `a relative tolerance of ${tolerance}`,
      full: `a relative tolerance of ${tolerance}`,
    }
  );
}

/** Whether a checked quantity agreed with its record, in words; an unknown outcome as written. */
export function agreementWords(outcome: string, tolerance: string): string {
  switch (outcome) {
    case "agrees":
      return `Agrees within ${toleranceWords(tolerance).short}`;
    case "differs":
      return "Differs: the attempt was refused before the gate";
    case "unreadable":
      return "Could not be read off the record";
    default:
      return outcome;
  }
}

/** A recorded reason as a sentence: its first letter raised, a full stop if it has none. */
export function asSentence(reason: string): string {
  const raised = `${(reason[0] ?? "").toUpperCase()}${reason.slice(1)}`;
  return /[.!?]$/.test(raised) ? raised : `${raised}.`;
}

/** What the gate column says when no gate record of the attempt is shown for the quantity. */
export const GATE_WORDS: Readonly<Record<string, string>> = {
  not_named: "No gate record of this attempt names this quantity.",
  unmatched: "Named by the gate's finding, but it cannot be matched to one gate record.",
  gate_off: "The gate did not run.",
  refused_before_gate: "The gate did not run: the attempt was refused before it.",
  gate_not_run: "The gate has not run on this attempt.",
};

/** The gate column's sentence for ``state``; a state the screen has no words for, as written. */
export function gateWords(state: string): string {
  return GATE_WORDS[state] ?? state;
}

/** An attempt's neutral tag in the rail, each from a line of the run's log. */
export type AttemptTag = "merged" | "refused-before-gate" | "not-merged" | "in-progress";

export const ATTEMPT_TAG_WORDS: Readonly<Record<AttemptTag, string>> = {
  merged: "Merged",
  "refused-before-gate": "Refused before the gate",
  "not-merged": "Not merged",
  "in-progress": "In progress",
};

/** A file a session's end did not seal, with the collector's reason, as a sentence. */
export function setAsideWords(how: string, reason: string): string {
  const lead =
    how === "refused" ? "Not sealed" : how === "discarded" ? "Discarded, not sealed" : how;
  return `${lead}: ${reason}${/[.!?]$/.test(reason) ? "" : "."}`;
}

/** A record of the attempt a later session recorded again. */
export function supersededWords(recordId: string): string {
  return `A later session of this attempt recorded ${recordId} again; the later one is shown.`;
}

/** A sealed record this version of the format does not admit. */
export function heldWords(reason: string): string {
  return `This record is sealed, but this version cannot read it: ${reason}${/[.!?]$/.test(reason) ? "" : "."}`;
}

/** A row the server sent that this page could not read. */
export function unreadWords(error: string): string {
  return `This row could not be read: ${error}.`;
}

/** A count of records, with "so far" while the run is still going. */
export function recordsCount(n: number, partial: boolean): string {
  return `${String(n)} ${n === 1 ? "record" : "records"}${partial ? " so far" : ""}`;
}

/** The screen's fixed sentences and labels. */
export const SERIES_COPY = {
  title: "Simulation",
  lede: "What the run's simulations recorded, as each was sealed when its session ended.",
  readingRun: "the run's simulation records",
  readingRecord: "the record",
  runError: "The run's simulation records could not be read",
  attemptError: "This attempt's records could not be read",
  recordError: "The record could not be read",
  noRunTitle: "No run yet",
  noRunBody: "A run's simulation records appear here once a run is recorded on this machine.",
  noRecordsTitle: "This run recorded no simulations.",
  noRecordsBody:
    "A role records a simulation when its script runs one; any quantity read off a record is checked against it before the gate.",
  noSealed: "This attempt left no sealed record.",
  inProgress: "Records appear when the session that wrote them ends.",
  broken: "This record changed after its session ended, so it is not shown.",
  notWhatWasSealed: "Not what was sealed",
  provenance:
    "This record names the committed code that wrote it. The harness did not re-run that code to confirm the curve.",
  checkedOnRead: "Checked against its seal on this read.",
  environment: "the interpreter's own installation, outside every place the session can write",
  aboveTable:
    "Each quantity a role read off one of its records was checked against that record before the gate. The gate column shows only what a gate record says about that quantity.",
  tableTitle: "What was read off a record, and what the gate said",
  noChecks: "No quantity of this attempt was read off a record.",
  readOffTitle: "Read off this record",
  notRead: "Not read",
  linearMagnitude: "Drawn on a linear scale: the record holds a magnitude of zero or below.",
  linearFrequency:
    "Drawn on a linear frequency scale: the record holds a frequency of zero or below.",
  slotTitle: "3D and multi-domain views",
  slotBody:
    "Tool views, such as a CAD viewer, a KiCad viewer or a co-simulation, appear here once one is added. None is added yet.",
  railTitle: "Simulation records",
  setAsideTitle: "Set aside",
  supersededTitle: "Superseded",
  notShownGroup: "Records not shown",
  inputsTitle: "Inputs and how it was produced",
  inputs: "Inputs",
  producedBy: "How it was produced",
  loaded: "Code it loaded",
  noInputs: "The record names no inputs.",
  recordedSeries: "Recorded series",
  views: "Views of this record",
  showRow: "Show its row",
  openGraph: "Open in the design graph",
  openGateChecks: "See the gate checks",
  unreadAttempt: "An attempt could not be read",
} as const;

/** The seal line's words, around the session id, length and digest the screen shows as data. */
export const SEAL_WORDS = {
  sealedWhen: "Sealed when session",
  ended: "ended",
} as const;

/** The opening sentence of the screen's error: what could not be read, and the server's reason. */
export function runErrorTitle(error: string): string {
  return `${SERIES_COPY.runError}: ${error}${/[.!?]$/.test(error) ? "" : "."}`;
}
