import { readFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { RUNS } from "../playwright.config";
import { cspViolations, THEMES, watch } from "./support";

/**
 * The shell in the browser, over the real server: the palette, notifications, the dock, theme
 * and density, the top bar and its run chip, the About page, and the order Escape closes things
 * in. Nothing leaves the origin and no content-security rule breaks.
 */

const VIEWS = ["Run records", "Approval queue", "Design graph", "Run timeline", "Gate checks"];

function operatorHash(): string {
  const started = JSON.parse(readFileSync(join(RUNS, "started.json"), "utf8")) as {
    operator_url: string;
  };
  return new URL(started.operator_url).hash;
}

async function settle(page: Page) {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
}

async function asOperator(page: Page, path: string) {
  await page.goto(`/?theme=light${operatorHash()}`);
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, path);
  await settle(page);
}

test("⌘K opens the palette with focus in its input, and Go to reaches every view", async ({
  page,
}) => {
  const seen = await watch(page);
  await page.goto("/#/orchestration/gate-checks?run=0/drive-on");
  await settle(page);
  for (const keys of ["Meta+k", "Control+k"]) {
    await page.keyboard.press(keys);
    const palette = page.locator("dialog.pg-palette[open]");
    await expect(palette).toBeVisible();
    await expect(palette.locator("input")).toBeFocused();
    const goTo = palette.locator('[role="group"][aria-label="Go to"] [role="option"]');
    await expect(goTo).toHaveText(VIEWS);
    await page.keyboard.press("Escape");
    await expect(palette).toHaveCount(0);
  }
  for (const title of VIEWS) {
    await page.keyboard.press("Control+k");
    await page.keyboard.type(title);
    await page.keyboard.press("Enter");
    await expect(page.locator(".pg-page-title")).toHaveText(title);
    // The run chosen is kept.
    expect(page.url()).toContain("run=0%2Fdrive-on");
    await settle(page);
  }
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);
});

