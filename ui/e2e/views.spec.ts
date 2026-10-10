import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  bindingStylesHold,
  cspViolations,
  styles,
  THEMES,
  TRANSPARENT,
  watch,
  type Watch,
} from "./support";

/**
 * The graph and run views end to end: the real server over runs the real loop made, the
 * three-mode plan among them with the real physics gate's records. In both themes each view must
 * render without a refusal, name the source of every quantity, keep the design's binding styling
 * rules, pass axe, make no outbound request and break no content-security rule. Under observe
 * nothing a gate decided is drawn as a filled verdict.
 */

async function open(page: Page, theme: string, path: string) {
  await page.goto(`/?theme=${theme}#${path}`);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator('[role="alert"]')).toHaveCount(0);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

async function common(page: Page, seen: Watch, shot: string) {
  const unsourced = await page
    .locator(".quantity")
    .evaluateAll((all) =>
      all.filter((q) => q.closest("[data-source]") === null).map((q) => q.textContent),
    );
  expect(await page.locator(".quantity").count()).toBeGreaterThan(0);
  expect(unsourced).toEqual([]);
  for (const q of await styles(page, ".quantity", ["font-family", "white-space"])) {
    expect(q["font-family"]).toContain("IBM Plex Mono");
    expect(q["white-space"]).toBe("nowrap");
  }
  const heights = await page
    .locator(".button, .run-link, .segmented button, button.graph-node")
    .evaluateAll((all) => all.map((el) => el.getBoundingClientRect().height));
  expect(heights.length).toBeGreaterThan(0);
  for (const height of heights) expect(height).toBeGreaterThanOrEqual(44);
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(
    axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
  ).toEqual([]);
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);
  const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
  if (evidence !== undefined)
    await page.screenshot({ path: `${evidence}/${shot}.png`, fullPage: true });
}

/** Nothing the gate decided under observe is a filled verdict, and the observe badge is hatched. */
async function observedNeverFilled(page: Page, scope: string) {
  await expect(page.locator(".topbar .gate-mode-observe")).toBeVisible();
  await expect(
    page.locator(`${scope} .verdict-pass, ${scope} .verdict-fail, ${scope} .verdict-warn`),
  ).toHaveCount(0);
  for (const o of await styles(page, `${scope} .observed`, [
    "border-top-style",
    "background-color",
  ])) {
    expect(o).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
  }
  await expect(page.locator(".tally-evaluated .verdict-unchecked")).toHaveCount(0);
}

for (const theme of THEMES) {
  test(`the design graph: nodes are buttons, a node opens with its quantities, edges and history (${theme})`, async ({
    page,
  }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/design-graph?run=0/drive-observe");
    const nodes = page.locator("button.graph-node");
    await expect(nodes).toHaveCount(6);
    await nodes
      .filter({ has: page.locator(".graph-node-id", { hasText: /^electrical\.drive$/ }) })
      .click();
    const inspector = page.locator('aside[aria-label="Node inspector"]');
    await expect(inspector.locator(".quantity")).toHaveCount(3);
    await expect(inspector.locator('section[aria-label="Constrains"]')).toContainText(
      "electrical.battery",
    );
    await expect(inspector.locator('section[aria-label="Constrained by"]')).toContainText(
      "electrical.driver",
    );
    await expect(inspector.locator(".history-entry")).toHaveCount(1);
    await expect(page.locator('section[aria-label="Nodes"] tbody tr')).toHaveCount(6);
    expect([...seen.api]).toContain("/api/runs/0/drive-observe/graph/history/electrical.drive");
    await common(page, seen, `design-graph-${theme}`);
  });

  test(`the design graph's diff between two revisions (${theme})`, async ({ page }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/design-graph?run=0/drive-observe&diff=1-6");
    const diff = page.locator('section[aria-label="Diff"]');
    await expect(diff.locator('table[aria-label="Change list"] tbody tr')).toHaveCount(5);
    await expect(diff).toContainText("View: rows are marked");
    await common(page, seen, `design-graph-diff-${theme}`);
  });

  test(`the run timeline under observe (${theme})`, async ({ page }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/run-timeline?run=0/drive-observe&pair=0/drive-on");
    await expect(page.locator(".lane")).toHaveCount(3);
    const gate = page.locator(".track .segment-gate-observe");
    await expect(gate).toHaveCount(1);
    await expect(gate).toContainText("would fail · not enforced");
    for (const g of await styles(page, ".segment-gate-observe", [
      "border-top-style",
      "background-image",
    ])) {
      expect(g["border-top-style"]).toBe("dashed");
      expect(g["background-image"]).not.toBe("none");
    }
    await observedNeverFilled(page, 'section[aria-label="Gate checks"]');
    await expect(page.locator('table[aria-label="By attribution"]')).toContainText("all routing");
    await bindingStylesHold(page);
    await common(page, seen, `run-timeline-observe-${theme}`);
  });

  test(`the run timeline of a gated run with three repairs (${theme})`, async ({ page }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/run-timeline?run=0/drive-on");
    await expect(page.locator(".lane")).toHaveCount(5);
    await expect(page.locator(".track .segment-gate-on")).toHaveCount(3);
    await expect(page.locator(".lane").nth(2)).toContainText("repair of gate · power");
    await bindingStylesHold(page);
    await common(page, seen, `run-timeline-on-${theme}`);
  });

  test(`gate checks under observe, read against the gated run (${theme})`, async ({ page }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/gate-checks?run=0/drive-observe&pair=0/drive-on");
    await observedNeverFilled(page, 'section[aria-label="Gate checks"]');
    await expect(page.getByText("0 evaluated · a pass over nothing").first()).toBeVisible();
    await expect(page.locator(".why-row").first()).toContainText("Why:");
    await expect(
      page.locator('section[aria-label="Same plan, another gate mode"] .gate-mode-on').first(),
    ).toBeVisible();
    await bindingStylesHold(page);
    await common(page, seen, `gate-checks-observe-${theme}`);
  });

  test(`gate checks of the gated run (${theme})`, async ({ page }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/gate-checks?run=0/drive-on");
    await expect(
      page.locator('section[aria-label="Gate checks"] td .verdict-fail').first(),
    ).toBeVisible();
    await expect(page.locator(".tally-evaluated .verdict-unchecked")).toHaveCount(0);
    await bindingStylesHold(page);
    await common(page, seen, `gate-checks-on-${theme}`);
  });
}

test("the gate-off run's checks say the gate did not run, and show no result", async ({ page }) => {
  const seen = await watch(page);
  await open(page, "light", "/orchestration/gate-checks?run=0/drive-off");
  await expect(page.getByText("The gate did not run")).toBeVisible();
  await expect(page.locator(".checks-table")).toHaveCount(0);
  expect(seen.outbound).toEqual([]);
});

test("g then g, g then t: two keys go to the graph and the timeline, and keep the run", async ({
  page,
}) => {
  await watch(page);
  await open(page, "light", "/orchestration/gate-checks?run=0/drive-on");
  await page.keyboard.press("g");
  await page.keyboard.press("t");
  await expect(page).toHaveURL(/#\/orchestration\/run-timeline\?run=0%2Fdrive-on$/);
  await page.keyboard.press("g");
  await page.keyboard.press("g");
  await expect(page).toHaveURL(/#\/orchestration\/design-graph\?run=0%2Fdrive-on$/);
  await page.keyboard.press("t");
  await expect(page).toHaveURL(/design-graph/);
});
