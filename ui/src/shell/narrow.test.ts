import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import { followNarrow, NARROW_MAX_PX, navStartsCollapsed } from "./prefs";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHELL_CSS = readFileSync(join(HERE, "shell.css"), "utf8");
const PARTS_CSS = readFileSync(join(HERE, "..", "design", "components.css"), "utf8");
const SCREENS_CSS = readFileSync(join(HERE, "..", "screens", "screens.css"), "utf8");

/** The rules inside every ``@media (max-width: <px>px)`` block of ``css``, joined. */
function narrowRules(css: string, px: number): string {
  const found: string[] = [];
  const opener = `@media (max-width: ${String(px)}px) {`;
  let at = css.indexOf(opener);
  while (at !== -1) {
    let depth = 0;
    let i = at + opener.length - 1;
    for (; i < css.length; i++) {
      if (css[i] === "{") depth++;
      if (css[i] === "}" && --depth === 0) break;
    }
    found.push(css.slice(at, i + 1));
    at = css.indexOf(opener, i);
  }
  return found.join("\n");
}

describe("a narrow window (390 px) shows the page, not the menu, and never scrolls sideways", () => {
  it("the navigation starts collapsed in a narrow window and expanded in a wide one", () => {
    expect(navStartsCollapsed(true)).toBe(true);
    expect(navStartsCollapsed(false)).toBe(false);
  });

  it("a collapsed navigation in a narrow window shows only its top row and its button", () => {
    const rules = narrowRules(SHELL_CSS, NARROW_MAX_PX);
    expect(rules).toMatch(
      /\.pg-shell\[data-nav="collapsed"\] \.pg-nav > :not\(\.pg-brand\)\s*\{[^}]*display: none/,
    );
  });

  it("a timeline row stacks as a card: its sentence takes the whole width, never one letter", () => {
    const rules = narrowRules(PARTS_CSS, NARROW_MAX_PX);
    expect(rules).toMatch(/\.pg-trow\s*\{[^}]*grid-template-columns: max-content minmax\(0, 1fr\)/);
    expect(rules).toMatch(/\.pg-trow-main,\s*\.pg-trow-end\s*\{[^}]*grid-column: 1 \/ -1/);
  });

  it("a row's value wraps rather than pushing the page sideways", () => {
    const rules = narrowRules(SCREENS_CSS, NARROW_MAX_PX);
    expect(rules).toMatch(/\.pg-row-value,\s*\.pg-quantity\s*\{[^}]*white-space: normal/);
  });

  it("the navigation follows the window across the narrow width after the page has opened", () => {
    const listeners: ((event: { matches: boolean }) => void)[] = [];
    const query = {
      matches: false,
      addEventListener: (_: string, listener: (event: { matches: boolean }) => void) => {
        listeners.push(listener);
      },
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal("window", { matchMedia: () => query });
    const seen: boolean[] = [];
    const stop = followNarrow((narrow) => {
      seen.push(narrow);
    });
    for (const listener of listeners) listener({ matches: true });
    for (const listener of listeners) listener({ matches: false });
    expect(seen).toEqual([true, false]);
    stop();
    expect(query.removeEventListener).toHaveBeenCalled();
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});
