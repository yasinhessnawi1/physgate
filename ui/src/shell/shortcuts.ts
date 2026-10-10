/**
 * Keyboard shortcuts, two keys each and never one: g then g opens the design graph, g then t the
 * run timeline, g then q the approval queue's area. A shortcut keeps the chosen run. Keys typed
 * into a field are never shortcuts.
 */
import { hrefFor } from "./route";

/** How long after the first key the second still counts, in milliseconds. */
export const CHORD_MS = 1500;

const SECOND: Readonly<Record<string, readonly [string, string | null]>> = {
  g: ["orchestration", "design-graph"],
  t: ["orchestration", "run-timeline"],
  q: ["collaboration", null],
};

/** Where the second key of a chord goes, or ``null`` when the two keys are not a shortcut. */
export function chordTarget(
  first: { readonly key: string; readonly at: number } | null,
  key: string,
  at: number,
  query: URLSearchParams,
): string | null {
  if (first?.key !== "g" || at - first.at > CHORD_MS) return null;
  const target = SECOND[key];
  if (target === undefined) return null;
  const run = query.get("run");
  const keep = new URLSearchParams(run === null || target[1] === null ? undefined : { run });
  return hrefFor(target[0], target[1], keep);
}

/** Whether a key event belongs to a field the person is typing in, or carries a modifier. */
export function notAShortcut(event: KeyboardEvent): boolean {
  const target = event.target;
  const typing =
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName));
  return typing || event.ctrlKey || event.metaKey || event.altKey;
}
