/**
 * What triggered a queue item, as a person reads it: the verdict the item's source says the
 * finding is, first, then a short finding whole; a long one (a reviewer's paragraph can run to
 * thousands of characters) as its opening sentence and the rubric items it names, with the whole
 * finding, word for word, one click away. Nothing is paraphrased: the opening is the finding's
 * own first sentence, the items its own ids, met or not.
 */
import type { QueueSource } from "../../api/queue";
import { FINDING_VERDICT, RAISED_PART_VERDICT } from "../../words/queue";
import { firstLine } from "../common/rows";
import { partRound } from "./parts";

/** A finding longer than this many characters is shown short first. */
export const LONG_FINDING = 320;

/**
 * Each rubric's item-id prefixes, as the approved rubrics number their items: a two-letter
 * prefix with a hyphen ("DS-21"), the control rubric's one letter with none ("D33"). Only these
 * are counted, so a hash name, a cipher, a bus or a part number ("SHA-256", "AES-128", "USB-3",
 * "DRV8838") is not taken for a rubric item.
 */
const HYPHENED = [
  ...["AC", "DS", "AP", "RH"],
  ...["EA", "ES", "EP", "EH"],
  ...["MA", "MS", "MP", "MH"],
  ...["SA", "SS", "SP", "SH"],
  ...["IA", "IS", "IP", "IH"],
  ...["PA", "PS", "PP", "PH"],
];
const SINGLE = ["A", "D", "S", "R"];

/** A rubric item's id as a reviewer cites it, with a clause letter where one is cited ("DS-10c"). */
const RUBRIC_ITEM = new RegExp(
  `\\b(?:(?:${HYPHENED.join("|")})-|(?:${SINGLE.join("|")}))\\d{1,3}[a-z]?\\b`,
  "g",
);

/** The rubric items a finding names, each once, in the order first named. */
export function citedStandards(finding: string): readonly string[] {
  return [...new Set(finding.match(RUBRIC_ITEM) ?? [])];
}

function citeWords(cited: readonly string[]): string {
  const n = cited.length;
  const items = n === 1 ? "1 item" : `${String(n)} items`;
  return `It names ${items} of the reviewer's rubric, met or not: ${cited.join(", ")}.`;
}

/** The verdict an item's finding is, by its source, and for a part by its round. */
export function findingVerdict(source: QueueSource, itemId?: string): string | null {
  if (source === "parts" && itemId !== undefined && (partRound(itemId)?.round ?? 1) > 1)
    return RAISED_PART_VERDICT;
  return FINDING_VERDICT[source];
}

export function Finding({
  text,
  source,
  itemId,
}: {
  readonly text: string;
  /** The item's source, which says what its finding is the verdict of. */
  readonly source: QueueSource;
  /** The item's id: a part raised again is a verdict, where its first round is a question. */
  readonly itemId?: string;
}) {
  const whole = text.trim();
  const verdict = findingVerdict(source, itemId);
  const lead = verdict !== null && (
    <>
      <strong className="pg-queue-finding-verdict">{verdict}</strong>{" "}
    </>
  );
  if (whole.length <= LONG_FINDING)
    return (
      <>
        {lead}
        <span className="pg-queue-finding-text">{text}</span>
      </>
    );
  const { head } = firstLine(whole);
  const cited = citedStandards(whole);
  const words = whole.split(/\s+/).length;
  return (
    <>
      <span className="pg-queue-finding-lead">
        {lead}
        {head}
      </span>
      {cited.length > 0 && <span className="pg-queue-finding-cites">{citeWords(cited)}</span>}
      <details className="pg-queue-finding-more">
        <summary className="pg-hit">Read the whole finding ({String(words)} words)</summary>
        <p className="pg-queue-finding-whole">{whole}</p>
      </details>
    </>
  );
}
