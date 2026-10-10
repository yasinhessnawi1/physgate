import { appendFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { RUNS } from "../playwright.config";
import { PORT } from "./port";
import { cspViolations, styles, THEMES, TRANSPARENT, watch } from "./support";

/**
 * The approval queue end to end: the real server, started with an operator, over runs the real
 * loop escalated, each test on its own copy so none depends on another's decision. In both
 * themes the view renders the item whole, every quantity with its source, the binding styling
 * rules held, axe clean, nothing outbound and no content-security violation. A decision taken in
 * the page goes through its confirmation and lands as the queue's own line; a decision on a view
 * that went stale is refused with the server's reason; a decision made while a session's window
 * is open shows the queue's mark; and a page on another origin cannot take one at all.
 */

const ORIGIN = `http://127.0.0.1:${String(PORT)}`;

function rootOf(name: string): string {
  return `0/${name}`;
}

async function open(page: Page, theme: string, run: string) {
  await page.goto(`/?theme=${theme}#/collaboration/approval-queue?run=${rootOf(run)}`);
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator(".queue-detail")).toBeVisible();
}

interface Decided {
  readonly item_id: string;
  readonly decision: string;
  readonly resolved_by: string;
  readonly flag: string | null;
}

async function decisions(page: Page, run: string): Promise<readonly Decided[]> {
  const answer = await page.request.get(`${ORIGIN}/api/runs/0/${run}/queue`);
  expect(answer.status()).toBe(200);
  const listing = (await answer.json()) as { decided: Decided[] };
  return listing.decided;
}

/** The colour a token resolves to in this page's theme, as the browser computes it. */
async function tokenColour(page: Page, token: string): Promise<string> {
  return page.evaluate((name) => {
    const probe = document.createElement("span");
    probe.style.color = `var(${name})`;
    document.body.append(probe);
    const colour = getComputedStyle(probe).color;
    probe.remove();
    return colour;
  }, token);
}

for (const theme of THEMES) {
  test(`the queue shows an escalated item whole, held to the design (${theme})`, async ({
    page,
  }) => {
    const seen = await watch(page);
    await open(page, theme, "run-esc-view");
    await expect(page.locator('[role="alert"]')).toHaveCount(0);
    await expect(page.locator(".page-title")).toHaveText("Approval queue");
    const detail = page.locator(".queue-detail");
    await expect(detail.locator(".queue-decision")).toContainText("was rejected on all 3 attempts");
    await expect(detail.getByText("the stall current is too high")).toBeVisible();
    await expect(detail.locator(".queue-diff")).toContainText("diff --git");
    // Two cited quantities, each with its unit, inside the element naming the run they come from.
    await expect(detail.locator(".quantity")).toHaveCount(2);
    await expect(detail.locator(".quantity").first()).toHaveText("3.4A");
    const unsourced = await page
      .locator(".quantity")
      .evaluateAll((all) => all.filter((q) => q.closest("[data-source]") === null).length);
    expect(unsourced).toBe(0);
    // Every trajectory held to its seal.
    await expect(detail.locator("[data-status]")).toHaveCount(3);
    await expect(detail.locator('[data-status="holds"]')).toHaveCount(3);
    // The board's departures: no time on the item, no agent question, no run controls.
    await expect(page.getByText("Time on this item")).toHaveCount(0);
    await expect(page.getByText("Agent question")).toHaveCount(0);
    await expect(page.getByText("Start a run")).toHaveCount(0);

    // Act is solid action blue with a leading glyph; reject is a red outline.
    const [approve] = await styles(page, ".queue-actions > .button-act", [
      "background-color",
      "color",
    ]);
    expect(approve?.["background-color"]).toBe(await tokenColour(page, "--color-action"));
    expect(approve?.color).toBe(await tokenColour(page, "--color-action-text"));
    await expect(page.locator(".queue-actions > .button-act")).toHaveText("✓ Approve…");
    const [reject] = await styles(page, ".queue-actions > .button-reject", [
      "border-top-color",
      "border-top-style",
      "color",
      "background-color",
    ]);
    expect(reject?.["border-top-color"]).toBe(await tokenColour(page, "--color-fail"));
    expect(reject?.["border-top-style"]).toBe("solid");
    expect(reject?.color).toBe(await tokenColour(page, "--color-fail"));
    expect(reject?.["background-color"]).not.toBe(await tokenColour(page, "--color-fail"));
    expect(reject?.["background-color"]).not.toBe(TRANSPARENT);
    // Every button and item at least 44 px tall.
    const heights = await page.locator(".button, .run-link, .queue-item").evaluateAll((all) =>
      // Only what is drawn: a closed confirmation's buttons are not on the page.
      all
        .filter((el) => el.getClientRects().length > 0)
        .map((el) => el.getBoundingClientRect().height),
    );
    expect(heights.length).toBeGreaterThan(2);
    for (const height of heights) expect(height).toBeGreaterThanOrEqual(44);

    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
    ).toEqual([]);
    expect(seen.outbound).toEqual([]);
    expect(await cspViolations(page)).toEqual([]);
    const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
    if (evidence !== undefined)
      await page.screenshot({ path: `${evidence}/queue-${theme}.png`, fullPage: true });
  });
}

test("a rejection cannot be opened until its note says why", async ({ page }) => {
  await open(page, "light", "run-esc-view");
  const reject = page.locator(".queue-actions > .button-reject");
  await expect(reject).toBeDisabled();
  await expect(page.getByText("A rejection says why: write the note first.")).toBeVisible();
  await page.getByLabel("Note for the ledger (optional to approve, required to reject)").fill("x");
  await expect(reject).toBeEnabled();
  expect(await decisions(page, "run-esc-view")).toEqual([]);
});

