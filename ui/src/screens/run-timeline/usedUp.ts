/**
 * Whether a subtask's repairs are used up, said only where the queue recorded it: an item whose
 * source is the exhausted repair budget. The budget itself is a harness constant, not a record,
 * so nothing is counted here. An open item is in the listing; a decided one has left the open
 * list, so its record is read from the item views, and the mark stays once the item is decided.
 */
import type { RunEvent } from "../../api/events";
import type { ItemView, QueueListing } from "../../api/queue";

/** The queue item the log escalated ``subtask`` to, if it did. */
export function escalatedItemOf(events: readonly RunEvent[], subtask: string): string | null {
  const escalated = events.find((e) => e.kind === "escalated" && e.subtask === subtask);
  return escalated?.kind === "escalated" ? escalated.itemId : null;
}

export function repairsUsedUp(
  listing: QueueListing | null,
  views: readonly ItemView[] | null,
  itemId: string | null,
  subtask: string,
): boolean {
  if (listing === null) return false;
  if (listing.open.some((i) => i.subtaskId === subtask && i.source === "repair_budget_exhausted"))
    return true;
  if (itemId === null || views === null) return false;
  if (!listing.decided.some((d) => d.itemId === itemId)) return false;
  return views.some((v) => v.item.itemId === itemId && v.item.source === "repair_budget_exhausted");
}
