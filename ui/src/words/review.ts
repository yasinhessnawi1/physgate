/**
 * Why a review that ran is not a verdict, in plain words. One table, read by the timeline's row
 * and the queue item's headline, so the two say the same thing. A cause the table does not know
 * is shown as recorded, never guessed at; none of these is a pass or a fail.
 */
const CAUSE_WORDS: Readonly<Record<string, string>> = {
  infrastructure: "the review session stopped on a fault",
  refused: "the reviewer declined to answer",
  no_verdict: "the reviewer ended without giving a verdict",
  invalid_verdict: "the reviewer's answer did not fit the required form",
  reading_incomplete: "a file the review requires was not read",
  compacted: "the review's context was compacted",
  context_exceeded: "the review outgrew the model's context window",
  unprepared: "the review packet could not be built",
  blocking_spec_defect: "the specification blocked the review",
};

/** The cause as a clause: "the reviewer's answer did not fit the required form". */
export function causeWords(cause: string): string {
  return CAUSE_WORDS[cause] ?? `cause recorded as ${cause}`;
}

/** How many tries the record says were made ("after 5 attempts"), or ``null`` when it says none. */
export function triesIn(detail: string | null): number | null {
  const found = detail === null ? undefined : /after (\d{1,3}) attempts/.exec(detail)?.[1];
  return found === undefined ? null : Number(found);
}

/** "(5 tries)" or nothing. */
export function triesWords(detail: string | null): string {
  const n = triesIn(detail);
  return n === null ? "" : ` (${String(n)} ${n === 1 ? "try" : "tries"})`;
}
