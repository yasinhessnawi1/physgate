/**
 * Every item of a run's queue as the server views it, open and decided alike, read one by one
 * from the item route. The listing names only the open items whole; a decided item's record (its
 * source among it) is reached this way.
 */
import { getJson, type Result } from "../../api/client";
import { type ItemView, itemView } from "../../api/queue";

export async function allItems(base: string, count: number): Promise<Result<readonly ItemView[]>> {
  const read = await Promise.all(
    Array.from({ length: count }, (_, i) => getJson(`${base}/queue/items/${String(i)}`, itemView)),
  );
  const views: ItemView[] = [];
  for (const one of read) {
    if (!one.ok) return one;
    views.push(one.value);
  }
  return { ok: true, value: views };
}
