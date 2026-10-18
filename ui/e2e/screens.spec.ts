import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  bindingStylesHold,
  cspViolations,
  hitAreasShort,
  idsLeading,
  namesNoCommand,
  saysNoMoreThanTheRecord,
  styles,
  THEMES,
  TRANSPARENT,
  watch,
  type Watch,
} from "./support";

/**
 * Home, the run timeline and the design graph end to end: the real server over runs the real
 * loop made. In both themes and at both widths each screen renders without a refusal, leads every
 * row and heading with a human label, names the source of every quantity, keeps the design's
 * binding styling rules, passes axe, says nothing about a decision the harness does not do, makes
 * no outbound request and breaks no content-security rule.
 */

const WIDTHS = [1440, 1280] as const;

async function open(page: Page, theme: string, path: string, width = 1440, alerts = 0) {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`/?theme=${theme}#${path}`);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator('main [role="alert"]')).toHaveCount(alerts);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

async function common(page: Page, seen: Watch, shot: string) {
  const unsourced = await page
    .locator(".pg-quantity")
    .evaluateAll((all) =>
      all.filter((q) => q.closest("[data-source]") === null).map((q) => q.textContent),
    );
  expect(unsourced).toEqual([]);
  expect(
    await hitAreasShort(
      page,
      ".pg-btn, .pg-run-link, .pg-seg button, button.pg-node, .pg-trow-open, .pg-need-link",
    ),
  ).toEqual([]);
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(
    axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
  ).toEqual([]);
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);
  await saysNoMoreThanTheRecord(page, shot);
  await namesNoCommand(page, shot);
  // No what-if is drawn on these screens: the runs carry no draft.
  await expect(page.locator(".pg-whatif, .pg-banner-whatif, .pg-figure-whatif")).toHaveCount(0);
  // The dock stays the placeholder: no collaborator action on any screen.
  await expect(page.locator(".pg-change, .pg-msg")).toHaveCount(0);
  const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
  if (evidence !== undefined) {
    // From the top of the content, so the evidence shows what a person sees first.
    await page.evaluate(() => {
      document.querySelector(".pg-content")?.scrollTo(0, 0);
    });
    await page.screenshot({ path: `${evidence}/${shot}.png` });
  }
}

/** Every graph node is whole inside the frame: none cut at an edge. */
async function nodesWhole(page: Page) {
  const cut = await page.locator(".pg-graph-frame").evaluate((frame) => {
    const box = frame.getBoundingClientRect();
    return [...frame.querySelectorAll<HTMLElement>("button.pg-node")]
      .filter((node) => {
        const r = node.getBoundingClientRect();
        return (
          r.left < box.left - 1 ||
          r.right > box.right + 1 ||
          r.top < box.top - 1 ||
          r.bottom > box.bottom + 1
        );
      })
      .map((node) => node.querySelector(".pg-node-id")?.textContent ?? "");
  });
  expect(await page.locator("button.pg-node").count()).toBeGreaterThan(0);
  expect(cut).toEqual([]);
}

/** Every node label and key is whole: wrapped, never cut, never clamped. */
async function labelsWhole(page: Page) {
  const cut = await page.locator(".pg-node-label, .pg-node-id").evaluateAll((all) =>
    all
      .filter((el) => {
        const s = getComputedStyle(el);
        return (
          el.scrollWidth > el.clientWidth + 0.5 ||
          s.textOverflow === "ellipsis" ||
          (s.webkitLineClamp !== "none" && s.webkitLineClamp !== "")
        );
      })
      .map((el) => el.textContent),
  );
  expect(cut).toEqual([]);
}

/** No text in any table of the screen is cut: each fits its region and every cell its text. */
async function nothingCut(page: Page) {
  const overflow = await page.locator(".pg-table-wrap > table").evaluateAll((tables) =>
    tables.flatMap((table) => {
      const region = table.parentElement;
      const wide =
        region !== null && table.scrollWidth > region.clientWidth + 1
          ? [`a table is wider than its region: ${table.getAttribute("aria-label") ?? ""}`]
          : [];
      const cells = [...table.querySelectorAll<HTMLElement>("td, th")]
        .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
        .map((cell) => cell.textContent.slice(0, 60));
      return [...wide, ...cells];
    }),
  );
  expect(overflow).toEqual([]);
}

