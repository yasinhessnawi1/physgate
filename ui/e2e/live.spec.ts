import { appendFileSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { RUNS } from "../playwright.config";
import { local, serve, type Started, stopServers } from "./serve";
import { cspViolations, THEMES, watch } from "./support";

/**
 * A running run's timeline follows its log as it grows. The run's log ends in a line its writer
 * has only half written; the real server, started by this file over a root of its own, is asked
 * again and again while the line stays half written, and the page shows nothing of it. Once the
 * test finishes the line, as the writer would, the page shows it, once: the rows are the rows a
 * fresh read of the whole log gives. The page acts on nothing and passes axe in both themes.
 */

const LIVE = join(RUNS, "live");
const RUN = "drive-live";
const LOG = join(LIVE, "runs", RUN, "events.jsonl");
/** The route the page follows the log by, from a line on. */
const FOLLOWED = /\/api\/runs\/0\/drive-live\/events\/from\/\d+$/;

let folder = "";
let live: Started = { url: "" };

test.beforeAll(async () => {
  test.setTimeout(180_000);
  folder = mkdtempSync(join(tmpdir(), "physgate-ui-e2e-live-"));
  const library = join(folder, "knowledge");
  mkdirSync(library, { mode: 0o700 });
  live = await serve(join(LIVE, "runs"), library);
});

test.afterAll(async () => {
  test.setTimeout(60_000);
  await stopServers(folder);
});

async function open(page: Page, theme: string) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${live.url}?theme=${theme}#/orchestration/run-timeline?run=0/${RUN}`);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

async function axeClean(page: Page) {
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(
    axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
  ).toEqual([]);
}

/** Every row's text, in order, so a row shown twice or left out is seen. */
async function rowsOf(page: Page): Promise<string[]> {
  return page.locator('section[aria-label="Timeline"] .pg-trow').allTextContents();
}

test("a running log is followed: a half-written line is never shown, and shown once when whole", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page, local(live.url));
  const answers: string[] = [];
  page.on("response", (response) => {
    if (FOLLOWED.test(new URL(response.url()).pathname))
      void response.text().then((body) => answers.push(body));
  });
  await open(page, "light");
  await expect(page.locator('[aria-label="The run shown"]')).toContainText("In progress · partial");
  const timeline = page.locator('section[aria-label="Timeline"]');
  await expect(timeline.locator(".pg-no-verdict")).toHaveCount(1);
  const before = await rowsOf(page);
  // The page asks again while the line is half written: nothing new is shown.
  await expect.poll(() => answers.length, { timeout: 30_000 }).toBeGreaterThanOrEqual(3);
  expect(await rowsOf(page)).toEqual(before);
  await expect(timeline.locator(".pg-verdict-fail")).toHaveCount(0);
  // No answer carried the half line: each ends its lines, and none is the half.
  const half = readFileSync(LOG, "utf8").split("\n").at(-1) ?? "";
  expect(half.length).toBeGreaterThan(0);
  for (const body of answers) {
    const { lines } = JSON.parse(body) as { lines: string };
    expect(lines === "" || lines.endsWith("\n")).toBe(true);
    expect(lines).not.toContain(half);
  }
  await axeClean(page);

  // The writer finishes the line: the gate's result is shown, once.
  appendFileSync(LOG, readFileSync(join(LIVE, "rest-of-line")));
  await expect(timeline.locator(".pg-trow .pg-verdict-fail")).toHaveCount(1, { timeout: 30_000 });
  await expect(timeline.locator(".pg-no-verdict")).toHaveCount(0);
  const followed = await rowsOf(page);
  expect(followed.length).toBeGreaterThan(before.length);
  await axeClean(page);
  // Nothing acts here: no button opens a confirmation.
  await expect(page.getByRole("button", { name: /…$/ })).toHaveCount(0);
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);

  // A fresh read of the whole log, in either theme, gives the rows the page followed to.
  for (const theme of THEMES) {
    await open(page, theme);
    await expect(timeline.locator(".pg-trow .pg-verdict-fail")).toHaveCount(1);
    expect(await rowsOf(page)).toEqual(followed);
    await axeClean(page);
  }
});
