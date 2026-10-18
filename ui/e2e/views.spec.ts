import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  bindingStylesHold,
  hitAreasShort,
  cspViolations,
  namesNoCommand,
  saysNoMoreThanTheRecord,
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
    .locator(".pg-quantity")
    .evaluateAll((all) =>
      all.filter((q) => q.closest("[data-source]") === null).map((q) => q.textContent),
    );
  expect(await page.locator(".pg-quantity").count()).toBeGreaterThan(0);
  expect(unsourced).toEqual([]);
  for (const q of await styles(page, ".pg-quantity", ["font-family", "white-space"])) {
    expect(q["font-family"]).toContain("JetBrains Mono");
    expect(q["white-space"]).toBe("nowrap");
  }
  expect(await hitAreasShort(page, ".pg-btn, .run-link, .pg-seg button, button.pg-node")).toEqual(
    [],
  );
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

/** No text in any table of the view is cut: each fits its region and every cell holds its text. */
async function nothingCut(page: Page) {
  const overflow = await page.locator(".pg-scroll-table > table").evaluateAll((tables) =>
    tables.flatMap((table) => {
      const region = table.parentElement;
      const wide =
        region !== null && table.scrollWidth > region.clientWidth + 1
          ? ["the table is wider than its region"]
          : [];
      const cells = [...table.querySelectorAll<HTMLElement>("td, th")]
        .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
        .map((cell) => cell.textContent.slice(0, 60));
      return [...wide, ...cells];
    }),
  );
  expect(await page.locator(".pg-scroll-table > table").count()).toBeGreaterThan(0);
  expect(overflow).toEqual([]);
}

/** Every run in the picker reads differently from every other. */
async function runsDistinct(page: Page) {
  const labels = await page
    .locator('nav[aria-label="Runs"] .run-link')
    .evaluateAll((links) => links.map((l) => l.textContent.replace(/\s+/g, " ").trim()));
  expect(labels.length).toBeGreaterThan(1);
  expect(new Set(labels).size).toBe(labels.length);
}

/** Nothing the gate decided under observe is a filled verdict, and the observe badge is hatched. */
async function observedNeverFilled(page: Page, scope: string) {
  await expect(page.locator(".pg-topbar .pg-gate-observe")).toBeVisible();
  await expect(
    page.locator(`${scope} .pg-verdict-pass, ${scope} .pg-verdict-fail, ${scope} .pg-verdict-warn`),
  ).toHaveCount(0);
  for (const o of await styles(page, `${scope} .pg-observed`, [
    "border-top-style",
    "background-color",
  ])) {
    expect(o).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
  }
  await expect(page.locator(".pg-tally-evaluated .pg-verdict-unchecked")).toHaveCount(0);
}

for (const theme of THEMES) {
  test(`gate checks under observe, read against the gated run (${theme})`, async ({ page }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/gate-checks?run=0/drive-observe&pair=0/drive-on");
    await observedNeverFilled(page, 'section[aria-label="Gate checks"]');
    await expect(page.getByText("0 evaluated · a pass over nothing").first()).toBeVisible();
    await expect(page.locator(".why-row").first()).toContainText("Why:");
    await nothingCut(page);
    await runsDistinct(page);
    expect([...seen.api]).toEqual(
      expect.arrayContaining([
        "/api/runs/0/drive-observe/gate-checks",
        "/api/runs/0/drive-on/gate-checks",
      ]),
    );
    await expect(page.locator(".pg-tally-over-nothing").first()).toContainText("over nothing");
    const measuredOfUnchecked = await page
      .locator('section[aria-label="Gate checks"] tr:has(.pg-verdict-unchecked) td:nth-child(5)')
      .allTextContents();
    expect(measuredOfUnchecked.length).toBeGreaterThan(0);
    for (const text of measuredOfUnchecked) expect(text).not.toMatch(/pass|evaluated/);
    const paired = await page
      .locator('nav[aria-label="Runs of the same brief and seed"] .run-link')
      .evaluateAll((links) => links.map((l) => l.textContent.replace(/\s+/g, " ").trim()));
    expect(paired.length).toBeGreaterThan(2);
    expect(new Set(paired).size).toBe(paired.length);
    await expect(
      page.locator('section[aria-label="Same plan, another gate mode"] .pg-gate-on').first(),
    ).toBeVisible();
    await bindingStylesHold(page);
    await common(page, seen, `gate-checks-observe-${theme}`);
  });

  test(`gate checks of the gated run (${theme})`, async ({ page }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/gate-checks?run=0/drive-on");
    await expect(
      page.locator('section[aria-label="Gate checks"] td .pg-verdict-fail').first(),
    ).toBeVisible();
    await expect(page.locator(".pg-tally-evaluated .pg-verdict-unchecked")).toHaveCount(0);
    await nothingCut(page);
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

test("the smoke page's runs read differently from each other too", async ({ page }) => {
  await watch(page);
  await open(page, "light", "/home/run-records?run=0/run-clean");
  await runsDistinct(page);
});

test("a gated run read against an observed one: the paired card is never a filled verdict", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "light", "/orchestration/gate-checks?run=0/drive-on&pair=0/drive-observe");
  const paired = page.locator('section[aria-label="Same plan, another gate mode"]');
  await expect(paired.locator(".paired-body .pg-gate-observe")).toBeVisible();
  await expect(paired.locator(".pg-verdict-pass, .pg-verdict-fail, .pg-verdict-warn")).toHaveCount(
    0,
  );
  await expect(paired.locator(".pg-observed").first()).toBeVisible();
  for (const o of await styles(
    page,
    'section[aria-label="Same plan, another gate mode"] .pg-observed',
    ["border-top-style", "background-color"],
  ))
    expect(o).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
  expect(seen.outbound).toEqual([]);
});

test("no screen over any recorded run shows a terminal command", async ({ page, request }) => {
  test.setTimeout(600_000);
  const listed = (await (await request.get("/api/runs")).json()) as {
    runs: { root: number; name: string }[];
  };
  expect(listed.runs.length).toBeGreaterThan(3);
  const views = [
    "/home/overview",
    "/home/run-records",
    "/orchestration/design-graph",
    "/orchestration/run-timeline",
    "/orchestration/gate-checks",
    "/collaboration/approval-queue",
  ];
  for (const run of listed.runs) {
    for (const view of views) {
      const query = new URLSearchParams({ run: `${String(run.root)}/${run.name}` });
      const path = `${view}?${query.toString()}`;
      await page.goto(`/?theme=light#${path}`);
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
      await namesNoCommand(page, path);
      await saysNoMoreThanTheRecord(page, path);
    }
  }
});