/** Every run in the switcher reads differently from every other. */
async function runsDistinct(page: Page) {
  const labels = await page
    .locator('nav[aria-label="Runs"] .pg-run-link')
    .evaluateAll((links) => links.map((l) => l.textContent.replace(/\s+/g, " ").trim()));
  expect(labels.length).toBeGreaterThan(1);
  expect(new Set(labels).size).toBe(labels.length);
}

/** Nothing the gate decided under observe is a filled verdict, and observe reads hatched. */
async function observedNeverFilled(page: Page, scope: string) {
  await expect(page.locator(".pg-topbar .pg-gate-observe")).toBeVisible();
  await expect(
    page.locator(`${scope} .pg-verdict-pass, ${scope} .pg-verdict-fail, ${scope} .pg-verdict-warn`),
  ).toHaveCount(0);
  for (const o of await styles(page, `${scope} .pg-observed`, [
    "border-top-style",
    "background-color",
  ]))
    expect(o).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
  await expect(page.locator(".pg-tally-evaluated .pg-verdict-unchecked")).toHaveCount(0);
}

/** The ids of the runs whose per-run records a page asked for. */
function runsRead(seen: Watch, route: string): Set<string> {
  return new Set(
    [...seen.api].flatMap((path) => {
      const found = new RegExp(`^/api/runs/0/([^/]+)/${route}$`).exec(path);
      return found === null ? [] : [found[1] ?? ""];
    }),
  );
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`Home: the runs, the run still going, what needs a person, and recent events (${theme}, ${String(width)})`, async ({
      page,
      request,
    }) => {
      const seen = await watch(page);
      // The run still going is one whose log was cut short, so the server refuses its ledger as
      // disagreeing with its log: that panel shows the refusal with its reason, and nothing else.
      await open(page, theme, "/home", width, 1);
      await expect(page.locator(".pg-page-title")).toHaveText("Home");
      const refused = page.locator('section[aria-label="The run still going"] [role="alert"]');
      await expect(refused).toContainText("The subtasks could not be read");
      await expect(refused).toContainText("the task ledger disagrees with the run-event log");
      await expect(refused.getByRole("button", { name: "Read again" })).toBeVisible();
      // The runs, grouped by brief as a view.
      const runs = page.locator('section[aria-label="Runs"]');
      await expect(runs).toContainText("View: grouped by brief");
      await expect(runs.locator(".pg-group-row").first()).toContainText("Runs of one brief");
      expect(await idsLeading(page, ".pg-run-name, .pg-need-why, .pg-trow-what")).toEqual([]);
      // The run still going: its chip says partial, and its figures say so far.
      const active = page.locator('section[aria-label="The run still going"]');
      await expect(active).toBeVisible();
      await expect(page.locator('[aria-label="The run shown"]')).toContainText(
        "In progress · partial",
      );
      await expect(active.locator(".pg-tally")).toContainText("so far");
      await expect(active).toContainText("List-price estimate");
      // Needs you: every open item across the runs read, a sentence first.
      const listed = (await (await request.get("/api/runs")).json()) as {
        runs: { name: string }[];
      };
      expect(listed.runs.length).toBeGreaterThan(12);
      const read = runsRead(seen, "queue");
      let waiting = 0;
      for (const name of read) {
        const q = (await (await request.get(`/api/runs/0/${name}/queue`)).json()) as {
          open: unknown[];
        };
        waiting += q.open.length;
      }
      await expect(page.locator('section[aria-label="Needs you"] .pg-need-link')).toHaveCount(
        waiting,
      );
      // Recent activity: rows with their actor.
      const rows = page.locator('section[aria-label="Recent activity"] .pg-trow');
      await expect(rows).toHaveCount(8);
      for (const row of await rows.all()) await expect(row.locator(".pg-actor")).toHaveCount(1);
      await expect(page.locator('section[aria-label="System"]')).toBeVisible();
      await bindingStylesHold(page);
      await nothingCut(page);
      await common(page, seen, `home-${theme}-${String(width)}`);
    });
  }
}

