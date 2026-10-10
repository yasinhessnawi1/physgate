import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { bindingStylesHold, cspViolations, styles, THEMES, TRANSPARENT, watch } from "./support";

/**
 * The smoke page end to end: the real server over runs the real loop made. Every request the
 * page makes that is not to this loopback server is aborted and counted, and the count must be
 * zero. So must the content-security-policy violations, and the accessibility violations in
 * both themes.
 */

async function open(page: Page, theme: (typeof THEMES)[number], run: string) {
  await page.goto(`/?theme=${theme}#/home/run-records?run=${run}`);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText("matched its seal")).toBeVisible();
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

    // An observe result is drawn dashed and unfilled, never as a filled verdict; the observe
    // badge is hatched. A recorded verdict (the reviews' passes) is filled, so the two differ.
    for (const o of await styles(page, ".observed", ["border-top-style", "background-color"])) {
      expect(o).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
    }
    for (const filled of await styles(page, ".verdict-pass", ["background-color"])) {
      expect(filled["background-color"]).not.toBe(TRANSPARENT);
    }
    for (const badge of await styles(page, ".gate-mode-observe", ["background-image"])) {
      expect(badge["background-image"]).not.toBe("none");
    }
    await bindingStylesHold(page);

    // The keyboard focus ring: 2 px, solid, in the accent.
    await page.keyboard.press("Tab");
    const ring = await page.evaluate(() => {
      const focused = document.activeElement;
      if (focused === null) return null;
      const computed = getComputedStyle(focused);
      return [computed.outlineStyle, computed.outlineWidth];
    });
    expect(ring).toEqual(["solid", "2px"]);

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
  for (const badge of await styles(page, ".gate-mode-on", ["background-image"])) {
    expect(badge["background-image"]).toBe("none");
  }
  for (const filled of await styles(page, "td .verdict-fail", [
    "border-top-style",
    "background-color",
  ])) {
    expect(filled["border-top-style"]).toBe("solid");
    expect(filled["background-color"]).not.toBe(TRANSPARENT);
  }
  expect(seen.outbound).toEqual([]);
});

test("a ledger the server refuses is shown as a refusal with its reason, and nothing partial", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "light", "0/run-refused");
  const ledger = page.locator('section[aria-label="Task ledger"]');
  const alert = ledger.locator('[role="alert"]');
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("Task ledger: not shown");
  await expect(alert).toContainText("the ledger holds a record this class could not have written");
  await expect(alert).toContainText("422");
  await expect(ledger.locator("table")).toHaveCount(0);
  // The rest of the run still renders: one refused record does not hide the others.
  await expect(page.locator('section[aria-label="Gate checks"] table')).toBeVisible();
  await bindingStylesHold(page);
  expect(seen.outbound).toEqual([]);
});

test("an area with no views says so", async ({ page }) => {
  const seen = await watch(page);
  // Simulation has no views yet (its views arrive with the simulation records).
  await page.goto("/#/simulation");
  await expect(page.getByText("No views in this area yet")).toBeVisible();
  await expect(page.locator(".topbar-area")).toContainText("Simulation");
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
