/**
 * The Evidence screen's address, and the one way it changes: the tab, the run whose spend is
 * shown, and the two runs compared live in the address's query, so a link keeps them.
 */
import { hrefFor } from "../../shell/route";

export const AREA = "home";
export const SLUG = "evidence";

/** The screen's address with ``changes`` made to ``query``; a ``null`` removes its key. */
export function evidenceAddress(
  query: URLSearchParams,
  changes: Readonly<Record<string, string | null>>,
): string {
  const next = new URLSearchParams(query);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null) next.delete(key);
    else next.set(key, value);
  }
  return hrefFor(AREA, SLUG, next);
}

/** Go to ``href``, an address inside the app; nothing is asked of the server by going. */
export function go(href: string): void {
  window.location.hash = href.slice(1);
}