test("Home reads at most twelve runs in full, and reads the rest when asked", async ({ page }) => {
  const seen = await watch(page);
  await open(page, "light", "/home", 1440, 1);
  const first = runsRead(seen, "events");
  expect(first.size).toBe(12);
  for (const route of ["config", "status", "queue"]) expect(runsRead(seen, route).size).toBe(12);
  await page.getByRole("button", { name: "Show all runs" }).click();
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect.poll(() => runsRead(seen, "events").size).toBeGreaterThan(12);
  await expect(page.getByRole("button", { name: "Show all runs" })).toHaveCount(0);
});

for (const theme of THEMES) {
  test(`the run timeline of a gated run with three repairs, and its attempt inspector (${theme})`, async ({
    page,
  }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/run-timeline?run=0/drive-on");
    const timeline = page.locator('section[aria-label="Timeline"]');
    const fails = timeline.locator(".pg-trow .pg-verdict-fail");
    await expect(fails).toHaveCount(3);
    await expect(timeline).toContainText("Attempt 2 rejected:");
    await expect(timeline).not.toContainText("sent back for repair");
    await expect(timeline).toContainText("Set aside for a person to decide");
    await expect(timeline).toContainText("The run goes on with the other subtasks.");
    for (const row of await timeline.locator(".pg-trow").all())
      await expect(row.locator(".pg-actor")).toHaveCount(1);
    expect(await idsLeading(page, ".pg-trow-what, .pg-screen-title")).toEqual([]);
    // The run reads by when it started, in the screen's heading and in the top bar.
    const started = /^Run \d{1,2} [A-Z][a-z]{2}, \d{2}:\d{2}/;
    await expect(page.locator(".pg-screen-title")).toHaveText(started);
    await expect(page.locator(".pg-run-chip .pg-run-label")).toHaveText(started);
    // The tally reads unchecked after the separator, and the cost is a list-price estimate.
    await expect(
      page.locator(".pg-run-head .pg-tally-evaluated .pg-verdict-unchecked"),
    ).toHaveCount(0);
    await expect(page.locator(".pg-run-head")).toContainText("List-price estimate");
    await expect(page.locator(".pg-run-head")).toContainText("Lower bound");
    // An attempt's row opens the inspector.
    await timeline.locator(".pg-trow-open", { hasText: "Attempt 3" }).first().click();
    const inspector = page.locator('aside[aria-label="Attempt inspector"]');
    await expect(inspector).toBeVisible();
    await expect(inspector.locator(".pg-inspector-title")).toHaveText(
      "Subtask 1 · attempt 3 · repairs used up",
    );
    await expect(inspector.locator('[data-status-kind="seal-holds"]')).toHaveCount(1);
    await expect(inspector).toContainText("Why it failed");
    await expect(inspector.locator(".pg-why").first()).toContainText(
      "Power drawn by the consumers",
    );
    // No review line is recorded for this attempt, and the inspector says only that: not why.
    await expect(inspector).toContainText("Not run: no review is recorded for this attempt.");
    await expect(inspector).not.toContainText("because the gate failed");
    // Unchecked follows the separator in the inspector's list, and none is above it.
    const checks = inspector.locator('section[aria-label="Gate checks"]');
    await expect(
      checks.locator('hr.pg-sep + ul[aria-label="Unchecked"] .pg-verdict-unchecked').first(),
    ).toBeVisible();
    await expect(checks.locator("ul:not([aria-label]) .pg-verdict-unchecked")).toHaveCount(0);
    for (const route of ["events", "gate-checks", "trace", "status", "config", "cost/2026-10-16"])
      expect([...seen.api]).toContain(`/api/runs/0/drive-on/${route}`);
    expect([...seen.api]).toContain("/api/runs/0/drive-on/trajectories/:session");
    await runsDistinct(page);
    await bindingStylesHold(page);
    await common(page, seen, `run-timeline-on-${theme}`);
  });

  test(`the run timeline under observe: nothing is a filled verdict (${theme})`, async ({
    page,
  }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/run-timeline?run=0/drive-observe", 1280);
    const timeline = page.locator('section[aria-label="Timeline"]');
    await expect(timeline.locator(".pg-observed").first()).toContainText(
      "Would fail · not enforced",
    );
    // A gate outcome under observe is never filled; a reviewer's recorded verdict still is.
    await observedNeverFilled(page, 'section[aria-label="Timeline"] .pg-trow[data-kind="gate"]');
    await observedNeverFilled(page, ".pg-run-head");
    await common(page, seen, `run-timeline-observe-${theme}`);
  });
}

