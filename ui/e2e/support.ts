/**
 * What every browser test of the operator UI shares: a watch on every request (anything not to
 * this loopback server is aborted and counted) and on content-security-policy violations, the
 * computed-style reader, and the design's binding styling rules read from what the browser draws.
 */
import { expect, type Page } from "@playwright/test";

import { PORT } from "./port";

export const LOCAL = new RegExp(`^http://127\\.0\\.0\\.1:${String(PORT)}/`);
export const THEMES = ["light", "dark"] as const;

export interface Watch {
  readonly outbound: string[];
  readonly api: Set<string>;
}

export async function watch(page: Page): Promise<Watch> {
  const seen: Watch = { outbound: [], api: new Set() };
  await page.route("**/*", async (route) => {
    const url = route.request().url();
    if (LOCAL.test(url)) {
      const path = new URL(url).pathname;
      if (path.startsWith("/api/"))
        seen.api.add(path.replace(/\/trajectories\/[^/]+$/, "/trajectories/:session"));
      await route.continue();
    } else {
      seen.outbound.push(url);
      await route.abort();
    }
  });
  await page.addInitScript(() => {
    const store = window as unknown as { cspViolations: string[] };
    store.cspViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      store.cspViolations.push(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });
  return seen;
}

/** The computed values of ``properties`` for every element ``selector`` matches. */
export async function styles(
  page: Page,
  selector: string,
  properties: readonly string[],
): Promise<Record<string, string>[]> {
  const found = await page.locator(selector).evaluateAll(
    (all, props) =>
      all.map((el) => {
        const computed = getComputedStyle(el);
        return Object.fromEntries(props.map((p) => [p, computed.getPropertyValue(p)]));
      }),
    properties,
  );
  expect(found.length, `nothing on the page matches ${selector}`).toBeGreaterThan(0);
  return found;
}

export const TRANSPARENT = "rgba(0, 0, 0, 0)";

/**
 * The design's binding styling rules, read from what the browser draws rather than from class
 * names: a class can stay while its style changes underneath it.
 */
export async function bindingStylesHold(page: Page) {
  // Unchecked: dashed and unfilled, never drawn like a pass.
  for (const u of await styles(page, ".verdict-unchecked", [
    "border-top-style",
    "background-color",
  ])) {
    expect(u).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
  }
  // Every quantity: Plex Mono, tabular figures, never wrapped.
  for (const q of await styles(page, ".quantity", [
    "font-family",
    "font-variant-numeric",
    "white-space",
  ])) {
    expect(q["font-family"]).toContain("IBM Plex Mono");
    expect(q["font-variant-numeric"]).toContain("tabular-nums");
    expect(q["white-space"]).toBe("nowrap");
  }
  // Buttons and run links are at least 44 px tall.
  const heights = await page
    .locator(".button, .run-link")
    .evaluateAll((all) => all.map((el) => el.getBoundingClientRect().height));
  expect(heights.length).toBeGreaterThan(0);
  for (const height of heights) expect(height).toBeGreaterThanOrEqual(44);
}

export async function cspViolations(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { cspViolations: string[] }).cspViolations);
}
