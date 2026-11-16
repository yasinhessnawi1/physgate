import { type ChildProcessWithoutNullStreams, execFileSync, spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { fileURLToPath } from "node:url";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { RUNS } from "../playwright.config";
import { cspViolations, THEMES, watch } from "./support";

/**
 * The Evidence screen end to end: the real server over the evaluation's fixture runs (each kind
 * of run, a drifted run, a rewritten configuration and a log a later harness wrote), started by
 * this file over their own root so no other screen's test reads them. In both themes and at both
 * widths every tab passes axe; the page asks only with GETs, only for the screen's routes and the
 * shell's, and nothing leaves the origin; the reportable run's held-out tier is nowhere in the
 * page; a drifted pair shows the refusal and no number; and over an empty root the screen says
 * it reads no run.
 */

const CHECKOUT = fileURLToPath(new URL("../..", import.meta.url));
const EVIDENCE = join(RUNS, "evidence", "runs");
const WIDTHS = [1440, 1280] as const;

interface Started {
  readonly url: string;
}

const servers: ChildProcessWithoutNullStreams[] = [];
let folder = "";

/** The real `physgate ui` over `root`, on a free port, in a process group of its own. */
async function serve(root: string, library: string): Promise<Started> {
  const child = spawn(
    "uv",
    ["run", "physgate", "ui", "--root", root, "--library", library, "--port", "0"],
    { cwd: CHECKOUT, detached: true },
  );
  servers.push(child);
  return new Promise<Started>((resolve, reject) => {
    let out = "";
    let err = "";
    child.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString();
      try {
        resolve(JSON.parse(out) as Started);
      } catch {
        // The announcement is not whole yet.
      }
    });
    child.stderr.on("data", (chunk: Buffer) => {
      err += chunk.toString();
    });
    child.on("exit", (code) => {
      reject(new Error(`the server stopped before it served (${String(code)}): ${err}`));
    });
  });
}

/** The processes still running whose command line names `marker`, as `pid command` lines. */
function runningWith(marker: string): string[] {
  return execFileSync("ps", ["-A", "-ww", "-o", "pid=,command="], { encoding: "utf8" })
    .split("\n")
    .filter((line) => line.includes(marker))
    .map((line) => line.trim());
}

async function until(gone: () => boolean, ms: number) {
  const deadline = Date.now() + ms;
  while (!gone() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 50));
}

let evidence: Started = { url: "" };
let empty: Started = { url: "" };
/** The reportable run's held-out tier, as its record names it: none of it may reach a page. */
let withheld: string[] = [];

test.beforeAll(async () => {
  test.setTimeout(180_000);
  folder = mkdtempSync(join(tmpdir(), "physgate-ui-e2e-evidence-"));
  const library = join(folder, "knowledge");
  mkdirSync(library, { mode: 0o700 });
  const nothing = join(folder, "no-runs");
  mkdirSync(nothing, { mode: 0o700 });
  // The server is named by the folder this file made, so the stop below finds only its own.
  evidence = await serve(EVIDENCE, library);
  empty = await serve(nothing, library);
  const recorded = JSON.parse(
    readFileSync(join(EVIDENCE, "ev-reportable", "run.json"), "utf8"),
  ) as {
    held_out: string[];
    held_out_canaries: string[];
    held_out_sha256: string[];
  };
  withheld = [
    ...recorded.held_out,
    ...recorded.held_out.map((path) => basename(path)),
    ...recorded.held_out_canaries,
    ...recorded.held_out_sha256,
  ];
  expect(withheld.length).toBeGreaterThan(4);
});

test.afterAll(async () => {
  test.setTimeout(60_000);
  for (const child of servers) {
    if (child.pid === undefined || child.exitCode !== null) continue;
    try {
      process.kill(-child.pid, "SIGINT");
    } catch {
      // Gone already.
    }
  }
  await until(() => runningWith(folder).length === 0, 10_000);
  for (const line of runningWith(folder)) {
    try {
      process.kill(Number(line.split(" ")[0]), "SIGKILL");
    } catch {
      // Gone since it was listed.
    }
  }
  if (folder !== "") rmSync(folder, { recursive: true, force: true });
});

