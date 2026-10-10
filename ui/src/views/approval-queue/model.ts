/**
 * What the Queue view says about its records, as pure functions a test can read: the words for
 * an item's source and a trajectory's seal status, which item is chosen, and the exact line a
 * decision writes, which the confirmation shows before anything is sent.
 */
import type { Verdict } from "../../design/components/VerdictBadge";
import type { ItemView, QueueSource, TrajectoryStatus, Verb } from "../../api/queue";
import { decisionText } from "../../api/queue";

export const SOURCE_LABEL: Readonly<Record<QueueSource, string>> = {
  gate_escalation: "Physics-gate escalation",
  repair_budget_exhausted: "Repair budget exhausted",
  review_unavailable: "Review reached no verdict",
  review_blocked: "Review blocked",
  arbitration: "Arbitration",
};

/** Each seal status as a verdict-styled badge: a glyph and words, never colour alone. */
export const STATUS_SHOWN: Readonly<Record<TrajectoryStatus, readonly [Verdict, string, string]>> =
  {
    holds: ["pass", "✓", "Seal holds"],
    tampered: ["fail", "✕", "Not what was sealed"],
    missing: ["fail", "✕", "Missing"],
    too_large: ["warn", "!", "Too large to read"],
    no_seal: ["unchecked", "○", "No seal recorded"],
    not_in_this_run: ["unchecked", "○", "Not in this run"],
  };

/** The item the query's ``item`` names by position, else the first open one, else the first. */
export function chosenItem(
  views: readonly ItemView[],
  wanted: string | null,
): ItemView | undefined {
  const named = views.find((view) => String(view.position) === wanted);
  return named ?? views.find((view) => view.open) ?? views[0];
}

/**
 * The line a decision writes, as the queue writes it, but for its time: the server stamps that
 * when it records, so the confirmation says so rather than inventing one. Keys in the order the
 * record has them. ``null`` while the decision is not one (a rejection without a note).
 */
export function lineToWrite(
  view: ItemView,
  verb: Verb,
  note: string,
  operator: string,
): string | null {
  const decision = decisionText(verb, note);
  if (decision === null) return null;
  return JSON.stringify({
    item_id: view.item.itemId,
    ts: "‹the time you confirm›",
    kind: "resolution",
    decision,
    resolved_by: operator,
  });
}

/** Why a verb cannot be chosen now, or ``null`` when it can. */
export function whyNot(verb: Verb, note: string, operator: string | null): string | null {
  if (operator === null)
    return "This server was started without naming an operator, so no decision can be taken here.";
  if (verb === "reject" && note.trim() === "") return "A rejection says why: write the note first.";
  return null;
}
