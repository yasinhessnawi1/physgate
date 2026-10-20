import { appendFileSync, readFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { RUNS } from "../playwright.config";
import { PORT } from "./port";
import {
  cspViolations,
  hitAreasShort,
  idsLeading,
  saysNoMoreThanTheRecord,
  styles,
  THEMES,
  TRANSPARENT,
  watch,
} from "./support";
import { DECISION_COPY } from "../src/words/queue";

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

/**
 * The operator's address, as `physgate ui --operator` printed it: the app's, with the action
 * token in its fragment. No route serves the token; this is how a person's browser gets it.
 */
function operatorUrl(): string {
  const started = JSON.parse(readFileSync(join(RUNS, "started.json"), "utf8")) as {
    operator_url: string;
  };
  return started.operator_url;
}

/** Open the operator's address, let the page take its token, then go to the run's queue. */
async function open(page: Page, theme: string, run: string, asOperator = true) {
  const address = new URL(operatorUrl());
  if (asOperator) {
    await page.goto(`/?theme=${theme}${address.hash}`);
    await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
    expect(page.url()).not.toContain("act=");
  } else {
    await page.goto(`/?theme=${theme}`);
  }
  await page.evaluate(
    (hash) => {
      window.location.hash = hash;
    },
    `/collaboration/approval-queue?run=${rootOf(run)}`,
  );
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator(".pg-queue-item")).toBeVisible();
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
    await expect(page.locator(".pg-page-title")).toHaveText("Queue");
    const detail = page.locator(".pg-queue-item");
    await expect(detail.locator(".pg-queue-decision")).toHaveText("A subtask used up its repairs");
    // The queue's own text is kept whole, folded under Details.
    await expect(detail.locator(".pg-queue-raw")).toContainText("was rejected on all 3 attempts");
    await expect(detail).toContainText(
      "The subtask was sent back on every attempt it was allowed, so no repair is left.",
    );
    await expect(detail.locator(".pg-seals summary")).toHaveText(
      "All 3 agent transcripts are intact (sealed).",
    );
    expect(
      await idsLeading(page, ".pg-queue-decision, .pg-queue-entry-title, .pg-section-label"),
    ).toEqual([]);
    await expect(detail.getByText("the stall current is too high")).toBeVisible();
    await expect(detail.locator(".pg-queue-diff")).toContainText("diff --git");
    // Two cited quantities, each with its unit, inside the element naming the run they come from.
    await expect(detail.locator(".pg-quantity")).toHaveCount(2);
    await expect(detail.locator(".pg-quantity").first()).toHaveText("3.4A");
    const unsourced = await page
      .locator(".pg-quantity")
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
    const [approve] = await styles(page, ".pg-queue-actions > .pg-btn-act", [
      "background-color",
      "color",
    ]);
    expect(approve?.["background-color"]).toBe(await tokenColour(page, "--color-action"));
    expect(approve?.color).toBe(await tokenColour(page, "--color-action-text"));
    // Its words end with "…" (it opens a confirmation), after a leading check.
    await expect(page.locator(".pg-queue-actions > .pg-btn-act")).toHaveText("Approve…");
    await expect(
      page.locator('.pg-queue-actions > .pg-btn-act > .pg-icon:first-child[data-icon="check"]'),
    ).toBeVisible();
    const [reject] = await styles(page, ".pg-queue-actions > .pg-btn-reject", [
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
    // Every button and item: a hit area of at least 44 by 44 px.
    expect(await hitAreasShort(page, ".pg-btn, .pg-run-link, .pg-queue-entry")).toEqual([]);
    await saysNoMoreThanTheRecord(page, `queue-${theme}`);

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

test("a page opened without the operator's address can only read, and says how to decide", async ({
  page,
}) => {
  await open(page, "light", "run-esc-view", false);
  await expect(page.locator(".pg-queue-actions > .pg-btn-act")).toBeDisabled();
  await expect(page.locator(".pg-queue-actions > .pg-btn-reject")).toBeDisabled();
  await expect(page.locator(".pg-queue-why-not")).toContainText(
    "This page was opened without the operator's address, so it can only read.",
  );
  await expect(page.locator(".pg-queue-actions > .pg-btn-act")).toHaveAccessibleDescription(
    /opened without the operator's address/,
  );
  // The page any local client can fetch carries no token, and neither does any response here.
  const index = await (await page.request.get(`${ORIGIN}/`)).text();
  const token = new URL(operatorUrl()).hash.replace("#act=", "");
  expect(index).not.toContain(token);
  expect(index).not.toContain("physgate-act-token");
  expect(await decisions(page, "run-esc-view")).toEqual([]);
});

test("a rejection cannot be confirmed blank: its confirmation waits for the reason", async ({
  page,
}) => {
  await open(page, "light", "run-esc-view");
  await page.locator(".pg-queue-actions > .pg-btn-reject").click();
  const dialog = page.locator("dialog[open]");
  const confirm = dialog.getByRole("button", { name: "Reject", exact: true });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("Reason · required").fill("   ");
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("Reason · required").fill("x");
  await expect(confirm).toBeEnabled();
  await expect(dialog.locator(".pg-writes-line")).toContainText('"decision":"reject: x"');
  await expect(dialog).toContainText(DECISION_COPY.then);
  await page.keyboard.press("Escape");
  expect(await decisions(page, "run-esc-view")).toEqual([]);
});

test("a decision goes through its confirmation and lands as the queue's own line", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "light", "run-esc-approve");
  await page.locator(".pg-queue-actions > .pg-btn-act").click();
  const dialog = page.locator("dialog[open]");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Note · optional").fill("accept the last attempt — checked by hand");
  await expect(dialog.locator(".pg-dialog-summary")).toHaveText(
    /^This records: e2e-operator approved '.*was rejected on all 3 attempts.*', with the note 'accept the last attempt — checked by hand'\.$/,
  );
  await expect(dialog).toContainText("One line appended to queue_decisions.jsonl in run run-esc");
  const line = await dialog.locator(".pg-writes-line").textContent();
  expect(JSON.parse(line ?? "")).toMatchObject({
    kind: "resolution",
    decision: "approve: accept the last attempt — checked by hand",
    resolved_by: "e2e-operator",
  });
  await expect(dialog).toContainText("Checked first, not written");
  await expect(dialog).toContainText(DECISION_COPY.then);
  await expect(dialog).toContainText("This cannot be edited or undone; the item closes.");
  const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
  if (evidence !== undefined)
    await page.screenshot({ path: `${evidence}/queue-confirm-light.png` });
  // Nothing is written until the person confirms.
  expect(await decisions(page, "run-esc-approve")).toEqual([]);
  await dialog.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.locator(".pg-queue-decided-text")).toHaveText(
    "approve: accept the last attempt — checked by hand",
  );
  const recorded = await decisions(page, "run-esc-approve");
  expect(recorded).toHaveLength(1);
  expect(recorded[0]).toMatchObject({
    decision: "approve: accept the last attempt — checked by hand",
    resolved_by: "e2e-operator",
    flag: null,
  });
  await expect(page.locator('.pg-queue-entry-on [data-status-kind="resolved"]')).toHaveText(
    "Resolved",
  );
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);
});

test("a decision on a view whose trajectory changed since is refused with the server's reason", async ({
  page,
}) => {
  await open(page, "light", "run-esc-stale");
  const session = await page
    .locator('[data-status="holds"] .pg-transcript-session')
    .first()
    .evaluate((el) => el.textContent);
  expect(session).not.toBe("");
  appendFileSync(join(RUNS, "runs", "run-esc-stale", "sessions", session, "stdout.jsonl"), "{}\n");
  await page.locator(".pg-queue-actions > .pg-btn-act").click();
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
  await page.locator(".pg-queue-actions > .pg-btn-act").click();
  await page.locator("dialog[open]").getByRole("button", { name: "Approve", exact: true }).click();
  const mark = "made while session still running or not yet resumed ran; confirm";
  await expect(page.locator(".pg-queue-flag")).toContainText(mark);
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
  await expect(framed.locator(".pg-queue-item")).toHaveCount(0);
  expect(await decisions(page, "run-esc-forged")).toEqual([]);
});
