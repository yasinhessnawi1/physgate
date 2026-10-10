import { evaluatedOf, type TallyCounts } from "../tally";

/** The four verdicts. Each has a glyph and a word, so none depends on colour alone. */
export type Verdict = "pass" | "fail" | "warn" | "unchecked";

const SHOWN: Record<Verdict, readonly [string, string]> = {
  pass: ["✓", "Pass"],
  fail: ["✕", "Fail"],
  warn: ["!", "Warn"],
  unchecked: ["○", "Unchecked"],
};

/** A verdict as recorded. Unchecked is dashed and unfilled: never styled like pass. */
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const [glyph, word] = SHOWN[verdict];
  return (
    <span className={`badge verdict verdict-${verdict}`}>
      <span aria-hidden="true">{glyph}</span> {word}
    </span>
  );
}

/**
 * Counts of verdicts. The evaluated count is pass, fail and warn; unchecked follows a
 * separator and is never part of it, because a check that did not run evaluated nothing.
 * Counted under observe, nothing was enforced, so the counts are shown as would-be outcomes in
 * dashed outlines and never as filled verdicts.
 */
export function Tally({ counts, observed = false }: { counts: TallyCounts; observed?: boolean }) {
  const evaluated = evaluatedOf(counts);
  const item = (verdict: "pass" | "fail" | "warn", word: string) =>
    observed ? (
      <span className={`badge observed observed-${verdict}`}>Would {word.toLowerCase()}</span>
    ) : (
      <VerdictBadge verdict={verdict} />
    );
  return (
    <span className="tally">
      <span className="tally-evaluated" data-evaluated={evaluated}>
        <span className="tally-item">
          {item("pass", "Pass")} <span className="mono">{counts.pass}</span>
        </span>
        <span className="tally-item">
          {item("fail", "Fail")} <span className="mono">{counts.fail}</span>
        </span>
        <span className="tally-item">
          {item("warn", "Warn")} <span className="mono">{counts.warn}</span>
        </span>
        <span className="tally-total">
          of <span className="mono">{evaluated}</span> evaluated{observed ? " · not enforced" : ""}
        </span>
      </span>
      <span className="tally-separator" role="separator" aria-orientation="vertical" />
      <span className="tally-unchecked">
        <VerdictBadge verdict="unchecked" /> <span className="mono">{counts.unchecked}</span>
      </span>
    </span>
  );
}