test("a gate stage with no recorded result is no verdict, never a pass", async ({ page }) => {
  const seen = await watch(page);
  await open(page, "light", "/orchestration/run-timeline?run=0/drive-cut");
  const none = page.locator('section[aria-label="Timeline"] .pg-no-verdict');
  await expect(none).toHaveCount(1);
  await expect(none).toHaveText("No verdict recorded");
  for (const g of await styles(page, ".pg-no-verdict", ["border-top-style", "background-color"]))
    expect(g).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
  await expect(
    page.locator(
      'section[aria-label="Timeline"] .pg-verdict-pass, section[aria-label="Timeline"] .pg-observed',
    ),
  ).toHaveCount(0);
  await expect(page.locator(".pg-run-head")).toContainText("No gate checks recorded");
  // In progress: the chip says partial, the cost says so far.
  await expect(page.locator('[aria-label="The run shown"]')).toContainText("In progress · partial");
  await expect(page.locator(".pg-run-head .pg-so-far").first()).toHaveText("so far");
  expect(seen.outbound).toEqual([]);
});

test("the timeline's event log refused is a sentence with its reason, and nothing partial", async ({
  page,
}) => {
  await watch(page);
  await page.route("**/api/runs/0/drive-on/events", (route) =>
    route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({ error: "the log holds a line no writer could have written" }),
    }),
  );
  await page.goto("/?theme=light#/orchestration/run-timeline?run=0/drive-on");
  const alert = page.locator('main [role="alert"]');
  await expect(alert).toContainText("The run's event log could not be read");
  await expect(alert).toContainText("the log holds a line no writer could have written");
  await expect(alert).toContainText("422");
  await expect(page.locator('section[aria-label="Timeline"]')).toHaveCount(0);
  await expect(page.locator('[aria-label="The run shown"]')).toHaveText("Run not read");
  await expect(alert.getByRole("button", { name: "Read again" })).toBeVisible();
});

for (const theme of THEMES) {
  test(`the design graph: nodes are buttons led by their labels, and a node opens whole in the inspector (${theme})`, async ({
    page,
  }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/design-graph?run=0/drive-observe");
    const nodes = page.locator("button.pg-node");
    await expect(nodes).toHaveCount(6);
    await nodesWhole(page);
    await labelsWhole(page);
    expect(await idsLeading(page, ".pg-node-label")).toEqual([]);
    // Cross-domain edges are dashed; edges within one domain are not.
    for (const e of await styles(page, '.pg-edge[data-cross="false"]', ["stroke-dasharray"]))
      expect(e["stroke-dasharray"]).toBe("none");
    await nodes
      .filter({ has: page.locator(".pg-node-id", { hasText: /^electrical\.drive$/ }) })
      .click();
    const inspector = page.locator('aside[aria-label="Node inspector"]');
    await expect(inspector.locator(".pg-inspector-title")).toHaveText("Drive");
    await expect(inspector.locator('section[aria-label="Quantities"] .pg-quantity')).toHaveCount(3);
    await expect(inspector.locator('section[aria-label="Quantities"]')).toContainText("Set by");
    await expect(inspector.locator('section[aria-label="Quantities"]')).toContainText(
      "Electrical agent",
    );
    await expect(inspector.locator('section[aria-label="Constrains"]')).toContainText(
      "electrical.battery",
    );
    await expect(inspector.locator('section[aria-label="Constrained by"]')).toContainText(
      "electrical.driver",
    );
    await expect(inspector.locator(".pg-history-entry")).toHaveCount(1);
    await observedNeverFilled(page, 'aside[aria-label="Node inspector"]');
    await nodesWhole(page);
    expect([...seen.api]).toEqual(
      expect.arrayContaining([
        "/api/runs/0/drive-observe/config",
        "/api/runs/0/drive-observe/graph",
        "/api/runs/0/drive-observe/gate-checks",
        "/api/runs/0/drive-observe/graph/history/electrical.drive",
      ]),
    );
    await runsDistinct(page);
    await common(page, seen, `design-graph-${theme}`);
  });

  test(`the design graph as a table, and the changes between two revisions (${theme})`, async ({
    page,
  }) => {
    const seen = await watch(page);
    await open(page, theme, "/orchestration/design-graph?run=0/drive-observe&view=table", 1280);
    await expect(page.locator('section[aria-label="Nodes"] tbody tr')).toHaveCount(6);
    await nothingCut(page);
    await page.getByRole("button", { name: "Changes" }).click();
    await page.getByRole("button", { name: "Show the changes" }).click();
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
    await page.goto(
      `/?theme=${theme}#/orchestration/design-graph?run=0/drive-observe&view=diff&diff=1-6`,
    );
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
    const diff = page.locator('section[aria-label="Diff"]');
    await expect(diff.locator('table[aria-label="Change list"] tbody tr')).toHaveCount(5);
    await expect(diff).toContainText("View: rows are marked");
    expect(await idsLeading(page, 'table[aria-label="Change list"] tbody td:first-child')).toEqual(
      [],
    );
    expect([...seen.api]).toContain("/api/runs/0/drive-observe/graph/diff/1/6");
    await nothingCut(page);
    await common(page, seen, `design-graph-diff-${theme}`);
  });
}

