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
  for (const u of await styles(page, ".pg-verdict-unchecked", [
    "border-top-style",
    "background-color",
  ])) {
    expect(u).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
  }
  // Every quantity: JetBrains Mono, tabular figures with the zero told apart, never wrapped.
  for (const q of await styles(page, ".pg-quantity", [
    "font-family",
    "font-variant-numeric",
    "white-space",
  ])) {
    expect(q["font-family"]).toContain("JetBrains Mono");
    expect(q["font-variant-numeric"]).toContain("tabular-nums");
    expect(q["font-variant-numeric"]).toContain("slashed-zero");
    expect(q["white-space"]).toBe("nowrap");
  }
  // Buttons and run links: a hit area of at least 44 by 44 px.
  expect(await hitAreasShort(page, ".pg-btn, .run-link")).toEqual([]);
}

/**
 * The controls ``selector`` matches whose hit area is under 44 by 44 px. The hit area is what a
 * pointer reaches, the control's own box and any invisible extension of it (its ``::before``):
 * each drawn control is scrolled to the middle of the view and the page is asked what lies at
 * the outermost whole pixels of a 44 px span centred on it, left, right, above and below. All four
 * must land on the control. Controls
 * not drawn (a closed dialog's) are skipped; none drawn at all fails.
 */
export async function hitAreasShort(page: Page, selector: string): Promise<string[]> {
  const count = await page.locator(selector).count();
  const short: string[] = [];
  let drawn = 0;
  for (let i = 0; i < count; i += 1) {
    const control = page.locator(selector).nth(i);
    if (!(await control.isVisible())) continue;
    drawn += 1;
    // In the middle of the viewport, so no probe falls outside it.
    await control.evaluate((el) => {
      el.scrollIntoView({ block: "center", inline: "center" });
    });
    const missed = await control.evaluate((el) => {
      const box = el.getBoundingClientRect();
      const [cx, cy] = [box.left + box.width / 2, box.top + box.height / 2];
      // The first and the last whole pixel of a 44 px span centred on the control: a target of
      // 44 px or more covers both, one of 43 misses one.
      const [low, high] = [(c: number) => Math.ceil(c - 22), (c: number) => Math.floor(c + 22) - 1];
      const points: [number, number][] = [
        [low(cx), cy],
        [high(cx), cy],
        [cx, low(cy)],
        [cx, high(cy)],
      ];
      return points.flatMap(([x, y]) => {
        const hit = document.elementFromPoint(x, y);
        if (hit !== null && (hit === el || el.contains(hit))) return [];
        const what =
          hit === null
            ? "nothing"
            : `${hit.tagName.toLowerCase()}.${hit.getAttribute("class") ?? ""}`;
        return [`${String(Math.round(x - cx))},${String(Math.round(y - cy))} (${what})`];
      });
    });
    if (missed.length > 0) {
      const name = (await control.textContent())?.trim().slice(0, 40) ?? "";
      short.push(`${selector} #${String(i)} "${name}": misses ${missed.join(" ")}`);
    }
  }
  if (drawn === 0) short.push(`nothing drawn matches ${selector}`);
  // Scrolling moved the browser's starting point for Tab to the last control probed; put it
  // back at the start of the page, where a person's first Tab begins.
  await page.evaluate(() => {
    document.body.firstElementChild?.scrollIntoView({ block: "start" });
  });
  return short;
}

export async function cspViolations(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { cspViolations: string[] }).cspViolations);
}