test("a writing entry opens its confirmation, and Escape closes the dialog, then the palette, then notifications", async ({
  page,
}) => {
  const seen = await watch(page);
  await asOperator(page, "/collaboration/approval-queue?run=0/run-esc-view");
  await expect(page.locator(".queue-detail")).toBeVisible();
  const notices = page.locator('section[aria-label="Notifications"]');
  const palette = page.locator("dialog.pg-palette[open]");
  const confirm = page.locator("dialog.pg-dialog[open]");

  // Notifications, then the palette over them: Escape closes the palette first.
  await page.getByRole("button", { name: "Notifications" }).click();
  await expect(notices).toBeVisible();
  await page.keyboard.press("Control+k");
  await expect(palette).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toHaveCount(0);
  await expect(notices).toBeVisible();

  // A writing entry opens the same confirmation as the button; Escape closes it first.
  await page.keyboard.press("Control+k");
  await page.keyboard.type("Approve");
  const entry = palette.locator('[role="option"]', { hasText: "Approve…" });
  await expect(entry).toHaveAttribute("aria-disabled", "false");
  await page.keyboard.press("Enter");
  await expect(confirm).toBeVisible();
  await expect(confirm).toContainText("This writes: one line appended to queue_decisions.jsonl");
  await expect(confirm.locator("button", { hasText: "Cancel" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(confirm).toHaveCount(0);
  await expect(notices).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(notices).toHaveCount(0);

  // A rejection needs its note, from the palette as from the button.
  await page.keyboard.press("Control+k");
  await page.keyboard.type("Reject");
  await expect(palette.locator('[role="option"]', { hasText: "Reject…" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await page.keyboard.press("Escape");
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);
});

test("notifications list every open item across the runs, a sentence first, and an unreadable run's refusal", async ({
  page,
}) => {
  const seen = await watch(page);
  const runs = (await (await page.request.get("/api/runs")).json()) as {
    runs: { root: number; name: string; error?: string }[];
  };
  let open = 0;
  for (const run of runs.runs.filter((r) => r.error === undefined)) {
    const listing = (await (
      await page.request.get(`/api/runs/${String(run.root)}/${run.name}/queue`)
    ).json()) as { open: unknown[] };
    open += listing.open.length;
  }
  expect(open).toBeGreaterThan(0);
  await page.goto("/#/home/run-records?run=0/run-clean");
  await settle(page);
  await page.getByRole("button", { name: "Notifications" }).click();
  const notices = page.locator('section[aria-label="Notifications"]');
  await expect(notices.locator(".pg-notice-link")).toHaveCount(open);
  for (const link of await notices.locator(".pg-notice-link").all()) {
    const first = await link.evaluate((l) => l.firstElementChild?.className);
    expect(first).toBe("pg-notice-sentence");
    await expect(link.locator(".pg-id").first()).toBeVisible();
  }
  expect(seen.outbound).toEqual([]);

  // One run's queue refused: that run says so, the others still list.
  const page2 = await page.context().newPage();
  await watch(page2);
  await page2.route("**/api/runs/0/run-esc-view/queue", (route) =>
    route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        error: "the queue holds a line no writer could have written",
        context: {},
      }),
    }),
  );
  await page2.goto("/#/home/run-records?run=0/run-clean");
  await settle(page2);
  await page2.getByRole("button", { name: "Notifications" }).click();
  const refused = page2.locator('section[aria-label="Notifications"] [role="alert"]');
  await expect(refused).toContainText("The queue of run-esc-view could not be read");
  await expect(refused).toContainText("the queue holds a line no writer could have written");
  await page2.close();
});

test("the collaborator's dock is a placeholder; below 1600 px it overlays the content", async ({
  page,
}) => {
  const seen = await watch(page);
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/#/orchestration/run-timeline?run=0/drive-on");
    await settle(page);
    const before = await page.locator(".pg-content").boundingBox();
    await page.keyboard.press("Control+j");
    const panel = page.locator(".pg-dock-panel");
    await expect(panel).toBeVisible();
    await expect(panel).toHaveText("The collaborator is not available in this build.");
    await expect(
      panel.locator("input, textarea, button, [contenteditable], .pg-msg, .pg-change"),
    ).toHaveCount(0);
    const after = await page.locator(".pg-content").boundingBox();
    expect(after?.width).toBe(before?.width);
    await page.keyboard.press("Meta+j");
    await expect(panel).toHaveCount(0);
  }
  // At 1600 px and wider the open dock takes its own room.
  await page.setViewportSize({ width: 1700, height: 900 });
  await page.reload();
  await settle(page);
  const wide = await page.locator(".pg-main").boundingBox();
  await page.keyboard.press("Control+j");
  await expect(page.locator(".pg-dock-panel")).toBeVisible();
  const narrowed = await page.locator(".pg-main").boundingBox();
  expect(narrowed?.width).toBeLessThan(wide?.width ?? 0);
  // The rail shows the collaborator's icon and no count.
  await expect(page.locator('.pg-dock-rail [data-icon="messages-square"]')).toBeVisible();
  await expect(page.locator(".pg-dock-rail")).toHaveText("");
  expect(seen.outbound).toEqual([]);
});

