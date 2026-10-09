import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

/**
 * The smoke page end to end: the real server over runs the real loop made. Every request the
 * page makes that is not to this loopback server is aborted and counted, and the count must be
 * zero. So must the content-security-policy violations, and the accessibility violations in
 * both themes.
 */

const LOCAL = /^http:\/\/127\.0\.0\.1:8799\//;
const THEMES = ["light", "dark"] as const;

interface Watch {
  readonly outbound: string[];
  readonly api: Set<string>;
}

async function watch(page: Page): Promise<Watch> {
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

async function open(page: Page, theme: (typeof THEMES)[number], run: string) {
  await page.goto(`/?theme=${theme}#/home/run-records?run=${run}`);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText("matched its seal")).toBeVisible();
}

async function cspViolations(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { cspViolations: string[] }).cspViolations);
}

for (const theme of THEMES) {
  test(`the smoke page reads every route and names every figure's source (${theme})`, async ({
    page,
  }) => {
    const seen = await watch(page);
    await open(page, theme, "0/run-observe");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.locator('[role="alert"]')).toHaveCount(0);
    for (const route of [
      "config",
      "events",
      "ledger",
      "gate-events",
      "graph",
      "cost/2026-09-27",
      "trajectories/:session",
    ]) {
      expect([...seen.api]).toContain(`/api/runs/0/run-observe/${route}`);
    }
    expect([...seen.api]).toEqual(expect.arrayContaining(["/api/runs", "/api/prices"]));

    // Every quantity on the page sits inside something that names its source.
    const unsourced = await page
      .locator(".quantity")
      .evaluateAll((all) =>
        all.filter((q) => q.closest("[data-source]") === null).map((q) => q.textContent),
      );
    expect(await page.locator(".quantity").count()).toBeGreaterThan(0);
    expect(unsourced).toEqual([]);

    // Observe mode: the failing check reads "would fail", and nothing observed is a filled verdict.
    await expect(page.getByText("Would fail · not enforced").first()).toBeVisible();
    await expect(page.locator(".observed .verdict-fail, .observed.verdict-fail")).toHaveCount(0);
    const gateChecks = page.locator('section[aria-label="Gate checks"]');
    await expect(gateChecks.locator(".verdict-pass, .verdict-fail, .verdict-warn")).toHaveCount(0);
    const ledgerGates = page.locator('section[aria-label="Task ledger"] tbody td:nth-child(4)');
    await expect(ledgerGates.locator(".verdict-pass, .verdict-fail, .verdict-warn")).toHaveCount(0);
    await expect(page.locator(".topbar .gate-mode-observe")).toBeVisible();

    // Unchecked is counted after the separator, never with the evaluated.
    await expect(page.locator(".tally-evaluated .verdict-unchecked")).toHaveCount(0);

    // The design graph is drawn from the run's journal.
    expect(await page.locator(".graph-node").count()).toBeGreaterThan(0);

    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
    ).toEqual([]);

    expect(seen.outbound).toEqual([]);
    expect(await cspViolations(page)).toEqual([]);

    const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
    if (evidence !== undefined) {
      await page.screenshot({ path: `${evidence}/smoke-page-${theme}.png`, fullPage: true });
    }
  });
}

test("a gated run's failing check is a filled fail", async ({ page }) => {
  const seen = await watch(page);
  await open(page, "light", "0/run-on");
  await expect(page.locator(".topbar .gate-mode-on")).toBeVisible();
  await expect(page.locator("td .verdict-fail").first()).toBeVisible();
  expect(seen.outbound).toEqual([]);
});

test("an area with no views says so", async ({ page }) => {
  const seen = await watch(page);
  await page.goto("/#/collaboration");
  await expect(page.getByText("No views in this area yet")).toBeVisible();
  await expect(page.locator(".topbar-area")).toContainText("Human–AI collaboration");
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(axe.violations).toEqual([]);
  expect(seen.outbound).toEqual([]);
});

test("under 760 px the sidebar stacks above the content", async ({ page }) => {
  await watch(page);
  await page.setViewportSize({ width: 600, height: 900 });
  await open(page, "light", "0/run-clean");
  const sidebar = await page.locator(".sidebar").boundingBox();
  const content = await page.locator(".content").boundingBox();
  expect(sidebar).not.toBeNull();
  expect(content).not.toBeNull();
  expect((sidebar?.y ?? 0) + (sidebar?.height ?? 0)).toBeLessThanOrEqual((content?.y ?? 0) + 1);
});

test("a planted outbound request is stopped and seen", async ({ page }) => {
  // Two layers: the server's content security policy stops the request in the browser and
  // records a violation; anything that got past it would reach the route block and be counted.
  // The detector is the union, so a request is never stopped silently.
  const seen = await watch(page);
  await open(page, "light", "0/run-clean");
  await page.evaluate(() => {
    const img = document.createElement("img");
    img.src = "https://example.org/pixel.png";
    document.body.append(img);
  });
  await expect
    .poll(
      async () =>
        seen.outbound.length +
        (await cspViolations(page)).filter((v) => v.includes("example.org")).length,
    )
    .toBeGreaterThan(0);
});
