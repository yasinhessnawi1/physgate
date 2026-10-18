import { evaluatedOf } from "../../tally";
import { VerdictBadge } from "./VerdictBadge";

export interface TallyProps {
  readonly pass: number;
  readonly fail: number;
  readonly warn: number;
  /** Always after the separator; never counted as evaluated. */
  readonly unchecked: number;
  /** Of the passes, how many looked at nothing, when known. */
  readonly overNothing?: number;
  /** The gate ran in observe mode: would-be outcomes in hatched outlines, and "not enforced". */
  readonly observed?: boolean;
  /** The run is still going: the total reads "so far". */
  readonly partial?: boolean;
  /** One badge per verdict with its word and count inside; the words are never dropped. */
  readonly compact?: boolean;
}

type Evaluated = "pass" | "fail" | "warn";
const WORD: Readonly<Record<Evaluated, string>> = { pass: "pass", fail: "fail", warn: "warn" };

/**
 * Counts of verdicts. The evaluated count is pass, fail and warn; unchecked follows a separator
 * and is never part of it, because a check that did not run evaluated nothing. Under observe
 * nothing was enforced, so the counts are would-be outcomes in dashed outlines, never filled
 * verdicts.
 */
export function Tally({
  pass,
  fail,
  warn,
  unchecked,
  overNothing,
  observed = false,
  partial = false,
  compact = false,
}: TallyProps) {
  const counts = { pass, fail, warn, unchecked };
  const evaluated = evaluatedOf(counts);
  const badge = (verdict: Evaluated) => {
    if (observed)
      return (
        <span className={`pg-badge pg-observed pg-observed-${verdict}`}>
          Would {WORD[verdict]}
          {compact && <span className="pg-badge-count">{counts[verdict]}</span>}
        </span>
      );
    return compact ? (
      <VerdictBadge verdict={verdict} count={counts[verdict]} />
    ) : (
      <VerdictBadge verdict={verdict} />
    );
  };
  const item = (verdict: Evaluated) =>
    compact ? (
      <span className="pg-tally-item">{badge(verdict)}</span>
    ) : (
      <span className="pg-tally-item">
        {badge(verdict)} <span className="pg-tally-n">{counts[verdict]}</span>
      </span>
    );
  return (
    <span className={compact ? "pg-tally pg-tally-compact" : "pg-tally"}>
      <span className="pg-tally-evaluated" data-evaluated={evaluated}>
        {item("pass")}
        {item("fail")}
        {item("warn")}
        <span className="pg-tally-total">
          of <span className="pg-tally-n">{evaluated}</span> evaluated
          {overNothing !== undefined && overNothing > 0 && (
            <span className="pg-tally-over-nothing">
              {" "}
              · <span className="pg-tally-n">{overNothing}</span>{" "}
              {overNothing === 1 ? "pass" : "passes"} over nothing
            </span>
          )}
          {observed ? " · not enforced" : ""}
          {partial && <span className="pg-so-far">so far</span>}
        </span>
      </span>
      <span className="pg-tally-sep" role="separator" aria-orientation="vertical" />
      <span className="pg-tally-unchecked">
        {compact ? (
          <VerdictBadge verdict="unchecked" count={unchecked} />
        ) : (
          <>
            <VerdictBadge verdict="unchecked" /> <span className="pg-tally-n">{unchecked}</span>
          </>
        )}
      </span>
    </span>
  );
}
