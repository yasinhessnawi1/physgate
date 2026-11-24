/**
 * What the screen shows of a path that lies on the machine that recorded: the server sends
 * those relative to the run or as a label, and this holds the page to the same words if an
 * answer ever carries one. A home folder holds an account name, so no such path is drawn.
 */

/** What a path outside the run is shown as, before the file's own name. */
export const OUTSIDE = "<outside the run>";

/** An absolute path in a sentence: a slash that starts a word, or a drive letter. */
const ABSOLUTE = /(?<![\w.~)\]}-])((?:\/[\w.+@=,~%-]+)+\/?|[A-Za-z]:\\[^\s'"]*)/g;

/** ``path`` as the page shows it: unchanged when relative, else the label and its own name. */
export function shownPath(path: string): string {
  const absolute = path.startsWith("/") || /^[A-Za-z]:\\/.test(path);
  if (!absolute) return path;
  const name = path
    .replace(/\\/g, "/")
    .split("/")
    .filter((part) => part !== "")
    .pop();
  return name === undefined ? OUTSIDE : `${OUTSIDE}/${name}`;
}

/** ``text`` with every absolute path in it shown by :func:`shownPath`, the rest unchanged. */
export function withoutAbsolutePaths(text: string): string {
  return text.replace(ABSOLUTE, (whole: string) => {
    const kept = whole.replace(/[.,;:]+$/, "");
    return shownPath(kept) + whole.slice(kept.length);
  });
}
