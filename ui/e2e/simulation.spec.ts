import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  bindingStylesHold,
  cspViolations,
  hitAreasShort,
  namesNoCommand,
  saysNoMoreThanTheRecord,
  THEMES,
  watch,
  type Watch,
} from "./support";

/**
 * The Simulation screen end to end: the real server over runs whose control sessions recorded
 * their step, their loop's frequency response and their edge runs through the real loop, each
 * record collected and sealed by the real collector and judged by the real gate. In both themes
 * and at both widths the screen passes axe, scrolls nowhere sideways but inside a plot's own data
 * region, leads every row and heading with words, keeps every value whole with its unit and its
 * source, draws no what-if and nothing that acts, asks the server only for its own routes and
 * the run's, and makes no outbound request. Then each fixture run shows its own case: a broken
 * seal, an attempt refused before the gate, a failing range, observe, off, a retried session, a
 * record at the sample bound, and the node links both ways.
 */

const WIDTHS = [1440, 1280] as const;
const S1 = "s1-af41ca";

/** The routes this screen may read: the run list, the run's own, and its three series routes. */
const ROUTES: readonly RegExp[] = [
  /^\/api\/runs$/,
  /^\/api\/runs\/0\/[^/]+\/events$/,
  /^\/api\/runs\/0\/[^/]+\/(config|status)$/,
  /^\/api\/runs\/0\/[^/]+\/series$/,
  /^\/api\/runs\/0\/[^/]+\/series\/[A-Za-z0-9][A-Za-z0-9_-]*\/[1-9]$/,
  /^\/api\/runs\/0\/[^/]+\/series\/[A-Za-z0-9][A-Za-z0-9_-]*\/[1-9]\/[a-z][a-z0-9_]*$/,
];

/** The paths a page asked for that are not this screen's routes. */
function unlisted(paths: Iterable<string>): string[] {
  return [...paths].filter((path) => !ROUTES.some((route) => route.test(path)));
}

/** A record id, a hex digest, a run id or a dotted key: never what leads. */
const AN_ID =
  /^([a-z][a-z0-9]*_[a-z0-9_]+$|[0-9a-f]{7,64}\b|run-\d+|[a-z][a-z0-9_]*(\.[a-z0-9_]+)+)/;

async function idsLead(page: Page, selector: string): Promise<string[]> {
  const firsts = await page.locator(selector).evaluateAll((all) =>
    all.map((el) => {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let node = walker.nextNode();
      while (node !== null && (node.textContent ?? "").trim() === "") node = walker.nextNode();
      return (node?.textContent ?? "").trim();
    }),
  );
  expect(firsts.length, `nothing matches ${selector}`).toBeGreaterThan(0);
  return firsts.filter((text) => AN_ID.test(text));
}

async function settle(page: Page) {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 60_000 });
}

async function open(page: Page, run: string, query = "", theme = "light", width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`/?theme=${theme}#/simulation/series?run=0/${run}${query}`);
  await settle(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator(".pg-page-title")).toHaveText("Simulation");
}

/** The part of the attempt route's answer the summary test reads. */
interface AttemptAnswer {
  readonly records: readonly {
    readonly record_id: string;
    readonly x: { readonly samples: number };
    readonly traces: readonly {
      readonly samples: number;
      readonly largest: number;
      readonly last: number;
    }[];
  }[];
}

const rail = (page: Page) => page.locator('nav[aria-label="Simulation records"]');
const table = (page: Page) =>
  page.locator('table[aria-label="What was read off a record, and what the gate said"]');
const row = (page: Page, quantity: string) =>
  table(page).locator("tbody tr", { hasText: quantity });

/**
 * Nothing scrolls sideways: not the page, the content, the rail, the record or the table of what
 * was read off a record. A plot's own data region may, and takes the keyboard for it.
 */
async function noSidewaysScroll(page: Page) {
  const wide = await page.evaluate(() => {
    const found: string[] = [];
    const root = document.scrollingElement;
    if (root !== null && root.scrollWidth > root.clientWidth + 1) found.push("the page");
    for (const el of document.querySelectorAll<HTMLElement>(
      ".pg-content, .pg-sim, .pg-sim-rail, .pg-sim-main, .pg-sim-record, .pg-sim-bound .pg-table-wrap",
    ))
      if (el.scrollWidth > el.clientWidth + 1) found.push(el.className);
    return found;
  });
  expect(wide).toEqual([]);
}