function local(url: string): RegExp {
  return new RegExp(`^${url.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
}

async function settle(page: Page) {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 60_000 });
}

/** The routes the page may ask: the screen's four, the price sheets, and what the shell reads. */
const ROUTES: readonly RegExp[] = [
  /^\/api\/evidence\/(runs|catches)$/,
  /^\/api\/evidence\/spend\/0\/[^/]+\/\d{4}-\d{2}-\d{2}$/,
  /^\/api\/evidence\/compare\/0\/[^/]+\/0\/[^/]+$/,
  /^\/api\/prices$/,
  /^\/api\/runs$/,
  /^\/api\/runs\/0\/[^/]+\/(queue|events|config|status)$/,
];

/** The screen at `query`, settled, with every request it makes watched and its methods kept. */
async function open(page: Page, query: string, theme = "light", width = 1440, at = evidence) {
  await page.setViewportSize({ width, height: 900 });
  const seen = await watch(page, local(at.url));
  const methods: string[] = [];
  page.on("request", (request) => {
    methods.push(request.method());
  });
  await page.goto(`${at.url}?theme=${theme}#/home/evidence${query}`);
  await settle(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator(".pg-page-title")).toHaveText("Evidence");
  return { seen, methods };
}

async function held(page: Page) {
  const html = await page.content();
  for (const value of withheld) expect(html, value).not.toContain(value);
}

const TABS = [
  ["runs", ""],
  ["spend", "&run=0/ev-development"],
  ["compare", "&a=0/ev-development&b=0/ev-ablation"],
  ["catches", ""],
] as const;

for (const theme of THEMES)
  for (const width of WIDTHS)
    test(`every tab in the ${theme} theme at ${String(width)} px passes axe, reads only, and keeps the held-out tier off the page`, async ({
      page,
    }) => {
      test.setTimeout(180_000);
      for (const [tab, extra] of TABS) {
        const { seen, methods } = await open(page, `?tab=${tab}${extra}`, theme, width);
        await expect(page.locator(`section[data-tab="${tab}"]`)).toBeVisible();
        await expect(page.locator(".pg-quantity-lg")).toHaveCount(0);
        const axe = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze();
        expect(
          axe.violations.map(
            (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
          ),
          tab,
        ).toEqual([]);
        const unsourced = await page
          .locator("main .pg-quantity")
          .evaluateAll((all) => all.filter((q) => q.closest("[data-source]") === null).length);
        expect(unsourced, tab).toBe(0);
        const wide = await page.evaluate(
          () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
        );
        expect(wide, `${tab} scrolls sideways`).toBe(false);
        await held(page);
        expect(new Set(methods), tab).toEqual(new Set(["GET"]));
        expect(
          [...seen.api].filter((path) => !ROUTES.some((r) => r.test(path))),
          tab,
        ).toEqual([]);
        expect(seen.outbound, tab).toEqual([]);
        expect(await cspViolations(page), tab).toEqual([]);
        const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
        if (evidence !== undefined)
          await page.screenshot({
            path: `${evidence}/evidence-${tab}-${theme}-${String(width)}.png`,
            fullPage: true,
          });
      }
    });

test("the screen is listed under Analyse, after Simulation, and its tabs change the address alone", async ({
  page,
}) => {
  await open(page, "");
  const analyse = page.locator('nav[aria-label="Areas"] section').filter({ hasText: "Analyse" });
  await expect(analyse.locator(".pg-nav-link")).toHaveText(["Simulation", "Evidence"]);
  await page.getByRole("button", { name: "Catches", exact: true }).click();
  await settle(page);
  expect(page.url()).toContain("tab=catches");
  await expect(page.locator('section[data-tab="catches"]')).toBeVisible();
});

test("the runs: each kind its own section, ablation last, each run tagged, the unread named", async ({
  page,
}) => {
  await open(page, "");
  const kinds = page.locator('section[data-tab="runs"] section[data-kind]');
  await expect(kinds).toHaveCount(3);
  expect(await kinds.evaluateAll((all) => all.map((s) => s.getAttribute("data-kind")))).toEqual([
    "reportable",
    "development",
    "ablation",
  ]);
  const runs = await page
    .locator("th[data-run]")
    .evaluateAll((all) => all.map((h) => h.getAttribute("data-run")));
  expect(runs).toEqual(["0/ev-reportable", "0/ev-development", "0/ev-drifted", "0/ev-ablation"]);
  await expect(kinds.nth(2)).toContainText(
    "Ablation run: measures what removing a part changes; never reportable",
  );
  await expect(kinds.nth(1).locator("td .evidence-kind-tag").first()).toHaveText("Not reportable");
  const unread = page.locator('section[aria-label="Runs that could not be read"]');
  await expect(unread.locator('[data-run="ev-tampered"]')).toContainText("Its run.json");
  await expect(unread.locator('[data-run="ev-unreadable"]')).toContainText("Its events.jsonl");
  await expect(page.locator('section[data-tab="runs"]')).toContainText(
    "The two gaps are not on this page yet: no measurement of them exists.",
  );
  await held(page);
});

test("the spend: each session beside its role's sum, the sum a view, a lower bound marked", async ({
  page,
}) => {
  await open(page, "?tab=spend&run=0/ev-development");
  const prices = (await (await page.request.get(`${evidence.url}api/prices`)).json()) as {
    prices: string[];
  };
  const newest = [...prices.prices].sort().at(-1) ?? "";
  await expect(page.locator('section[data-tab="spend"]')).toContainText(
    `Priced at the price sheet of ${newest}, the newest the server holds.`,
  );
  const answer = (await (
    await page.request.get(`${evidence.url}api/evidence/spend/0/ev-development/${newest}`)
  ).json()) as {
    view: string;
    line: { lower_bound: boolean };
    roles: { role: string; sessions: { session_id: string }[] }[];
  };
  for (const role of answer.roles) {
    const table = page.locator(`table[data-role="${role.role}"]`);
    await expect(table.locator("tbody tr")).toHaveCount(role.sessions.length);
    await expect(table.locator("tfoot")).toContainText(answer.view);
  }
  if (answer.line.lower_bound)
    await expect(page.locator('section[aria-label="The run\'s cost"]')).toContainText("at least");
  await expect(page.locator(".evidence-spend .evidence-mark")).toContainText("Not reportable");
});

test("two runs compared through the choosers, and a drifted pair refused with no number", async ({
  page,
}) => {
  await open(page, "?tab=compare");
  const panel = page.locator('section[data-tab="compare"]');
  await expect(panel).toContainText("Choose two runs to compare: a baseline and a candidate.");
  await panel.getByLabel("Baseline").selectOption("0/ev-development");
  await panel.getByLabel("Candidate").selectOption("0/ev-ablation");
  await settle(page);
  expect(page.url()).toContain("a=0%2Fev-development");
  await expect(panel.locator("table.evidence-compare")).toBeVisible();
  await expect(panel.locator('[data-note="differs"]')).toBeVisible();

  await panel.getByLabel("Candidate").selectOption("0/ev-drifted");
  await settle(page);
  const refused = panel.locator('[role="alert"]');
  await expect(refused).toContainText(
    "These two runs are not compared: they were run with different settings",
  );
  await expect(refused).toContainText("The model that plans the subtasks");
  await expect(refused).toContainText("The output token limit");
  await expect(panel.locator("table")).toHaveCount(0);
  await expect(panel.locator(".pg-quantity")).toHaveCount(0);

  await panel.getByLabel("Candidate").selectOption("0/ev-reportable");
  await settle(page);
  await expect(refused).toContainText("the tasks each run withheld differ");
  await expect(panel.locator("table")).toHaveCount(0);
  await held(page);
});

test("the catches: each kind counted apart, in order, a rate only as k of n", async ({ page }) => {
  await open(page, "?tab=catches");
  const panel = page.locator('section[data-tab="catches"]');
  const kinds = panel.locator("section[data-kind]");
  expect(await kinds.evaluateAll((all) => all.map((s) => s.getAttribute("data-kind")))).toEqual([
    "reportable",
    "development",
    "ablation",
  ]);
  await expect(panel.locator("tfoot")).toHaveCount(0);
  await expect(panel).not.toContainText("%");
  const after = panel.locator('tr[data-check="all"] td:last-child');
  for (const cell of await after.all()) await expect(cell).toHaveText(/^\d+ of \d+$/);
  await expect(panel.locator('section[aria-label="Runs not counted"]')).toContainText(
    "ev-unreadable",
  );
});

test("over an empty root the screen says it reads no run, and shows no error", async ({ page }) => {
  await open(page, "", "light", 1440, empty);
  await expect(page.locator(".pg-state-empty h2")).toHaveText("This server reads no run.");
  await expect(page.locator('main [role="alert"]')).toHaveCount(0);
});
