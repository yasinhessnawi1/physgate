/**
 * What the screens say about the approval queue, in one place.
 *
 * Two tables. The first says why a person is asked, one sentence per source the queue records.
 * The second is every sentence any screen says about a decision.
 *
 * What a decision does depends on the run. A run that only records decisions (every evaluation
 * run, and every run before decisions could act) writes one line and reads it only to remove the
 * subtask's working copy; its items say nothing about what a verb does, and the copy for them says
 * only that. A run that acts on decisions writes, on each item, what approve and reject will do
 * and why, computed from its record; the copy for such an item is made from those fields alone.
 * A sentence that promised more than the record says would be a claim born in the interface.
 */
import type {
  Consequence,
  OnChoose,
  Position,
  QueueSource,
  Taken,
  WhyRecordOnly,
} from "../api/queue";
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
    "it does not restart the subtask unless the item says, before you decide, what it will do.",
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
  verb: "approve" | "reject" | "choose",
  decisionRequired: string,
  note: string,
  position?: Position,
): string {
  const did =
    verb === "approve"
      ? "approved"
      : verb === "reject"
        ? "rejected"
        : `chose ${POSITION_WORDS[position ?? "sizing"].toLowerCase()} on`;
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
  escalation_decision: "A subtask was sent to a person",
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

/** Why approving an item records only, after "Approve records only: ". */
const WHY_RECORD_ONLY_WORDS: Readonly<Record<WhyRecordOnly, string>> = {
  gate: "the physics gate refused the attempt, and a person overrides the reviewer alone",
  change_check: "the change check refused the attempt, and a person overrides the reviewer alone",
  reading:
    "the attempt's required reading was not completed, and a person overrides the reviewer alone",
  indicator_in_history: "a review of this subtask confirmed a reward-hacking indicator",
  scan_hit: "the scan before review found a reward-hacking indicator that no review judged",
  source: "for an item of this kind a decision is recorded and changes nothing in the run",
  legacy: "the item was listed before items said what a decision does",
};

/** Each position a person may choose, as its button names it. */
export const POSITION_WORDS: Readonly<Record<Position, string>> = {
  sizing: "Sizing's value",
  domain: "The domain's value",
};

/** What choosing a position does, from what the item says it does. */
export const CHOOSE_WORDS: Readonly<Record<OnChoose, string>> = {
  record_only: "Choose: the decision is recorded, and nothing in the run acts on it.",
};

/** The approve button's label on an item whose approve records only. */
export const APPROVE_RECORDS_ONLY = "Approve (records only)…";

/** What each choice does to an item, in the dialog and on the item, from its own fields. */
export interface ChoiceWords {
  /** The approve button's label. */
  readonly approveLabel: `${string}…`;
  readonly approve: string;
  readonly reject: string;
}

function indicatorWords(c: Consequence): string {
  const named = c.confirmedIndicators.map((i) => `attempt ${String(i.attempt)} (${i.kind})`);
  return named.length === 1
    ? `the review of ${named[0] ?? ""} confirmed a reward-hacking indicator`
    : `reviews of this subtask confirmed reward-hacking indicators: ${named.join(", ")}`;
}

const REJECT_WORDS: Readonly<Record<Consequence["onReject"], string>> = {
  retry:
    "Reject: this attempt is spent, and the next one starts from your note, quoted as you " +
    "wrote it. Its reviewer is told what it was told.",
  fix:
    "Reject: one fix is made by a fresh session in the subtask's working copy, told the " +
    "review's verdict and your note and nothing of the earlier session. It is the subtask's " +
    "last attempt; if it is not accepted, the subtask ends rejected.",
  end_subtask: "Reject: the subtask ends rejected, and nothing of it is merged.",
  record_only: "Reject: the decision is recorded, and nothing in the run acts on it.",
};

/** What approve and reject will do to an item, made from the consequence the run listed. */
export function consequenceWords(c: Consequence): ChoiceWords {
  const reject = REJECT_WORDS[c.onReject];
  if (c.onApprove === "merge_attempt") {
    const commit = c.attemptCommit === null ? "" : ` (commit ${c.attemptCommit.slice(0, 12)})`;
    return {
      approveLabel: "Approve…",
      approve:
        `Approve: attempt ${String(c.attempt ?? "")}${commit} is merged into the run exactly as ` +
        "shown, by the run's own merge, and the whole-design gate then judges it with the rest.",
      reject,
    };
  }
  const why =
    c.whyRecordOnly === "indicator_in_history" && c.confirmedIndicators.length > 0
      ? indicatorWords(c)
      : WHY_RECORD_ONLY_WORDS[c.whyRecordOnly ?? "source"];
  return {
    approveLabel: APPROVE_RECORDS_ONLY,
    approve: `Approve records only: ${why}.`,
    reject,
  };
}

const NOT_TAKEN_WORDS: Readonly<Record<string, string>> = {
  held_os_layer_off:
    "Held: it was written while a session ran without the OS layer, so it acts only once an " +
    "operator confirms it on the command line.",
  not_bound: "Recorded only: it was not taken on a view of the item.",
  legacy_item: "Recorded only: the item does not say what a decision does.",
};

/** What the run did with a decision, from its own record of taking it. */
export function takenWords(t: Taken): string {
  if (!t.acts) {
    const known = t.whyNot === null ? undefined : NOT_TAKEN_WORDS[t.whyNot];
    return known ?? `Recorded only (${t.whyNot ?? "no reason recorded"}).`;
  }
  const done: Readonly<Record<Taken["effect"], string>> = {
    merge: "The run took it: the attempt it names was merged.",
    retry: "The run took it: the next attempt started from the note.",
    fix: "The run took it: one fix was ordered.",
    end_subtask: "The run took it: the subtask ended rejected.",
    none: "The run took it; it changed nothing.",
  };
  const by = t.confirmedBy === null ? "" : ` Confirmed on the command line by ${t.confirmedBy}.`;
  if (t.orderTooLong)
    return (
      "The run took it: the subtask ended rejected, and no session was started. What that " +
      "session would have been told was longer than its reviewer can read whole." +
      by
    );
  return done[t.effect] + by;
}
