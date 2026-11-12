import { readFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import { RUNS } from "../playwright.config";
import { BANNED_WORDS } from "../src/rules/scan";
import { OS_LAYER_ABSENT_WORDS, QUEUE_DECISION_WORDS, SETTINGS_COPY } from "../src/words/settings";
import {
  cspViolations,
  hitAreasShort,
  LOCAL,
  namesNoCommand,
  THEMES,
  watch,
  type Watch,
} from "./support";

/**
 * Settings end to end: the real server over runs the real loop made, its engine catalogue the
 * checkout's own file, read once at start. In both themes and at both widths the screen passes
 * axe, scrolls nowhere sideways but inside a table, keeps every control a person reaches at
 * 44 px, keeps every quantity inside a named source, shows no command, no act and none of the
 * held-out tier's values or the operator's token, and asks the server for exactly what it shows,
 * by GET alone, with no request leaving the origin.
 */

const WIDTHS = [1440, 1280] as const;
/** How many listed runs a screen reads labels for before the person asks for all. */
const FIRST_RUNS = 12;

interface Listed {
  readonly root: number;
  readonly name: string;
  readonly error?: string;
}

async function listed(request: APIRequestContext): Promise<readonly Listed[]> {
  const answer = (await (await request.get("/api/runs")).json()) as { runs: Listed[] };
  return answer.runs;
}

const base = (run: Listed) => `/api/runs/${String(run.root)}/${encodeURIComponent(run.name)}`;

/** The requests a page made to this server, with their methods. */
function methods(page: Page): string[] {
  const found: string[] = [];
  page.on("request", (request) => {
    if (LOCAL.test(request.url()))
      found.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });
  return found;
}

async function settle(page: Page) {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
}

async function open(page: Page, query: string, theme: string | null = "light", width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  const search = theme === null ? "" : `?theme=${theme}`;
  // A page of its own each time: an address that differs only in its fragment would not load.
  await page.goto("about:blank");
  await page.goto(`/${search}#/home/settings${query}`);
  await settle(page);
  await expect(page.locator(".pg-page-title")).toHaveText("Settings");
}

function section(page: Page, name: string) {
  return page.locator(`section[aria-label="${name}"]`).first();
}

/** Nothing scrolls sideways: not the page, not the content; a table may, inside its own region. */
async function noSidewaysScroll(page: Page) {
  const wide = await page.evaluate(() => {
    const found: string[] = [];
    const root = document.scrollingElement;
    if (root !== null && root.scrollWidth > root.clientWidth + 1) found.push("the page");
    for (const el of document.querySelectorAll<HTMLElement>(".pg-content, .pg-settings, .pg-card"))
      if (el.scrollWidth > el.clientWidth + 1)
        found.push(`${el.className} ${el.getAttribute("aria-label") ?? ""}`.trim());
    return found;
  });
  expect(wide).toEqual([]);
}

/** What every view of the screen holds to. */
async function holds(page: Page, seen: Watch, where: string) {
  await expect(page.locator('main [role="alert"]')).toHaveCount(0);
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(
    axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
    where,
  ).toEqual([]);
  await noSidewaysScroll(page);
  expect(
    await hitAreasShort(
      page,
      ".pg-btn, .pg-seg button, .pg-run-link, .pg-runs-summary, .pg-nav-foot .pg-nav-link, main summary",
    ),
    where,
  ).toEqual([]);
  const unsourced = await page
    .locator("main .pg-quantity")
    .evaluateAll((all) =>
      all.filter((q) => q.closest("[data-source]") === null).map((q) => q.textContent),
    );
  expect(unsourced, where).toEqual([]);
  await expect(page.locator(".pg-btn-act, .pg-btn-reject, main dialog")).toHaveCount(0);
  expect(await page.locator("main").innerText()).not.toMatch(/[✓✕]/);
  await namesNoCommand(page, where);
  const whole = await page.evaluate(() => document.body.textContent);
  expect(BANNED_WORDS.filter((w) => w.test(whole)).map(String), where).toEqual([]);
  expect(seen.outbound, where).toEqual([]);
  expect(await cspViolations(page), where).toEqual([]);
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`every section of Settings, over a run the OS layer held (${theme}, ${String(width)})`, async ({
      page,
    }) => {
      const seen = await watch(page);
      await open(page, "?run=0/set-present-none", theme, width);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(section(page, "Engines").locator(".pg-engine")).not.toHaveCount(0);
      await expect(
        section(page, "System, as the run recorded it").locator(".pg-facts").first(),
      ).toBeVisible();
      await holds(page, seen, `settings-${theme}-${String(width)}`);
      const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
      if (evidence !== undefined)
        await page.screenshot({
          path: `${evidence}/settings-${theme}-${String(width)}.png`,
          fullPage: true,
        });
    });
  }
}

