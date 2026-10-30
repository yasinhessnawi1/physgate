/**
 * What the Queue screen says about its records, as pure functions a test can read: which item
 * is chosen, the seal status in words, and the exact line a decision writes, which the
 * confirmation shows before anything is sent.
 */
import type { ItemView, Position, TrajectoryStatus, Verb } from "../../api/queue";
import { decisionText, isBlank } from "../../api/queue";
import type { StatusKind } from "../../design/components/status/StatusTag";

/** Each seal status as a neutral tag: a seal is not a verdict. */
export const SEAL_TAG: Readonly<Record<TrajectoryStatus, StatusKind>> = {
  holds: "seal-holds",
  tampered: "seal-tampered",
  missing: "seal-missing",
  no_seal: "seal-none",
  not_in_this_run: "seal-elsewhere",
  too_large: "seal-too-large",
};

/** The item the query's ``item`` names by position or id, else the first open one, else the first. */
export function chosenItem(
  views: readonly ItemView[],
  wanted: string | null,
): ItemView | undefined {
  const named = views.find(
    (view) => String(view.position) === wanted || view.item.itemId === wanted,
  );
  return named ?? views.find((view) => view.open) ?? views[0];
}

/** The seals in one line: all intact, or how many are not. */
export function sealLine(view: ItemView): string {
  const n = view.trajectories.length;
  const holding = view.trajectories.filter((t) => t.status === "holds").length;
  if (n === 0) return "The item links no agent transcript.";
  if (holding === n)
    return n === 1
      ? "The agent transcript is intact (sealed)."
      : `All ${String(n)} agent transcripts are intact (sealed).`;
  return `${String(n - holding)} of ${String(n)} agent transcripts are not as they were sealed, or cannot be read.`;
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
  position?: Position,
): string | null {
  const decision = decisionText(verb, note, position);
  if (decision === null) return null;
  // The decision is bound to this view, so its line also names the verb, the note when there is
  // one, and the digest of the item as shown: exactly the fields the queue writes, in its order.
  return JSON.stringify({
    item_id: view.item.itemId,
    ts: "‹the time you confirm›",
    kind: "resolution",
    decision,
    resolved_by: operator,
    verb,
    ...(position === undefined ? {} : { position }),
    ...(isBlank(note) ? {} : { note }),
    shown_sha256: view.itemSha256,
  });
}

/** Why a verb cannot be chosen now, or ``null`` when it can. */
export function whyNot(operator: string | null, holdsToken = true): string | null {
  if (operator === null)
    return "This server was started without naming an operator, so no decision can be taken here.";
  if (!holdsToken)
    return (
      "This page was opened without the operator's address, so it can only read. Open the " +
      "operator's address the server gave when it started (the one ending in #act=…) to decide here."
    );
  return null;
}

/** A rejection without a reason is not a decision; anything else is. */
export function blankRejection(verb: Verb, note: string): boolean {
  return verb === "reject" && isBlank(note);
}
