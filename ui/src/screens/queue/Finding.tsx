/**
 * What triggered a queue item, as a person reads it: a short finding whole; a long one (a
 * reviewer's paragraph can run to thousands of characters) as its opening sentence and the
 * standards it cites, with the whole finding, word for word, one click away. Nothing is
 * paraphrased: the opening is the finding's own first sentence, the standards its own ids.
 */
import { firstLine } from "../common/rows";

/** A finding longer than this many characters is shown short first. */
export const LONG_FINDING = 320;

/** A standard's id as reviewers cite it: two to four capitals, a hyphen, a number ("DS-21"). */
const STANDARD = /\b[A-Z]{2,4}-\d{1,3}\b/g;

/** The standards a finding cites, each once, in the order first cited. */
export function citedStandards(finding: string): readonly string[] {
  return [...new Set(finding.match(STANDARD) ?? [])];
}

function citeWords(cited: readonly string[]): string {
  const n = cited.length;
  return `It cites ${String(n)} standard${n === 1 ? "" : "s"}: ${cited.join(", ")}.`;
}

export function Finding({ text }: { readonly text: string }) {
  const whole = text.trim();
  if (whole.length <= LONG_FINDING) return <>{text}</>;
  const { head } = firstLine(whole);
  const cited = citedStandards(whole);
  const words = whole.split(/\s+/).length;
  return (
    <>
      <span className="pg-queue-finding-lead">{head}</span>
      {cited.length > 0 && <span className="pg-queue-finding-cites">{citeWords(cited)}</span>}
      <details className="pg-queue-finding-more">
        <summary className="pg-hit">Read the whole finding ({String(words)} words)</summary>
        <p className="pg-queue-finding-whole">{whole}</p>
      </details>
    </>
  );
}
