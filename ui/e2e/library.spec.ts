import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import {
  cspViolations,
  hitAreasShort,
  namesNoCommand,
  saysNoMoreThanTheRecord,
  styles,
  THEMES,
  TRANSPARENT,
  watch,
  type Watch,
} from "./support";

/**
 * The library end to end: the real server over a fixture library beside the runs, given by
 * `--library`, holding every state a library file can be in, a skill file that is a link and a
 * staged file not named as a candidate. In both themes and at both widths every section passes
 * axe, scrolls nowhere sideways, leads every row and heading with words, keeps each state
 * neutral and each value whole with its unit, shows no command and no act, asks the server for
 * library routes alone, and makes no outbound request.
 */

const WIDTHS = [1440, 1280] as const;
const SECTIONS = [
  "Standards",
  "Skills",
  "Reviewer rubrics",
  "Proposed · 4",
  "Data-sheet ratings",
] as const;

/** What each section draws once it has read what it reads. */
const READY: Readonly<Record<(typeof SECTIONS)[number], string>> = {
  Standards: 'table[aria-label="Standards"]',
  Skills: 'table[aria-label="Skills"]',
  "Reviewer rubrics": 'table[aria-label="Reviewer rubrics"]',
  "Proposed · 4": 'table[aria-label="Proposed changes"]',
  "Data-sheet ratings": 'table[aria-label="Energy store classes"]',
};

/** The routes this screen may read: the library's five, and nothing else. */
const LIBRARY_ROUTES: readonly RegExp[] = [
  /^\/api\/library$/,
  /^\/api\/library\/files\/(standards|skill|bounds)\/[a-z][a-z0-9_]*$/,
  /^\/api\/library\/staged$/,
  /^\/api\/library\/staged\/[A-Za-z0-9_-]+$/,
  /^\/api\/library\/ratings$/,
];

/** The paths a page asked for that are not this screen's routes. */
function unlisted(seen: Watch): string[] {
  return [...seen.api].filter((path) => !LIBRARY_ROUTES.some((route) => route.test(path)));
}

/** A path, a hex digest of 7 to 64 characters, or a candidate id: never what leads. */
const AN_ID =
  /^(knowledge\/|[\w.-]+\/[\w./-]+|[0-9a-f]{7,64}\b|cand-[\w-]+|[\w-]+\.(md|toml|json)\b)/;

/** The first texts of everything ``selector`` matches that read as an id. */
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
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
}

async function open(page: Page, theme: string, query = "", width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`/?theme=${theme}#/reference/library${query}`);
  await settle(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator(".pg-page-title")).toHaveText("Library");
}

function section(page: Page, name: string) {
  return page.locator('[aria-label="Library sections"]').getByRole("button", { name });
}

/**
 * Nothing on the page scrolls sideways: not the page, the content, the inspector, a file's text
 * or the changed lines, and, with no inspector open, no table either. With the inspector open the
 * content is 360 px narrower, and a table may then scroll inside its own region, which takes the
 * keyboard's focus for it.
 */
async function noSidewaysScroll(page: Page) {
  const wide = await page.evaluate(() => {
    const found: string[] = [];
    const root = document.scrollingElement;
    if (root !== null && root.scrollWidth > root.clientWidth + 1) found.push("the page");
    const inspecting = document.querySelector(".pg-inspector-region:not([hidden])") !== null;
    const selector = `.pg-content, .pg-inspector-slot, .pg-lib-text, .pg-lib-diff${
      inspecting ? "" : ", .pg-table-wrap"
    }`;
    for (const el of document.querySelectorAll<HTMLElement>(selector))
      if (el.scrollWidth > el.clientWidth + 1)
        found.push(`${el.className} ${el.getAttribute("aria-label") ?? ""}`.trim());
    return found;
  });
  expect(wide).toEqual([]);
}

/** What every section holds to, in every theme and at every width. */
async function holds(page: Page, seen: Watch, where: string) {
  await expect(page.locator('main [role="alert"]')).toHaveCount(0);
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(
    axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
    where,
  ).toEqual([]);
  await noSidewaysScroll(page);
  expect(
    await hitAreasShort(page, ".pg-seg button, .pg-lib-open, main .pg-id-copy"),
    where,
  ).toEqual([]);
  // Every value is a quantity inside a record that names its source.
  const unsourced = await page
    .locator(".pg-quantity")
    .evaluateAll((all) =>
      all.filter((q) => q.closest("[data-source]") === null).map((q) => q.textContent),
    );
  expect(unsourced, where).toEqual([]);
  // The states are neutral: never a verdict's glyph, class or colour.
  await expect(page.locator("main .pg-verdict-pass, main .pg-verdict-fail")).toHaveCount(0);
  expect(await page.locator("main").innerText()).not.toMatch(/[✓✕]/);
  // No control here acts, and none promotes or discards.
  await expect(page.locator(".pg-btn-act")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /promote|discard/i })).toHaveCount(0);
  await namesNoCommand(page, where);
  await saysNoMoreThanTheRecord(page, where);
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);
  expect(unlisted(seen), where).toEqual([]);
  const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
  if (evidence !== undefined) await page.screenshot({ path: `${evidence}/library-${where}.png` });
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`every section of the library, its rows led by words (${theme}, ${String(width)})`, async ({
      page,
    }) => {
      const seen = await watch(page);
      await open(page, theme, "", width);
      await expect(page.getByText("10 promotions recorded")).toBeVisible();
      for (const name of SECTIONS) {
        await section(page, name).click();
        await expect(page.locator(READY[name])).toBeVisible();
        await settle(page);
        await expect(section(page, name)).toHaveAttribute("aria-pressed", "true");
        expect(await idsLead(page, "main table tbody tr td:first-child")).toEqual([]);
        await holds(page, seen, `${name}-${theme}-${String(width)}`);
      }
    });
  }
}

