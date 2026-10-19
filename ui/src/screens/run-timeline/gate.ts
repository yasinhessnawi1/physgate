/**
 * An attempt's gate call read from the gate's own per-check records, counted by the one tally.
 * No record is no verdict, never a pass; records that are all unchecked judged nothing;
 * otherwise the gate failed if a record failed where its failure blocks (a failure that does not
 * block is a warning, as the gate itself records one), and the reading says how many it left
 * unchecked. Under observe nothing was enforced, so it reads as what the gate would have done.
 */
import type { GateCheck } from "../../api/run";
import type { GateMode } from "../../design/components/verdict/GateMode";
import { evaluatedOf, tallyOf } from "../../design/tally";

export type GateReading =
  | { readonly kind: "off" }
  | { readonly kind: "none" }
  | { readonly kind: "unchecked-only" }
  | {
      readonly kind: "judged";
      readonly mode: "on" | "observe";
      readonly outcome: "pass" | "fail";
      readonly unchecked: number;
    };

export function gateReading(
  mode: GateMode,
  records: readonly Pick<GateCheck, "outcome" | "blocking">[],
  skipped: boolean,
): GateReading {
  if (skipped || mode === "off") return { kind: "off" };
  if (records.length === 0) return { kind: "none" };
  const counts = tallyOf(
    records.map((r) => (r.outcome === "fail" && !r.blocking ? "warn" : r.outcome)),
  );
  if (evaluatedOf(counts) === 0) return { kind: "unchecked-only" };
  return {
    kind: "judged",
    mode,
    outcome: counts.fail > 0 ? "fail" : "pass",
    unchecked: counts.unchecked,
  };
}

/** The reading in words. */
export function readingWords(reading: GateReading): string {
  switch (reading.kind) {
    case "off":
      return "The gate did not run: it is off for this run.";
    case "none":
      return "No gate result is recorded for this attempt.";
    case "unchecked-only":
      return "The gate judged nothing: every record is unchecked.";
    case "judged": {
      const left = reading.unchecked > 0 ? ` It left ${String(reading.unchecked)} unchecked.` : "";
      return reading.mode === "observe"
        ? `The gate would have ${reading.outcome === "fail" ? "failed" : "passed"} this attempt, but was not enforced.${left}`
        : `The gate ${reading.outcome === "fail" ? "failed" : "passed"} this attempt.${left}`;
    }
  }
}