test("a decision goes through its confirmation and lands as the queue's own line", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "light", "run-esc-approve");
  await page
    .getByLabel("Note for the ledger (optional to approve, required to reject)")
    .fill("accept the last attempt — checked by hand");
  await page.locator(".queue-actions > .button-act").click();
  const dialog = page.locator("dialog[open]");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    "This writes: one line appended to queue_decisions.jsonl in run run-esc",
  );
  const line = await dialog.locator(".confirm-line").textContent();
  expect(JSON.parse(line ?? "")).toMatchObject({
    kind: "resolution",
    decision: "approve: accept the last attempt — checked by hand",
    resolved_by: "e2e-operator",
  });
  await expect(dialog).toContainText("This cannot be edited or undone; the item closes.");
  const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
  if (evidence !== undefined)
    await page.screenshot({ path: `${evidence}/queue-confirm-light.png` });
  // Nothing is written until the person confirms.
  expect(await decisions(page, "run-esc-approve")).toEqual([]);
  await dialog.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.locator(".queue-decided-text")).toHaveText(
    "approve: accept the last attempt — checked by hand",
  );
  const recorded = await decisions(page, "run-esc-approve");
  expect(recorded).toHaveLength(1);
  expect(recorded[0]).toMatchObject({
    decision: "approve: accept the last attempt — checked by hand",
    resolved_by: "e2e-operator",
    flag: null,
  });
  await expect(page.locator(".queue-item-on .queue-decided")).toHaveText("Decided");
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);
});

test("a decision on a view whose trajectory changed since is refused with the server's reason", async ({
  page,
}) => {
  await open(page, "light", "run-esc-stale");
  const session = await page
    .locator('[data-status="holds"]')
    .first()
    .evaluate((badge) => {
      return badge.parentElement?.querySelector(".mono")?.textContent ?? "";
    });
  expect(session).not.toBe("");
  appendFileSync(join(RUNS, "runs", "run-esc-stale", "sessions", session, "stdout.jsonl"), "{}\n");
  await page.locator(".queue-actions > .button-act").click();
  await page.locator("dialog[open]").getByRole("button", { name: "Approve", exact: true }).click();
  const alert = page.locator('[role="alert"]');
  await expect(alert).toContainText("a trajectory of the item is no longer as it was shown");
  await expect(alert).toContainText("409");
  expect(await decisions(page, "run-esc-stale")).toEqual([]);
});

test("a decision made while a session's window is open shows the queue's own mark", async ({
  page,
}) => {
  await open(page, "light", "run-esc-window");
  await page.locator(".queue-actions > .button-act").click();
  await page.locator("dialog[open]").getByRole("button", { name: "Approve", exact: true }).click();
  const mark = "made while session still running or not yet resumed ran; confirm";
  await expect(page.locator(".queue-flag")).toContainText(mark);
  const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
  if (evidence !== undefined)
    await page.screenshot({ path: `${evidence}/queue-decided-marked-light.png`, fullPage: true });
  expect((await decisions(page, "run-esc-window"))[0]?.flag).toBe(mark);
});

test("a page on another origin cannot take a decision, read the token, or frame the page", async ({
  page,
}) => {
  const attacker = `http://localhost:${String(PORT + 1)}`;
  const target = `${ORIGIN}/api/runs/0/run-esc-forged/queue/decisions`;
  const body = JSON.stringify({
    item_id: "run-esc-s1-af41ca",
    verb: "approve",
    note: "forged",
    shown: { item_sha256: "0".repeat(64), trajectories: [] },
  });
  await page.route(`${attacker}/**`, (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><title>elsewhere</title>
<form id="f" method="POST" action="${target}" target="sink" enctype="text/plain">
<input name='${body.slice(0, -1)}' value='"}'></form>
<iframe name="sink"></iframe><iframe id="framed" src="${ORIGIN}/"></iframe>`,
    }),
  );
  await page.goto(`${attacker}/`);
  const outcomes = await page.evaluate(
    async ([url, json, home]) => {
      const tried: Record<string, string> = {};
      const attempt = async (name: string, run: () => Promise<Response>) => {
        try {
          const response = await run();
          tried[name] = `answered ${String(response.status)} (${response.type})`;
        } catch (error) {
          tried[name] = `failed: ${error instanceof Error ? error.name : String(error)}`;
        }
      };
      await attempt("json with a guessed token", () =>
        fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Physgate-Act-Token": "guess" },
          body: json,
        }),
      );
      await attempt("a simple text post", () =>
        fetch(url, {
          method: "POST",
          mode: "no-cors",
          headers: { "Content-Type": "text/plain" },
          body: json,
        }),
      );
      await attempt("reading the page for its token", () => fetch(home));
      (document.getElementById("f") as HTMLFormElement).submit();
      await new Promise((resolve) => setTimeout(resolve, 1500));
      return tried;
    },
    [target, body, `${ORIGIN}/`] as const,
  );
  // A request that needs a preflight never leaves; the page can neither read ours nor its token.
  expect(outcomes["json with a guessed token"]).toBe("failed: TypeError");
  expect(outcomes["reading the page for its token"]).toBe("failed: TypeError");
  // A simple post needs no preflight, so it is sent; the server refuses it (another origin), and
  // its own Cross-Origin-Resource-Policy keeps even the opaque answer from the page.
  expect(outcomes["a simple text post"]).toBe("failed: TypeError");
  // Framed, our page is refused by its own headers and shows nothing of itself.
  const framed = page.frameLocator("#framed");
  await expect(framed.locator(".queue-detail")).toHaveCount(0);
  expect(await decisions(page, "run-esc-forged")).toEqual([]);
});