test("theme follows the system until chosen, is kept per viewer, and the page renders the same when storage throws", async ({
  browser,
}) => {
  const dark = await browser.newContext({ colorScheme: "dark" });
  const page = await dark.newPage();
  await watch(page);
  await page.goto("/#/home/run-records?run=0/run-clean");
  await settle(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: /^Theme/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /^Density/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "comfortable");
  await page.reload();
  await settle(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("html")).toHaveAttribute("data-density", "comfortable");
  await dark.close();

  const blocked = await browser.newContext({ colorScheme: "light" });
  const bare = await blocked.newPage();
  const errors: string[] = [];
  bare.on("pageerror", (e) => errors.push(e.message));
  await bare.addInitScript(() => {
    const refuse = () => {
      throw new DOMException("blocked", "SecurityError");
    };
    Storage.prototype.getItem = refuse;
    Storage.prototype.setItem = refuse;
  });
  await bare.goto("/#/home/run-records?run=0/run-clean");
  await settle(bare);
  await expect(bare.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(bare.locator("html")).toHaveAttribute("data-density", "compact");
  await expect(bare.locator(".pg-page-title")).toHaveText("Run records");
  await bare.getByRole("button", { name: /^Density/ }).click();
  await expect(bare.locator("html")).toHaveAttribute("data-density", "comfortable");
  expect(errors).toEqual([]);
  await blocked.close();
});

test("the top bar keeps the title whole, names the operator, and says read only without the token", async ({
  page,
}) => {
  await watch(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/#/orchestration/design-graph?run=0/drive-observe");
  await settle(page);
  const title = page.locator(".pg-page-title");
  expect(
    await title.evaluate((t) => ({
      fits: t.scrollWidth <= t.clientWidth,
      cut: getComputedStyle(t).textOverflow,
    })),
  ).toEqual({ fits: true, cut: "clip" });
  await expect(page.locator(".pg-avatar")).toHaveAttribute("aria-label", "e2e-operator");
  await expect(page.locator(".pg-read-only")).toHaveText("Read only");
  // Narrow: the group crumb and the search label go first; the title stays.
  await page.setViewportSize({ width: 820, height: 900 });
  await expect(page.locator(".pg-crumb-group")).toBeHidden();
  await expect(title).toBeVisible();
  // As the operator, the page is not read only.
  await asOperator(page, "/collaboration/approval-queue?run=0/run-esc-view");
  await expect(page.locator(".pg-read-only")).toHaveCount(0);
});

test("the run chip shows each recorded OS-layer state, and never an unrecorded one as present", async ({
  page,
}) => {
  await watch(page);
  const config = (await (await page.request.get("/api/runs/0/drive-on/config")).json()) as {
    config: Record<string, unknown>;
  };
  const states: [unknown, string][] = [
    [{ state: "present", mechanism: "bubblewrap", claude_version: "x" }, "OS layer · bubblewrap"],
    [{ state: "absent", reason: "bwrap missing", no_os_protection: false }, "OS layer absent"],
    [{ state: "absent", reason: "native Windows", no_os_protection: true }, "No OS protection"],
    [undefined, "OS layer not recorded"],
  ];
  for (const [layer, words] of states) {
    await page.unrouteAll();
    await watch(page);
    const rest = Object.fromEntries(
      Object.entries(config.config).filter(([key]) => key !== "os_layer"),
    );
    const body = { ...config, config: layer === undefined ? rest : { ...rest, os_layer: layer } };
    await page.route("**/api/runs/0/drive-on/config", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(body) }),
    );
    await page.goto("/#/orchestration/gate-checks?run=0/drive-on");
    await settle(page);
    const chip = page.locator('[aria-label="The run shown"]');
    await expect(chip).toContainText(words);
    await expect(chip.locator(".pg-gate-on")).toBeVisible();
    if (layer === undefined) await expect(chip).not.toContainText("bubblewrap");
  }
});

for (const theme of THEMES) {
  test(`the About page carries the licences, and axe is clean (${theme})`, async ({ page }) => {
    const seen = await watch(page);
    await page.goto(`/?theme=${theme}#/about`);
    const about = page.locator(".pg-about");
    await expect(about).toBeVisible();
    for (const summary of await about.locator("summary").all()) await summary.click();
    await expect(about).toContainText("SIL OPEN FONT LICENSE Version 1.1");
    await expect(about).toContainText("ISC License");
    await expect(about).toContainText("Instrument Sans");
    await expect(about).toContainText("JetBrains Mono");
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(axe.violations.map((v) => v.id)).toEqual([]);
    expect(seen.outbound).toEqual([]);
    expect(await cspViolations(page)).toEqual([]);
  });

  test(`the shell is clean to axe at 1440 and 1280 (${theme})`, async ({ page }) => {
    await watch(page);
    for (const width of [1440, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/?theme=${theme}#/home/run-records?run=0/run-clean`);
      await settle(page);
      await page.getByRole("button", { name: "Notifications" }).click();
      await expect(page.locator('section[aria-label="Notifications"]')).toBeVisible();
      await settle(page);
      await page.keyboard.press("Control+j");
      const axe = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
      ).toEqual([]);
    }
  });
}