for (const query of ["", "?run=0/set-absent-none"]) {
  test(`the screen asks for exactly what it shows, by GET alone (${query === "" ? "the newest run" : "a run past the first listed"})`, async ({
    page,
    request,
  }) => {
    const runs = await listed(request);
    const readable = runs.filter((run) => run.error === undefined);
    expect(readable.length).toBeGreaterThan(FIRST_RUNS);
    const seen = await watch(page);
    const asked = methods(page);
    await open(page, query);
    await expect(
      section(page, "System, as the run recorded it").locator(".pg-facts").first(),
    ).toBeVisible();
    await settle(page);
    const configs = [...seen.api].filter((p) => p.endsWith("/config"));
    expect(configs).toHaveLength(1);
    const chosen = readable.find((run) => `${base(run)}/config` === configs[0]);
    expect(chosen).toBeDefined();
    if (query !== "") {
      expect(chosen?.name).toBe("set-absent-none");
      expect(readable.slice(0, FIRST_RUNS)).not.toContain(chosen);
    }
    const labelled = [...readable.slice(0, FIRST_RUNS), ...(chosen === undefined ? [] : [chosen])];
    const expected = new Set([
      "/api/runs",
      "/api/engines",
      ...labelled.map((run) => `${base(run)}/events`),
      ...(chosen === undefined ? [] : [`${base(chosen)}/config`, `${base(chosen)}/status`]),
    ]);
    expect(new Set(seen.api)).toEqual(expected);
    expect(asked.length).toBeGreaterThan(0);
    expect(asked.filter((a) => !a.startsWith("GET "))).toEqual([]);
    expect(seen.outbound).toEqual([]);
    expect(await cspViolations(page)).toEqual([]);
    // The comparison would refuse a path the screen has no business asking for.
    const first = readable[0];
    if (first === undefined) throw new Error("no readable run");
    expect(new Set([...seen.api, `${base(first)}/ledger`])).not.toEqual(expected);
  });
}

test("each run's OS layer and network read as it recorded them, under its own source", async ({
  page,
}) => {
  await watch(page);
  const system = () => section(page, "System, as the run recorded it");
  const field = (name: string) => system().locator(`[data-field="${name}"]`);

  await open(page, "?run=0/set-present-none");
  await expect(field("os-layer")).toContainText("OS layer · Seatbelt");
  await expect(field("network")).toContainText("None, enforced by the OS layer");
  await expect(system().locator(".pg-system > .pg-source")).toHaveAttribute(
    "aria-label",
    /^Source: run set-present-none at /,
  );
  await expect(field("token-ceiling").locator(".pg-quantity")).toHaveText("100000tokens");
  await expect(field("wall-clock").locator(".pg-quantity")).toHaveText("120s");
  await expect(field("turns").locator(".pg-quantity")).toHaveText("20turns");
  await expect(field("retries").locator(".pg-quantity")).toHaveText("0retries");
  await expect(page.locator('[aria-label="The run shown"]')).toContainText("OS layer · Seatbelt");

  await open(page, "?run=0/set-absent-none");
  await expect(field("os-layer").locator(".pg-os-layer-absent")).toBeVisible();
  await expect(field("os-layer")).toContainText("macOS: sandbox-exec is missing");
  await expect(field("network")).toContainText("None requested, not enforceable here");

  await open(page, "?run=0/run-esc-act");
  await expect(field("queue-decisions")).toContainText(QUEUE_DECISION_WORDS.act ?? "");
  // The rig configures its runs for development, where sessions may run without the layer.
  await expect(field("os-layer-absent")).toContainText(OS_LAYER_ABSENT_WORDS.allow ?? "");

  await open(page, "?run=0/run-on");
  await expect(field("os-layer")).toContainText("OS layer not recorded");
  await expect(field("network")).toContainText("Open");

  const pairs = system().locator('table[aria-label="Who built and who reviewed"] tbody tr');
  await expect(pairs.first()).toBeVisible();
  await expect(pairs.filter({ hasText: SETTINGS_COPY.decomposition })).toHaveCount(1);
  await expect(system().locator(".pg-verdict-pass, .pg-verdict-fail")).toHaveCount(0);
});

test("no value of the held-out tier reaches the page, whatever the configuration carries", async ({
  page,
  request,
}) => {
  const seen = await watch(page);
  const path = "/api/runs/0/set-present-none/config";
  const planted = {
    held_out: ["/srv/planted/held-out-root-7f3a"],
    held_out_canaries: ["CANARY-PLANTED-7F3A-0001"],
    held_out_sha256: ["7f3a".repeat(16)],
  };
  // The real answer, with the held-out tier's three keys set to planted values: the screen must
  // draw none of them, whether the route serves them, omits them or counts them.
  const real = (await (await request.get(path)).json()) as { config: Record<string, unknown> };
  await page.route(`**${path}`, async (route) => {
    seen.api.add(path);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...real, config: { ...real.config, ...planted } }),
    });
  });
  await open(page, "?run=0/set-present-none");
  await expect(
    section(page, "System, as the run recorded it").locator(".pg-facts").first(),
  ).toBeVisible();
  const html = await page.evaluate(() => document.documentElement.outerHTML);
  for (const value of Object.values(planted).flat()) expect(html).not.toContain(value);
  for (const value of [...((real.config.held_out as string[] | undefined) ?? [])])
    expect(html).not.toContain(value);
});