/** What the screen holds to, in every theme and at every width. */
async function holds(page: Page, seen: Watch, where: string) {
  await expect(page.locator('main [role="alert"]')).toHaveCount(0);
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(
    axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
    where,
  ).toEqual([]);
  await noSidewaysScroll(page);
  // Every value carries its unit and sits inside a figure that names its source.
  const unsourced = await page
    .locator(".pg-quantity")
    .evaluateAll((all) =>
      all.filter((q) => q.closest("[data-source]") === null).map((q) => q.textContent),
    );
  expect(unsourced, where).toEqual([]);
  expect(
    await hitAreasShort(
      page,
      ".pg-btn, .pg-run-link, .pg-seg button, .pg-sim-attempt, .pg-sim-record-link",
    ),
    where,
  ).toEqual([]);
  // Labels lead: every rail row, plot title, legend key and table row.
  for (const selector of [
    ".pg-sim-subtask-title",
    ".pg-sim-attempt",
    ".pg-sim-record-link",
    ".pg-plot-title",
    ".pg-sim-key",
    'table[aria-label="What was read off a record, and what the gate said"] tbody tr',
  ])
    expect(await idsLead(page, selector), `${where}: ${selector}`).toEqual([]);
  // The chart is hidden from assistive tech, which reads the summary and the table instead.
  const plots = await page.locator("figure.pg-plot").count();
  expect(plots).toBeGreaterThan(0);
  await expect(page.locator('figure.pg-plot .pg-plot-canvas[aria-hidden="true"]')).toHaveCount(
    plots,
  );
  await expect(page.locator("figure.pg-plot .pg-plot-summary")).toHaveCount(plots);
  // No what-if and nothing that acts.
  await expect(
    page.locator(
      ".pg-whatif, .pg-banner-whatif, .pg-plot-whatif, .pg-quantity-whatif, .pg-btn-act",
    ),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Run as/ })).toHaveCount(0);
  expect(seen.outbound, where).toEqual([]);
  expect(await cspViolations(page), where).toEqual([]);
  expect(unlisted(seen.api), where).toEqual([]);
  await saysNoMoreThanTheRecord(page, where);
  await namesNoCommand(page, where);
  const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
  if (evidence !== undefined)
    await page.screenshot({ path: `${evidence}/simulation-${where}.png` });
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`a recorded run: rail, record, plots and the table, held to the screen's rules (${theme}, ${String(width)})`, async ({
      page,
    }) => {
      const seen = await watch(page);
      await open(page, "run-series", "", theme, width);
      // It opens on the first subtask that sealed a record, at its merged attempt.
      await expect(rail(page).locator('.pg-sim-attempt[aria-current="true"]')).toContainText(
        "Attempt 1",
      );
      await expect(rail(page).locator('.pg-sim-attempt[aria-current="true"]')).toContainText(
        "Merged",
      );
      await expect(rail(page).locator(".pg-sim-group-title")).toHaveText([
        "Edge runs",
        "Frequency response",
        "Step",
      ]);
      await expect(page.locator(".pg-sim-record-head")).toContainText("titled by the control role");
      await bindingStylesHold(page);
      await holds(page, seen, `run-series-${theme}-${String(width)}`);
    });
  }
}

test("each plot's summary holds the attempt's own numbers, and its data every row with units", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "run-series", `&subtask=${S1}&attempt=1&record=step_nominal`);
  const figure = page.locator("figure.pg-plot").first();
  await expect(figure.locator(".pg-plot-title")).toHaveText("Position and error");
  const summary = (await figure.locator(".pg-plot-summary").textContent()) ?? "";
  // The summary's numbers are the attempt route's summary of the same record, unrounded.
  const answer = await page.evaluate(async (path) => {
    const response = await fetch(path);
    return (await response.json()) as AttemptAnswer;
  }, `/api/runs/0/run-series/series/${S1}/1`);
  const step = answer.records.find((r) => r.record_id === "step_nominal");
  expect(step).toBeDefined();
  for (const trace of step?.traces ?? []) {
    expect(summary).toContain(`${String(trace.samples)} samples`);
    expect(summary).toContain(`largest ${String(trace.largest)} m`);
    expect(summary).toContain(`last ${String(trace.last)} m`);
  }
  await figure.getByRole("button", { name: "Data", exact: true }).click();
  const data = figure.locator("table.pg-plot-table");
  await expect(data.locator("thead th")).toHaveText(["Time [s]", "Position [m]", "Error [m]"]);
  const samples = Number(step?.x.samples);
  await expect(figure).toContainText(`Rows 1–500 of ${String(samples)}`);
  let rows = await data.locator("tbody tr").count();
  while (await figure.getByRole("button", { name: "Next rows" }).isEnabled()) {
    await figure.getByRole("button", { name: "Next rows" }).click();
    rows += await data.locator("tbody tr").count();
  }
  expect(rows).toBe(samples);
  // The data region takes the keyboard, so a wide table can be scrolled without a pointer.
  await expect(figure.locator('[role="region"]')).toHaveAttribute("tabindex", "0");
  expect(seen.outbound).toEqual([]);
});

