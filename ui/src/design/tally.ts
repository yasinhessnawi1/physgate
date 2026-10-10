/**
 * The one tally of gate outcomes. Every count of pass, fail, warn and unchecked on every screen
 * comes from here, so the rule that makes the gate honest is written once: a check that did not
 * run evaluated nothing, so **unchecked is never counted as a pass and never inside the
 * evaluated count**. A source fence test fails if any other module counts outcomes itself.
 *
 * It counts records as the gate wrote them: one pass record per check and scope that ran, one
 * record per failing, warning or unchecked instance.
 */
import type { Verdict } from "./components/VerdictBadge";

export interface TallyCounts {
  readonly pass: number;
  readonly fail: number;
  readonly warn: number;
  readonly unchecked: number;
  /** Of the passes, how many looked at nothing (a pass record with 0 evaluated), when known. */
  readonly overNothing?: number;
}

/** Counts of each outcome among ``outcomes``. */
export function tallyOf(outcomes: Iterable<Verdict>): TallyCounts {
  let pass = 0;
  let fail = 0;
  let warn = 0;
  let unchecked = 0;
  for (const outcome of outcomes) {
    if (outcome === "pass") pass += 1;
    else if (outcome === "fail") fail += 1;
    else if (outcome === "warn") warn += 1;
    else unchecked += 1;
  }
  return { pass, fail, warn, unchecked };
}

/** What was evaluated: pass, fail and warn. Unchecked evaluated nothing and is not here. */
export function evaluatedOf(counts: TallyCounts): number {
  return counts.pass + counts.fail + counts.warn;
}

/**
 * The tally of gate records, and how many of the passes looked at nothing. A pass over nothing
 * stays a pass record, as the gate wrote it; the count says it out loud next to "evaluated".
 */
export function tallyOfChecks(
  checks: Iterable<{ readonly outcome: Verdict; readonly evaluated: number | null }>,
): TallyCounts {
  const all = [...checks];
  return {
    ...tallyOf(all.map((c) => c.outcome)),
    overNothing: all.filter((c) => c.outcome === "pass" && c.evaluated === 0).length,
  };
}