test("the sections are reached from the keyboard alone", async ({ page }) => {
  await watch(page);
  await open(page, "light");
  await section(page, "Standards").focus();
  for (const [key, name] of [
    ["Tab", "Skills"],
    ["Tab", "Reviewer rubrics"],
  ] as const) {
    await page.keyboard.press(key);
    await expect(section(page, name)).toBeFocused();
    await page.keyboard.press(name === "Skills" ? "Enter" : "Space");
    await settle(page);
    await expect(section(page, name)).toHaveAttribute("aria-pressed", "true");
  }
  await expect(page.getByText("Rubric text is not shown here")).toBeVisible();
});

test("standards: each file's state, by its bytes; a domain's chip for the five domains only", async ({
  page,
}) => {
  await watch(page);
  await open(page, "light");
  const table = page.locator('table[aria-label="Standards"]');
  const row = (label: string) => table.locator("tbody tr", { hasText: label });
  await expect(row("Control standards").locator(".pg-status")).toHaveText("Matches its promotion");
  await expect(row("Electrical standards").locator(".pg-status")).toHaveText("No digest recorded");
  await expect(row("Cross-domain standards").locator(".pg-status")).toHaveText("Never promoted");
  await expect(row("Sizing standards").locator(".pg-status")).toHaveText("Matches its promotion");
  await expect(row("Sizing standards").locator(".pg-domain")).toHaveCount(0);
  await expect(row("Control standards").locator(".pg-domain-control")).toHaveText("Control");
  await expect(row("Cross-domain standards").locator(".pg-domain-cross")).toHaveCount(1);
  await expect(row("Control standards").locator(".pg-actor-human")).toHaveText(/Yasin Hessnawi/);
  // The neutral style: a state is never drawn as a verdict.
  await expect(table.locator(".pg-status.pg-verdict-pass, .pg-status.pg-verdict-fail")).toHaveCount(
    0,
  );
});

test("a file opens in the inspector, focus moves to it, and its text is text", async ({ page }) => {
  const seen = await watch(page);
  await open(page, "dark");
  await page
    .locator('table[aria-label="Standards"] tbody tr', { hasText: "Control standards" })
    .getByRole("link")
    .click();
  await settle(page);
  const inspector = page.locator(".pg-inspector-region");
  await expect(inspector.locator(".pg-inspector-title")).toHaveText("Control standards");
  // Focus lands once the shell has shown the region, a frame or so after the record is put there.
  await expect
    .poll(() =>
      page.evaluate(() => document.activeElement?.closest(".pg-inspector-region") !== null),
    )
    .toBe(true);
  await expect(inspector.locator(".pg-lib-text")).toContainText(
    "A loop is closed before it is tuned.",
  );
  const history = inspector.locator(".pg-lib-history li");
  await expect(history).toHaveCount(2);
  await expect(history.nth(1)).toContainText("Wrote this file");
  await expect(history.nth(0)).not.toContainText("Wrote this file");
  for (const chip of await styles(page, ".pg-inspector-region .pg-source", ["border-top-style"]))
    expect(chip["border-top-style"]).toBe("dashed");
  await expect(inspector.locator(".pg-source")).toHaveAttribute(
    "aria-label",
    "Source: knowledge/control/standards.md at no commit",
  );
  expect(await idsLead(page, ".pg-inspector-title")).toEqual([]);
  await holds(page, seen, "file-inspector");
});

test("a link inside the library and a misnamed staged file are rows of their own", async ({
  page,
}) => {
  await watch(page);
  await open(page, "light", "?tab=skills");
  const skills = page.locator('table[aria-label="Skills"] tbody tr');
  await expect(skills).toHaveCount(2);
  await expect(skills.filter({ hasText: "Electrical skill" })).toContainText(
    "This file is a link, so it is not read.",
  );
  await expect(skills.filter({ hasText: "Control skill" })).toContainText(
    "Differs from every promotion",
  );
  await section(page, "Proposed · 4").click();
  await settle(page);
  const changes = page.locator('table[aria-label="Proposed changes"] tbody tr');
  await expect(changes).toHaveCount(4);
  await expect(changes.filter({ hasText: "bad name.json" })).toContainText(
    "This file is not named as staging names a candidate, so promotion would not find it.",
  );
  await expect(page.locator('table[aria-label="Proposed antipatterns"] tbody tr')).toHaveText(
    /Proposed antipattern for the firmware skill/,
  );
});