test("a loop is drawn as its magnitude and phase in the units recorded, never converted", async ({
  page,
}) => {
  await watch(page);
  await open(page, "run-series", `&subtask=${S1}&attempt=1&record=loop_nominal`);
  await expect(page.locator("figure.pg-plot .pg-plot-title")).toHaveText([
    "Loop magnitude",
    "Loop phase",
  ]);
  const phase = page.locator("figure.pg-plot").nth(1);
  await phase.getByRole("button", { name: "Data", exact: true }).click();
  await expect(phase.locator("thead th")).toHaveText([
    "Angular frequency [rad/s]",
    "Loop phase [rad]",
  ]);
  await expect(page.locator("main")).not.toContainText("°");
});

test("a record changed after its session ended is a sentence in its place, and nothing of it is drawn", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "run-series-tampered");
  const broken = rail(page).locator(".pg-sim-record-link", { hasText: "Not what was sealed" });
  await expect(broken).toHaveCount(1);
  // The others still render.
  await expect(page.locator("figure.pg-plot").first()).toBeVisible();
  await broken.click();
  await settle(page);
  const state = page.locator(".pg-sim-refused");
  await expect(state.locator("h2")).toHaveText(
    "This record changed after its session ended, so it is not shown.",
  );
  await expect(state).toContainText("sealed sha256");
  await expect(page.locator("figure.pg-plot")).toHaveCount(0);
  await expect(page.locator(".pg-plot-summary, .pg-sim-produced")).toHaveCount(0);
  await expect(page.locator(".pg-state-error")).toHaveCount(0);
  await expect(rail(page).locator(".pg-sim-record-link")).toHaveCount(6);
  expect(unlisted(seen.api)).toEqual([]);
  expect(seen.outbound).toEqual([]);
});

test("an attempt refused before the gate: the quantity could not be read off, and the gate did not run", async ({
  page,
}) => {
  await watch(page);
  await open(page, "run-series-refused");
  // With no choice, the merged attempt of the first subtask.
  await expect(rail(page).locator('.pg-sim-attempt[aria-current="true"]')).toContainText(
    "Attempt 3",
  );
  await expect(rail(page).locator(".pg-sim-attempt").nth(1)).toContainText(
    "Refused before the gate",
  );
  await open(page, "run-series-refused", `&subtask=${S1}&attempt=2`);
  await expect(page.locator("main")).toContainText("This attempt left no sealed record.");
  const phase = row(page, "Phase margin");
  await expect(phase).toContainText("Could not be read off the record");
  await expect(phase).toContainText("loop_nominal");
  await expect(phase).toContainText("The gate did not run: the attempt was refused before it.");
  await expect(phase.locator('[class*="pg-verdict"]')).toHaveCount(0);
});

test("the gate column: a failing range, an unchecked record and a quantity no gate record names", async ({
  page,
}) => {
  await watch(page);
  await open(page, "run-series-refused", `&subtask=${S1}&attempt=1`);
  const peak = row(page, "Step peak");
  await expect(peak.locator(".pg-verdict-fail")).toHaveCount(1);
  await expect(peak).toContainText("0.1");
  await expect(peak).toContainText(/check 2 · seq \d+/);
  await expect(row(page, "Phase margin").locator(".pg-verdict-unchecked")).toHaveCount(1);
  await open(page, "run-series", `&subtask=${S1}&attempt=1`);
  const named = row(page, "Step peak");
  await expect(named).toContainText("No gate record of this attempt names this quantity.");
  await expect(named.locator('[class*="pg-verdict"], .pg-badge')).toHaveCount(0);
});

