import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { RUNS } from "../playwright.config";
import { PORT } from "./port";
import {
  cspViolations,
  hitAreasShort,
  namesNoCommand,
  saysNoMoreThanTheRecord,
  THEMES,
  watch,
} from "./support";

/**
 * A part of the plan decided in the browser (ARCH-122): the real server, started with an
 * operator, over the scripted run on the reference brief that asks which parts a person has,
 * held with its six parts open. At a phone's width, in both themes, a part is shown whole with
 * its three choices and no approve or reject, held to the design, axe clean, nothing outbound.
 * Then one part is had, one made and the rest found from the page, each through its
 * confirmation; the run is driven once more, as the run command would, and the page shows it
 * released.
 */

const ORIGIN = `http://127.0.0.1:${String(PORT)}`;
const REPO = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const VIEW = "run-parts-view";
const DECIDE = "run-parts-decide";

/** The operator's address as `physgate ui --operator` printed it; the token is in its fragment. */
function operatorUrl(): string {
  const started = JSON.parse(readFileSync(join(RUNS, "started.json"), "utf8")) as {
    operator_url: string;
  };
  return started.operator_url;
}

/** Open the operator's address, let the page take its token, then go to ``item`` of the run. */
async function open(page: Page, theme: string, run: string, item: string) {
  const address = new URL(operatorUrl());
  await page.goto(`/?theme=${theme}${address.hash}`);
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, `/collaboration/approval-queue?run=0/${run}&item=${item}`);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator(".pg-queue-item")).toBeVisible();
}

interface Decided {
  readonly item_id: string;
  readonly position?: string;
  readonly parts?: unknown;
}

async function decided(page: Page, run: string): Promise<readonly Decided[]> {
  const answer = await page.request.get(`${ORIGIN}/api/runs/0/${run}/queue`);
  expect(answer.status()).toBe(200);
  return ((await answer.json()) as { decided: Decided[] }).decided;
}

/** Record the choice the form holds, through its confirmation, and wait for the queue's line. */
async function record(page: Page, decision: string) {
  await page.getByRole("button", { name: "Record this choice…" }).click();
  const dialog = page.locator("dialog[open]");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Record", exact: true }).click();
  // The listing is read again, and the item shows the queue's own line in place of the choices.
  await expect(page.locator(".pg-queue-decided-text")).toHaveText(decision);
}

for (const theme of THEMES) {
  test(`a part is shown whole with its three choices at a phone's width (${theme})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const seen = await watch(page);
    await open(page, theme, VIEW, `${VIEW}-parts-1`);
    await expect(page.locator(".pg-queue-decision")).toHaveText("A part of the plan to decide");
    const component = page.locator(".pg-parts-component");
    await expect(component).toContainText("Drive gearmotors, 50:1 Micro Metal HPCB 6V");
    await expect(component).toContainText("Electrical");
    await expect(component).toContainText("Part 1 of 6");
    await expect(page.getByRole("radio", { name: /^Find it/ })).toBeChecked();
    await expect(page.getByRole("radio", { name: /^I have it/ })).toBeVisible();
    await expect(page.getByRole("radio", { name: /^I will make it/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /approve|reject/i })).toHaveCount(0);

    // By keyboard alone: the choices are one group, arrows move between them, the fields follow.
    await page.getByRole("radio", { name: /^Find it/ }).focus();
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("ArrowUp");
    await expect(page.getByRole("radio", { name: /^I have it/ })).toBeChecked();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Mass: value")).toBeFocused();
    await page.keyboard.type("0.0095");
    await expect(page.locator(".pg-parts-problems")).toContainText("Mass: a value needs its unit");
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Mass: unit")).toBeFocused();
    await page.keyboard.type("kg");
    await expect(page.locator(".pg-parts-problems")).toHaveCount(0);

    // Nothing wider than the screen, every control large enough to hit.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    expect(await hitAreasShort(page, ".pg-btn, .pg-parts-choice label")).toEqual([]);
    await namesNoCommand(page, `parts-${theme}`);
    await saysNoMoreThanTheRecord(page, `parts-${theme}`);
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" ")}`)).toEqual(
      [],
    );
    expect(seen.outbound).toEqual([]);
    expect(await cspViolations(page)).toEqual([]);
    const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
    if (evidence !== undefined)
      await page.screenshot({ path: `${evidence}/parts-${theme}.png`, fullPage: true });
  });
}

test("one part had, one made and the rest found from the page, and the run is released", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await open(page, "light", DECIDE, `${DECIDE}-parts-1`);

  await page.getByRole("radio", { name: /^I have it/ }).check();
  await page.getByLabel("Mass: value").fill("0.0095");
  await page.getByLabel("Mass: unit").fill("kg");
  await page.getByLabel("Stall current: value").fill("1.6");
  await page.getByLabel("Stall current: unit").fill("A");
  await record(page, "choose have");

  await open(page, "light", DECIDE, `${DECIDE}-parts-2`);
  await page.getByRole("radio", { name: /^I will make it/ }).check();
  await page.getByLabel("Mass: value").fill("0.012");
  await page.getByLabel("Mass: unit").fill("kg");
  await page.getByLabel("Text 1").fill("printed in PETG, walls at least 2 mm");
  await record(page, "choose make");

  for (const n of [3, 4, 5, 6]) {
    await open(page, "light", DECIDE, `${DECIDE}-parts-${String(n)}`);
    await expect(page.getByRole("radio", { name: /^Find it/ })).toBeChecked();
    await record(page, "choose find");
  }

  const lines = await decided(page, DECIDE);
  expect(lines.map((d) => d.position)).toEqual(["have", "make", "find", "find", "find", "find"]);
  expect(lines[0]?.parts).toEqual({
    declared: { mass: { unit: "kg", value: 0.0095 }, stall_current: { unit: "A", value: 1.6 } },
    texts: [],
  });
  expect(lines[1]?.parts).toEqual({
    declared: { mass: { unit: "kg", value: 0.012 } },
    texts: ["printed in PETG, walls at least 2 mm"],
  });

  // The run, driven once more as the run command would drive it, takes the decisions.
  const step = execFileSync("uv", ["run", "python", "tests/ui_parts_rig.py", RUNS, DECIDE], {
    cwd: REPO,
    encoding: "utf8",
    timeout: 180_000,
  });
  expect(step.trim().split("\n").at(-1)).toBe("done");

  await open(page, "light", DECIDE, `${DECIDE}-parts-1`);
  await expect(page.locator(".pg-parts-released")).toHaveText(
    "Every part is decided, and the run was released: 1 you have, 1 you will make, 4 to find.",
  );
});
