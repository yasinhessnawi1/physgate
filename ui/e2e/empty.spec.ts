import { type ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type Page, test } from "@playwright/test";

import { cspViolations, namesNoCommand, THEMES, watch } from "./support";

/**
 * The app on a machine with no run yet: the real server over an empty run folder, as the desktop
 * app starts it on its first day. The shell renders whole, Home leads with starting a project
 * (drawn disabled, coming soon), every other screen shows its own empty state, and no page
 * shows a terminal command.
 */

const CHECKOUT = fileURLToPath(new URL("../..", import.meta.url));

interface Started {
  readonly url: string;
  readonly operator_url: string;
}

interface Serving {
  readonly child: ChildProcessWithoutNullStreams;
  readonly started: Started;
}

/** The real `physgate ui` over `root`, on a free port, with the operator named. */
async function serve(root: string): Promise<Serving> {
  const child = spawn(
    "uv",
    ["run", "physgate", "ui", "--root", root, "--port", "0", "--operator", "e2e-operator"],
    { cwd: CHECKOUT },
  );
  const started = await new Promise<Started>((resolve, reject) => {
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
  return { child, started };
}

async function stop(child: ChildProcessWithoutNullStreams | undefined) {
  // Read afresh each time: the process ends while this waits.
  const running = () => child !== undefined && child.exitCode === null && child.signalCode === null;
  if (child === undefined || !running()) return;
  const stopped = new Promise((resolve) => child.once("exit", resolve));
  child.kill("SIGINT");
  await Promise.race([stopped, new Promise((resolve) => setTimeout(resolve, 10_000))]);
  if (running()) child.kill("SIGKILL");
}

let server: ChildProcessWithoutNullStreams | undefined;
let unreadableServer: ChildProcessWithoutNullStreams | undefined;
let folder = "";
let started: Started = { url: "", operator_url: "" };
let unreadable: Started = { url: "", operator_url: "" };

test.beforeAll(async () => {
  test.setTimeout(180_000);
  folder = mkdtempSync(join(tmpdir(), "physgate-ui-e2e-empty-"));
  const root = join(folder, "physgate-runs");
  mkdirSync(root, { mode: 0o700 });
  ({ child: server, started } = await serve(root));
  // A run folder whose one run cannot be read: its record is not JSON.
  const broken = join(folder, "unreadable-runs");
  mkdirSync(join(broken, "broken-run"), { recursive: true, mode: 0o700 });
  writeFileSync(join(broken, "broken-run", "run.json"), "{");
  ({ child: unreadableServer, started: unreadable } = await serve(broken));
});

test.afterAll(async () => {
  await stop(server);
  await stop(unreadableServer);
  if (folder !== "") rmSync(folder, { recursive: true, force: true });
});

function local(url: string = started.url): RegExp {
  return new RegExp(`^${url.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
}

async function settle(page: Page) {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
}

/**
 * The page's text holds no terminal command: what is drawn, and what is in the page but not
 * drawn (a closed disclosure, a hidden panel). No code or preformatted block stands in its
 * content either. The About page is the one exception to that: it sets the licences' own texts
 * as preformatted text, and its text is still held to the first rule.
 */
async function showsNoCommand(page: Page, where: string) {
  await namesNoCommand(page, where);
  if (where !== "#/about") await expect(page.locator("main code, main pre")).toHaveCount(0);
}

test("the server over an empty run folder serves the app and lists no runs", async ({
  request,
}) => {
  const listed = (await (await request.get(`${started.url}api/runs`)).json()) as {
    runs: unknown[];
  };
  expect(listed.runs).toEqual([]);
  const index = await request.get(started.url);
  expect(index.status()).toBe(200);
  expect(await index.text()).toContain("<!doctype html>");
});

for (const theme of THEMES) {
  test(`with no run, the shell renders and Home leads with starting a project (${theme})`, async ({
    page,
  }) => {
    const seen = await watch(page, local());
    await page.goto(`${started.url}?theme=${theme}${new URL(started.operator_url).hash}`);
    await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
    await settle(page);

    // The shell: navigation, the top bar, the palette and the collaborator's placeholder.
    await expect(page.locator('nav[aria-label="Areas"]')).toBeVisible();
    await expect(page.locator(".pg-topbar")).toBeVisible();
    await expect(page.locator(".pg-page-title")).toHaveText("Home");
    await expect(page.locator('[aria-label="The run shown"]')).toHaveText("No run yet");
    await page.keyboard.press("Control+k");
    const palette = page.locator("dialog.pg-palette[open]");
    await expect(palette).toBeVisible();
    await expect(palette.locator("input")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(palette).toHaveCount(0);
    await page.keyboard.press("Control+j");
    await expect(page.locator(".pg-dock-panel")).toHaveText(
      "The collaborator is not available in this build.",
    );
    await page.keyboard.press("Control+j");

    // Home: its empty state, led by the start control, disabled and said to be coming.
    const home = page.locator('.pg-state-empty[aria-label="No runs yet"]');
    await expect(home).toBeVisible();
    const start = home.getByRole("button", { name: "Start a project" });
    await expect(start).toBeDisabled();
    await expect(home.locator("button").first()).toHaveText("Start a project");
    await expect(start).toHaveAccessibleDescription("Coming soon");
    await expect(home.getByText("Coming soon", { exact: true })).toBeVisible();
    await showsNoCommand(page, "Home");

    // Notifications over no run: nothing open, and no command.
    await page.getByRole("button", { name: "Notifications" }).click();
    await expect(page.locator('section[aria-label="Notifications"]')).toBeVisible();
    await showsNoCommand(page, "Notifications");
    await page.keyboard.press("Escape");

    // Every other screen shows its own empty state, and no error.
    const hrefs = await page
      .locator('nav[aria-label="Areas"] a.pg-nav-link')
      .evaluateAll((links) => links.map((link) => link.getAttribute("href") ?? ""));
    expect(hrefs.length).toBeGreaterThanOrEqual(5);
    for (const href of hrefs) {
      await page.evaluate((hash) => {
        window.location.hash = hash;
      }, href);
      await settle(page);
      if (href !== "#/about") {
        await expect(page.locator(".pg-state-empty").first(), href).toBeVisible();
        await expect(page.locator('main [role="alert"]'), href).toHaveCount(0);
      }
      await showsNoCommand(page, href);
    }

    expect(seen.outbound).toEqual([]);
    expect(await cspViolations(page)).toEqual([]);
  });
}

test("with runs listed and none readable, Home lists each with its reason and starts nothing", async ({
  page,
}) => {
  const seen = await watch(page, local(unreadable.url));
  await page.goto(`${unreadable.url}?theme=light${new URL(unreadable.operator_url).hash}`);
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
  await settle(page);
  await expect(page.locator('.pg-state-empty[aria-label="No run here can be read"]')).toBeVisible();
  const listed = page.locator('section[aria-label="Runs"]');
  await expect(listed).toContainText("broken-run");
  await expect(listed).toContainText("Run broken-run could not be read:");
  // Not the first-day screen: there is a run, so nothing offers to start a project.
  await expect(page.getByRole("button", { name: "Start a project" })).toHaveCount(0);
  await showsNoCommand(page, "Home, none readable");
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);
});
