import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { RUNS } from "../playwright.config";

/**
 * The two kinds of item a person met in a recorded run, end to end on the real server: a failed
 * contract's, with its two positions, and a review that reached no verdict. On both, the
 * decision controls come before the long finding, so they are in view when the item opens; and a
 * page that cannot decide says so at the top of the item, and says where the address that can
 * decide is: the run's ui.out.
 */

const KINDS = [
  { run: "run-contract", buttons: 4 },
  { run: "run-unavailable", buttons: 2 },
] as const;

function operatorUrl(): string {
  const started = JSON.parse(readFileSync(join(RUNS, "started.json"), "utf8")) as {
    operator_url: string;
  };
  return started.operator_url;
}

async function open(page: Page, run: string, asOperator: boolean) {
  const address = new URL(operatorUrl());
  await page.goto(asOperator ? `/${address.hash}` : "/");
  if (asOperator) await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
  // The app routes by the address's fragment once it has started: wait for it before moving.
  await expect(page.getByRole("link", { name: "Queue" }).first()).toBeVisible({ timeout: 30_000 });
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, `/collaboration/approval-queue?run=0/${run}`);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(".pg-queue-item")).toBeVisible({ timeout: 30_000 });
}

/** The top of ``selector``'s first match, as the browser lays it out. */
async function top(page: Page, selector: string): Promise<number> {
  const box = await page.locator(selector).first().boundingBox();
  expect(box, `nothing on the page matches ${selector}`).not.toBeNull();
  return box?.y ?? Number.NaN;
}

for (const { run, buttons } of KINDS) {
  test(`the decision controls come before the finding and are in view (${run})`, async ({
    page,
  }) => {
    await open(page, run, true);
    const actions = page.locator(".pg-queue-actions > .pg-btn");
    await expect(actions).toHaveCount(buttons);
    // Reject needs no seal, so the page that can decide offers it on either kind.
    await expect(page.locator(".pg-queue-actions > .pg-btn-reject")).toBeEnabled();
    await expect(page.locator(".pg-queue-why-not")).toHaveCount(0);
    expect(await top(page, ".pg-queue-actions")).toBeLessThan(await top(page, ".pg-queue-finding"));
    await expect(page.locator(".pg-queue-actions")).toBeInViewport();
  });

  test(`a page that cannot decide says so at the top and names the run's ui.out (${run})`, async ({
    page,
  }) => {
    await open(page, run, false);
    const notice = page.locator(".pg-queue-why-not");
    await expect(notice).toContainText("operator address");
    await expect(notice).toContainText("ui.out");
    await expect(notice).toBeInViewport();
    expect(await top(page, ".pg-queue-why-not")).toBeLessThan(await top(page, ".pg-queue-finding"));
    for (const button of await page.locator(".pg-queue-actions > .pg-btn").all())
      await expect(button).toBeDisabled();
  });
}