function operatorHash(): string {
  const started = JSON.parse(readFileSync(join(RUNS, "started.json"), "utf8")) as {
    operator_url: string;
  };
  return new URL(started.operator_url).hash;
}

test("who decides here: as the operator, it can decide, and no part of the token is on the page", async ({
  page,
}) => {
  await watch(page);
  const hash = operatorHash();
  const token = decodeURIComponent(hash.replace(/^#act=/, ""));
  expect(token.length).toBeGreaterThan(16);
  await page.goto(`/?theme=light${hash}`);
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
  await page.evaluate(() => {
    window.location.hash = "#/home/settings";
  });
  await settle(page);
  const who = section(page, "Who decides here");
  await expect(who).toContainText("Decisions taken in this window are recorded as e2e-operator.");
  await expect(who).toContainText(SETTINGS_COPY.canDecide);
  const html = await page.evaluate(() => document.documentElement.outerHTML);
  for (let i = 0; i + 12 <= token.length; i += 1)
    expect(html).not.toContain(token.slice(i, i + 12));

  await open(page, "");
  await expect(section(page, "Who decides here")).toContainText(SETTINGS_COPY.cannotDecide);
});

test("the defaults for new runs are disabled, empty and say why; engines not offered are not choices", async ({
  page,
}) => {
  await watch(page);
  await open(page, "");
  const defaults = section(page, "Defaults for new runs");
  const controls = defaults.locator(".pg-facts input, .pg-facts select, .pg-facts button");
  expect(await controls.count()).toBeGreaterThanOrEqual(8);
  for (let i = 0; i < (await controls.count()); i += 1) {
    const control = controls.nth(i);
    await expect(control).toBeDisabled();
    const described = await control.getAttribute("aria-describedby");
    expect(described).not.toBeNull();
    await expect(page.locator(`[id="${described ?? ""}"]`)).toContainText(
      /A default kept here is coming\.|the harness refuses it when the reviewer starts\./,
    );
  }
  await expect(defaults.locator('[aria-pressed="true"]')).toHaveCount(0);
  for (const select of await defaults.locator("select").all()) await expect(select).toHaveValue("");
  await expect(defaults.locator('input[type="number"]')).toHaveValue("");
  await expect(defaults.locator('input[type="radio"]:checked')).toHaveCount(0);

  // Nothing on an engine's row is a control: the keyboard never stops inside one.
  const engines = section(page, "Engines");
  await expect(engines.locator('.pg-engine[data-status="not-yet"]')).not.toHaveCount(0);
  await expect(
    engines.locator(".pg-engine").locator("a, button, input, select, summary, [tabindex]"),
  ).toHaveCount(0);
  await expect(
    engines.locator('.pg-engine[data-status="not-yet"] .pg-status-dashed'),
  ).not.toHaveCount(0);
  await page.locator(".pg-skip-link").focus();
  for (let i = 0; i < 60; i += 1) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(
      () => document.activeElement?.closest(".pg-engine") !== null,
    );
    expect(inside).toBe(false);
  }
});

test("the foot item is reached from the keyboard, and the breadcrumb names This app", async ({
  page,
}) => {
  await watch(page);
  await page.goto("/?theme=light#/home/overview");
  await settle(page);
  const item = page.locator('.pg-nav-foot a[href="#/home/settings"]');
  await expect(item).toHaveText("Settings");
  let reached = false;
  for (let i = 0; i < 40 && !reached; i += 1) {
    await page.keyboard.press("Tab");
    reached = await item.evaluate((el) => el === document.activeElement);
  }
  expect(reached).toBe(true);
  await page.keyboard.press("Enter");
  await settle(page);
  await expect(page.locator(".pg-breadcrumb li")).toHaveText(["This app", "Settings"]);
});

test("theme and density chosen in Settings and in the top bar are one choice, both ways", async ({
  page,
}) => {
  await watch(page);
  await open(page, "", null);
  const look = section(page, "Appearance");
  await look.getByRole("group", { name: "Theme" }).getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator('button[title^="Theme"]')).toHaveAttribute(
    "title",
    "Theme: Dark. Change it",
  );
  await page.locator('button[title^="Density"]').click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "comfortable");
  await expect(
    look.getByRole("group", { name: "Density" }).getByRole("button", { name: "Comfortable" }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await settle(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    section(page, "Appearance")
      .getByRole("group", { name: "Theme" })
      .getByRole("button", { name: "Dark" }),
  ).toHaveAttribute("aria-pressed", "true");

  // A theme the address fixes holds the control disabled, and says so.
  await open(page, "", "light");
  const theme = section(page, "Appearance").getByRole("group", { name: "Theme" });
  for (const button of await theme.getByRole("button").all()) await expect(button).toBeDisabled();
  await expect(section(page, "Appearance")).toContainText("Fixed to light by this page's address");
});