test("a value is shown with every digit its record holds, never rounded", async ({ page }) => {
  const seen = await watch(page);
  const recorded = 14.712345678;
  let held: string | null = null;
  await page.route("**/api/runs/0/drive-observe/graph", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as {
      nodes: Record<
        string,
        { node: { id: string; quantities: Record<string, { value: unknown }> } }
      >;
    };
    const drive = Object.values(body.nodes).find((n) => n.node.id === "electrical.drive");
    const first = drive === undefined ? undefined : Object.keys(drive.node.quantities)[0];
    if (drive !== undefined && first !== undefined) {
      (drive.node.quantities[first] as { value: unknown }).value = recorded;
      held = first;
    }
    await route.fulfill({ response, json: body });
  });
  await open(
    page,
    "light",
    "/orchestration/design-graph?run=0/drive-observe&node=electrical.drive",
  );
  expect(held).not.toBeNull();
  const inspector = page.locator('aside[aria-label="Node inspector"]');
  await expect(inspector.locator(".pg-quantity-value", { hasText: /^14\.712345678$/ })).toHaveCount(
    1,
  );
  expect(seen.outbound).toEqual([]);
});

test("a long node label wraps whole at 1280, and its key stays whole beneath it", async ({
  page,
}) => {
  await watch(page);
  const long = "electrical.a_driver_whose_key_runs_far_longer_than_any_card_is_wide_at_all";
  await page.route("**/api/runs/0/drive-observe/graph", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as {
      nodes: Record<string, { node: { id: string } }>;
    };
    const driver = body.nodes["electrical.driver"];
    if (driver !== undefined) {
      driver.node.id = long;
      body.nodes[long] = driver;
      delete body.nodes["electrical.driver"];
    }
    await route.fulfill({ response, json: body });
  });
  await open(page, "light", "/orchestration/design-graph?run=0/drive-observe", 1280);
  await expect(page.locator(".pg-node-id", { hasText: long })).toHaveCount(1);
  await labelsWhole(page);
  await nodesWhole(page);
});

test("the graph opens with a node selected by its link, every node whole", async ({ page }) => {
  const seen = await watch(page);
  await open(
    page,
    "light",
    "/orchestration/design-graph?run=0/drive-observe&node=electrical.driver",
  );
  await expect(page.locator('button.pg-node[aria-pressed="true"]')).toContainText(
    "electrical.driver",
  );
  await nodesWhole(page);
  expect(seen.outbound).toEqual([]);
});