test("a proposed change shows what promoting it would do, in words, with no act", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "light", "?tab=proposed");
  await page
    .locator('table[aria-label="Proposed changes"] tbody tr', {
      hasText: "Proposed change to the control standards",
    })
    .getByRole("link")
    .click();
  await settle(page);
  const inspector = page.locator(".pg-inspector-region");
  await expect(inspector.locator(".pg-inspector-title")).toHaveText(
    "Proposed change to the control standards",
  );
  await expect(inspector).toContainText("Replaces the whole file");
  await expect(inspector.locator('[data-fact="now"] .pg-quantity')).toContainText("B");
  await expect(inspector.locator('[data-fact="after"] .pg-quantity')).toContainText("B");
  await expect(inspector).toContainText("Changed lines (a view of the file before and after)");
  await expect(inspector).toContainText(
    "Promotion is done by a person at a terminal, by design: no agent session can change what later runs read.",
  );
  // Added lines in the accent, removed ones struck through: never a verdict's red or green.
  for (const del of await styles(page, ".pg-inspector-region del", ["text-decoration-line"]))
    expect(del["text-decoration-line"]).toContain("line-through");
  for (const ins of await styles(page, ".pg-inspector-region ins", [
    "background-color",
    "text-decoration-line",
  ])) {
    expect(ins["background-color"]).not.toBe(TRANSPARENT);
    expect(ins["text-decoration-line"]).toBe("none");
  }
  const accent = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--color-accent-bg").trim(),
  );
  expect(accent).not.toBe("");
  // Focus lands once the shell has shown the region, a frame or so after the record is put there.
  await expect
    .poll(() =>
      page.evaluate(() => document.activeElement?.closest(".pg-inspector-region") !== null),
    )
    .toBe(true);
  await holds(page, seen, "candidate-inspector");
});

test("ratings: whole values with their units, a source on each, every record one click away", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "light", "?tab=ratings", 1280);
  const range = page.locator('table[aria-label="Electrical bounds ranges"] tbody tr').first();
  await expect(range.locator(".pg-quantity")).toHaveText(["0.78Hz", "32000Hz"]);
  for (const cell of await styles(page, 'table[aria-label="Electrical bounds ranges"] td.pg-wrap', [
    "white-space",
    "text-overflow",
  ])) {
    expect(cell["white-space"]).not.toBe("nowrap");
    expect(cell["text-overflow"]).not.toBe("ellipsis");
  }
  await expect(page.locator('section[aria-label="Electrical bounds"]')).toContainText(
    "No envelope is loaded.",
  );
  await expect(
    page.locator('table[aria-label="Cross-domain bounds envelopes"] tbody tr'),
  ).toHaveCount(1);
  await expect(
    page.locator('table[aria-label="Energy store classes"] tbody tr .pg-quantity').first(),
  ).toContainText("1/h");
  for (const chip of await styles(page, "main .pg-source", ["border-top-style"]))
    expect(chip["border-top-style"]).toBe("dashed");
  await range.getByRole("link").click();
  await settle(page);
  const inspector = page.locator(".pg-inspector-region");
  await expect(inspector.locator(".pg-inspector-title")).toHaveText("Sample rate");
  await expect(inspector).toContainText("A fixture source, read on the date below.");
  await inspector.getByRole("link", { name: "Open the file" }).click();
  await settle(page);
  await expect(inspector.locator(".pg-inspector-title")).toHaveText("Electrical bounds");
  await expect(inspector.locator(".pg-lib-text")).toContainText("sample_rate");
  await expect(inspector.locator(".pg-status").first()).toHaveText("Never promoted");
  await holds(page, seen, "ratings-inspector");
});

test("the screen asks for its own routes alone, and a call to any other is caught", async ({
  page,
}) => {
  const seen = await watch(page);
  await open(page, "light");
  for (const name of SECTIONS) {
    await section(page, name).click();
    await expect(page.locator(READY[name])).toBeVisible();
    await settle(page);
  }
  expect([...seen.api].sort()).toEqual([
    "/api/library",
    "/api/library/ratings",
    "/api/library/staged",
  ]);
  expect(unlisted(seen)).toEqual([]);
  // A call this screen never makes, planted: the watch names it.
  const planted = ["/api", "library", "elsewhere"].join("/");
  await page.evaluate(async (path) => {
    await fetch(path);
  }, planted);
  expect(unlisted(seen)).toEqual([planted]);
  await page.evaluate(async () => {
    await fetch("/api/runs");
  });
  expect(unlisted(seen)).toEqual([planted, "/api/runs"]);
});
