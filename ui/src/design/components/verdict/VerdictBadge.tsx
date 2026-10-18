import { type Verdict, VERDICT_SHOWN } from "./verdict";

/**
 * A verdict as recorded: glyph, word and colour, always all three. Unchecked is dashed and
 * unfilled, never styled like a pass.
 */
export function VerdictBadge({
  verdict,
  count,
}: {
  readonly verdict: Verdict;
  readonly count?: number;
}) {
  const [glyph, word] = VERDICT_SHOWN[verdict];
  return (
    <span className={`pg-badge pg-verdict pg-verdict-${verdict}`}>
      <span className="pg-badge-glyph" aria-hidden="true">
        {glyph}
      </span>
      {word}
      {count !== undefined && <span className="pg-badge-count">{count}</span>}
    </span>
  );
}