test("under observe a failing range would fail and is not enforced; with the gate off it did not run", async ({
  page,
}) => {
  await watch(page);
  await open(page, "run-series-observe", `&subtask=${S1}&attempt=1`);
  const peak = row(page, "Step peak");
  await expect(peak).toContainText("Would fail · not enforced");
  await expect(table(page).locator(".pg-verdict-fail")).toHaveCount(0);
  await open(page, "run-series-off", `&subtask=${S1}&attempt=1`);
  const cells = table(page).locator("tbody tr");
  const n = await cells.count();
  expect(n).toBeGreaterThan(0);
  for (let i = 0; i < n; i += 1) await expect(cells.nth(i)).toContainText("The gate did not run.");
  await expect(table(page).locator('[class*="pg-verdict"]')).toHaveCount(0);
});

test("a retried session: what it recorded again is superseded, what it left is set aside with a reason", async ({
  page,
}) => {
  await watch(page);
  await open(page, "run-series-retried", `&subtask=${S1}&attempt=1`);
  const superseded = rail(page).locator("details", { hasText: "Superseded" });
  await superseded.locator("summary").click();
  await expect(superseded.locator("li")).toHaveCount(6);
  await expect(superseded).toContainText("the later one is shown");
  const aside = rail(page).locator("details", { hasText: "Set aside" });
  await aside.locator("summary").click();
  await expect(aside).toContainText("stray_notes.json");
  await expect(aside).toContainText(".half_written.tmp");
  await expect(aside).toContainText("Not sealed:");
});

test("a record at the sample bound pages its every row, and a frequency record that is no loop is one plot", async ({
  page,
}) => {
  await watch(page);
  await open(page, "run-series-large");
  await page.locator(".pg-sim-record-link", { hasText: "long run at the sample bound" }).click();
  await settle(page);
  const figure = page.locator("figure.pg-plot").first();
  await figure.getByRole("button", { name: "Data", exact: true }).click();
  await expect(figure).toContainText("Rows 1–500 of 100000");
  await figure.getByRole("button", { name: "Next rows" }).click();
  await expect(figure).toContainText("Rows 501–1000 of 100000");
  await page.locator(".pg-sim-record-link", { hasText: "gain sweep" }).click();
  await settle(page);
  await expect(page.locator("figure.pg-plot .pg-plot-title")).toHaveText(["Gain"]);
});

test("a run that recorded no simulation says so, with no command", async ({ page }) => {
  await watch(page);
  await open(page, "run-clean");
  await expect(page.locator(".pg-state-empty h2").first()).toHaveText(
    "This run recorded no simulations.",
  );
  await namesNoCommand(page, "run-clean");
});

test("the node links go both ways, and the keyboard reaches a record and moves focus into it", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "run-series", `&subtask=${S1}&attempt=1`);
  // Keyboard: a rail record is a link; choosing one moves focus into the record.
  const link = rail(page).locator(".pg-sim-record-link", { hasText: "gain 2.5" });
  await link.focus();
  await page.keyboard.press("Enter");
  await settle(page);
  await expect(page.locator(".pg-sim-record-heading")).toBeFocused();
  // A row's node opens the design graph with that node selected.
  await row(page, "Phase margin").locator("a.pg-sim-node").click();
  await expect(page.locator(".pg-page-title")).toHaveText("Design graph");
  await settle(page);
  const back = page.getByRole("link", { name: "Show the record it was read off" }).first();
  await expect(back).toBeVisible();
  await back.click();
  await settle(page);
  await expect(page.locator(".pg-page-title")).toHaveText("Simulation");
  await expect(page.locator(".pg-sim-record-heading")).toContainText("broken at the plant input");
  expect(seen.outbound).toEqual([]);
});

test("the route watch catches a path this screen does not read", async ({ page }) => {
  const seen = await watch(page);
  await open(page, "run-series");
  expect(unlisted(seen.api)).toEqual([]);
  await page.evaluate(async () => {
    await fetch("/api/runs/0/run-series/ledger");
  });
  await expect.poll(() => unlisted(seen.api)).toEqual(["/api/runs/0/run-series/ledger"]);
});
