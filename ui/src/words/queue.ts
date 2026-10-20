/**
 * What the screens say about the approval queue, in one place.
 *
 * Two tables. The first says why a person is asked, one sentence per source the queue records.
 * The second is every sentence any screen says about a decision. Today's harness records a
 * decision as one line, and the run reads it only to remove the subtask's working copy at its
 * next clean-up; it never reads the verb, and nothing is retried, resumed or merged. So the copy
 * says only that. A sentence that promised more would be a claim born in the interface.
 */
import type { QueueSource } from "../api/queue";
import { causeWords, triesWords } from "./review";

export interface SourceWords {
  /** The kind of item, short, for a list row's overline. */
  readonly kind: string;
  /** Why a person is asked, as a sentence. */
  readonly why: string;
}

export const SOURCE_WORDS: Readonly<Record<QueueSource, SourceWords>> = {
  gate_escalation: {
    kind: "Whole-design gate failure",
    why: "The finished design failed the gate after every subtask had merged, and no one subtask owns it.",
  },
  repair_budget_exhausted: {
    kind: "Repairs used up",
    why: "The subtask was sent back on every attempt it was allowed, so no repair is left.",
  },
  review_unavailable: {
    kind: "Review reached no verdict",
    why: "The reviewer could not reach a verdict on the attempt. No repair attempt was spent.",
  },
  review_blocked: {
    kind: "Review blocked",
    why: "The reviewer could not decide a safety-critical check, because the specification lacks its input.",
  },
  arbitration: {
    kind: "Builder and reviewer disagree",
    why: "The agent that built the work and the reviewer disagree, and only a person can settle it.",
  },
  escalation_decision: {
    kind: "Sent early to a person",
    why: "The escalation decision sent the subtask to a person while it still had attempts left.",
  },
};

/** Every sentence a screen says about a decision. Nothing else on a screen says it. */
export const DECISION_COPY = {
  /** The dialog's "Then": the same for approve and reject, for every source. */
  then:
    "Nothing else happens in this run. The subtask is not retried, resumed or merged. If the run " +
    "is still going, the orchestrator removes the subtask's working copy at its next clean-up.",
  /** The timeline, Home and the queue's footer, where a subtask was set aside. */
  setAside: "Set aside for a person to decide. The run goes on with the other subtasks.",
  /** The glossary's entry for a queue item. */
  queueItem:
    "A question the run could not settle by itself. Your decision is recorded against the run; " +
    "it does not restart the subtask.",
  /** Under the buttons: which of the two needs a reason. */
  reasonRule: "Approving needs no reason; a rejection must say why.",
} as const;

/** The timeline's row for a subtask set aside, naming the queue item it became. */
export function setAsideWith(itemId: string): string {
  return `Set aside for a person to decide (${itemId}). The run goes on with the other subtasks.`;
}

/** The dialog's opening sentence: who records what, about which item. */
export function decisionSummary(
  operator: string,
  verb: "approve" | "reject",
  decisionRequired: string,
  note: string,
): string {
  const did = verb === "approve" ? "approved" : "rejected";
  const quoted = `'${decisionRequired}'`;
  return note.trim() === ""
    ? `This records: ${operator} ${did} ${quoted}.`
    : `This records: ${operator} ${did} ${quoted}, with the note '${note}'.`;
}

/**
 * Words no screen may use about a decision: each claims the run does something with it that the
 * harness does not do. A test reads the rendered screens and the sources for them.
 */
export const BANNED_DECISION_WORDS: readonly RegExp[] = [
  /\bresumes?\b/i,
  /\bretry\b/i,
  /\bretries\b/i,
  /\bmerges\b/i,
  /gets a new attempt/i,
  /fresh attempt/i,
  /waits? for your decision/i,
  /side with/i,
];

/** The banned words found in ``text``. */
export function bannedIn(text: string): readonly string[] {
  return BANNED_DECISION_WORDS.filter((w) => w.test(text)).map(String);
}

/** The headline of an item, by source: what happened, in a sentence, with no raw record in it. */
const HEADLINES: Readonly<Record<QueueSource, string>> = {
  gate_escalation: "The finished design failed the gate",
  repair_budget_exhausted: "A subtask used up its repairs",
  review_unavailable: "The review reached no verdict",
  review_blocked: "A review could not decide a safety-critical check",
  arbitration: "The builder and the reviewer disagree",
  escalation_decision: "A subtask was sent to a person early",
};

/**
 * A queue item's headline, made by code from its source and, for a review with no verdict, the
 * cause and attempt its text names; no model. The raw text is kept apart, under "Details". When
 * the cause cannot be read from it the source's own sentence stands.
 */
export function queueHeadline(item: {
  readonly source: QueueSource;
  readonly decisionRequired: string;
}): string {
  if (item.source !== "review_unavailable") return HEADLINES[item.source];
  const text = item.decisionRequired;
  const cause = /\(([a-z_]+):/.exec(text)?.[1];
  if (cause === undefined) return HEADLINES.review_unavailable;
  const attempt = /attempt (\d{1,4})/.exec(text)?.[1];
  return `The review${attempt === undefined ? "" : ` of attempt ${attempt}`} reached no verdict: ${causeWords(cause)}${triesWords(text)}`;
}