test("the arrow keys move the focus along the graph's edges", async ({ page }) => {
  await watch(page);
  await open(page, "light", "/orchestration/design-graph?run=0/drive-observe");
  const driver = page.locator("button.pg-node").filter({
    has: page.locator(".pg-node-id", { hasText: /^electrical\.driver$/ }),
  });
  await driver.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("button.pg-node:focus .pg-node-id")).toHaveText("electrical.drive");
  await page.keyboard.press("ArrowLeft");
  await expect(page.locator("button.pg-node:focus .pg-node-id")).toHaveText(/^electrical\./);
});

test("under a domain filter the nodes table resolves every edge over the whole graph", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "light", "/orchestration/design-graph?run=0/domains");
  await expect(page.locator("button.pg-node")).toHaveCount(4);
  await page.locator('[aria-label="Domain filter"] button', { hasText: /^Control$/ }).click();
  await expect(page.locator("button.pg-node")).toHaveCount(1);
  await page.getByRole("button", { name: "Table" }).click();
  const table = page.locator('section[aria-label="Nodes"]');
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(table).not.toContainText("not in the graph");
  await expect(table.locator("tbody tr")).toContainText("firmware.loop");
  await expect(table.locator("tbody tr")).toContainText("electrical.supply");
  expect(seen.outbound).toEqual([]);
});

test("the command palette finds the graph's nodes by label, key and verdict", async ({ page }) => {
  await watch(page);
  await open(page, "light", "/orchestration/design-graph?run=0/drive-observe");
  await page.keyboard.press("Control+k");
  await page.keyboard.type("Driver");
  const entry = page.locator('dialog.pg-palette [role="option"]', { hasText: "electrical.driver" });
  await expect(entry.first()).toContainText("Driver · electrical.driver");
  await page.keyboard.press("Enter");
  await expect(page.locator('aside[aria-label="Node inspector"] .pg-inspector-title')).toHaveText(
    "Driver",
  );
});

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`the glossary: five groups, every term, and the queue item as recorded (${theme}, ${String(width)})`, async ({
      page,
    }) => {
      const seen = await watch(page);
      await open(page, theme, "/reference/glossary", width);
      await expect(page.locator(".pg-page-title")).toHaveText("Glossary");
      await expect(page.locator(".pg-glossary section")).toHaveCount(5);
      const glossary = page.locator(".pg-glossary");
      for (const term of ["Gate", "Observe", "Unchecked", "Attempt", "Repair", "Safe point"])
        await expect(glossary.locator("dt", { hasText: new RegExp(`^${term}$`) })).toHaveCount(1);
      await expect(glossary).toContainText(
        "A question the run could not settle by itself. Your decision is recorded against the run; it does not restart the subtask.",
      );
      await expect(glossary).toContainText("Power balance check");
      await common(page, seen, `glossary-${theme}-${String(width)}`);
    });
  }

  test(`run records: configuration, cost at a price sheet, tokens, ledger and seals (${theme})`, async ({
    page,
  }) => {
    const seen = await watch(page);
    await open(page, theme, "/home/run-records?run=0/drive-observe", 1280);
    await expect(page.locator(".pg-page-title")).toHaveText("Run records");
    await expect(page.locator('section[aria-label="Configuration"]')).toContainText("Manifest");
    await expect(page.locator('section[aria-label="Cost"]')).toContainText("list-price estimate");
    await expect(page.locator('table[aria-label="By attribution"]')).toContainText("all routing");
    await expect(page.locator('section[aria-label="Tokens and cost"]')).toContainText(
      "Lower bound",
    );
    await expect(
      page.locator('section[aria-label="Trajectories"] [data-status-kind="seal-holds"]').first(),
    ).toBeVisible();
    expect(
      await idsLeading(page, ".pg-panel-title, table[aria-label='Task ledger'] td:first-child"),
    ).toEqual([]);
    for (const route of [
      "config",
      "ledger",
      "events",
      "tokens",
      "decisions",
      "gate-events",
      "cost/2026-10-16",
    ])
      expect([...seen.api]).toContain(`/api/runs/0/drive-observe/${route}`);
    await nothingCut(page);
    await common(page, seen, `run-records-${theme}`);
  });
}
