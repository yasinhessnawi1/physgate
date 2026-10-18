import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import tokens from "../src/design/tokens.json" with { type: "json" };
import { srgbOf } from "../src/design/tokens";
import {
  cspViolations,
  hitAreasShort,
  styles,
  THEMES,
  TRANSPARENT,
  watch,
  type Watch,
} from "./support";

/**
 * The component gallery in the browser: every component drawn, in both themes, at 1440 and 1280
 * px wide, and compact and comfortable. Graph labels wrap and are never cut, the Parts row fits
 * at 1280 with everything open, every number is in the bundled mono with tabular figures, every
 * control has a 44 px hit area and a visible focus ring, motion stops under reduced motion,
 * axe is clean, and nothing leaves the origin.
 */

const WIDTHS = [1440, 1280] as const;

/** A pattern that finds ``words`` whole inside a longer text, however its spaces were laid out. */
function wholeIn(words: string): RegExp {
  const escaped = words.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(escaped.replace(/\s+/g, "\\s+"));
}

async function open(page: Page, theme: string, width: number, height = 900): Promise<Watch> {
  const seen = await watch(page);
  await page.setViewportSize({ width, height });
  await page.goto(`/?theme=${theme}#/gallery`);
  await expect(page.locator('[data-gallery="data"]')).toBeVisible({ timeout: 30_000 });
  await page.evaluate(() => document.fonts.ready);
  return seen;
}

async function nothingLeft(page: Page, seen: Watch) {
  expect(seen.outbound).toEqual([]);
  expect(await cspViolations(page)).toEqual([]);
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test(`graph labels wrap and are never cut, and axe is clean (${theme}, ${String(width)})`, async ({
      page,
    }) => {
      const seen = await open(page, theme, width);
      const labels = await page.locator(".pg-node-label, .pg-node-id").evaluateAll((all) =>
        all.map((el) => {
          const style = getComputedStyle(el);
          return {
            text: el.textContent,
            fits: el.scrollWidth <= el.clientWidth,
            ellipsis: style.textOverflow,
            clamp: style.getPropertyValue("-webkit-line-clamp"),
            inButton: el.closest("button") !== null,
          };
        }),
      );
      expect(labels.length).toBeGreaterThan(20);
      for (const label of labels) {
        expect(label, label.text).toMatchObject({ fits: true, inButton: true });
        expect(label.ellipsis, label.text).not.toBe("ellipsis");
        expect(["none", ""]).toContain(label.clamp);
      }
      // The whole label and the whole key are in the node's accessible name, as the browser
      // computes it: a shorter name set over the visible text would leave a reader without them.
      const nodes = page.locator("button").filter({ has: page.locator(".pg-node-label") });
      expect(await nodes.count()).toBeGreaterThan(10);
      for (const node of await nodes.all())
        for (const words of await node.locator(".pg-node-label, .pg-node-id").allTextContents())
          await expect(node, words).toHaveAccessibleName(wholeIn(words));
      // A long label wraps onto more lines, and the canvas lays the cards out apart.
      const boxes = await page
        .locator(".pg-graph-layer .pg-node")
        .evaluateAll((all) => all.map((b) => b.getBoundingClientRect().toJSON() as DOMRect));
      for (const [i, a] of boxes.entries())
        for (const b of boxes.slice(i + 1)) {
          const apart =
            a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top;
          expect(apart).toBe(true);
        }
      const tall = await page
        .locator(".pg-graph-layer .pg-node-label")
        .evaluateAll((all) =>
          Math.max(
            ...all.map(
              (l) => l.getBoundingClientRect().height / parseFloat(getComputedStyle(l).lineHeight),
            ),
          ),
        );
      expect(tall).toBeGreaterThan(1.5);

      const axe = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
      ).toEqual([]);
      await nothingLeft(page, seen);
      const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
      if (evidence !== undefined)
        await page.screenshot({
          path: `${evidence}/gallery-${theme}-${String(width)}.png`,
          fullPage: true,
        });
    });
  }

  test(`the Parts row fits at 1280 with the nav, the inspector and the dock rail (${theme})`, async ({
    page,
  }) => {
    const seen = await open(page, theme, 1280, 900);
    await expect(page.locator(".pg-shell")).toHaveAttribute("data-nav", "expanded");
    await expect(page.locator(".pg-inspector-region")).toBeVisible();
    await expect(page.locator(".pg-dock-panel")).toHaveCount(0);
    const table = page.locator('[data-gallery="parts"] .pg-table-wrap').first();
    await table.scrollIntoViewIfNeeded();
    const fit = await table.evaluate((wrap) => {
      const inner = wrap.querySelector("table");
      const status = [...wrap.querySelectorAll<HTMLElement>(".pg-part-status")].find(
        (s) => s.textContent === "Specs 6 of 6 · gate checked: fail",
      );
      const box = wrap.getBoundingClientRect();
      const s = status?.getBoundingClientRect();
      return {
        overflow: (inner?.scrollWidth ?? 0) - wrap.clientWidth,
        found: status !== undefined,
        whole:
          status !== undefined &&
          s !== undefined &&
          status.scrollWidth <= status.clientWidth + 0.5 &&
          s.left >= box.left - 0.5 &&
          s.right <= box.right + 0.5,
      };
    });
    expect({ found: fit.found, whole: fit.whole }).toEqual({ found: true, whole: true });
    expect(fit.overflow).toBeLessThanOrEqual(0);
    await nothingLeft(page, seen);
    const evidence = process.env.PHYSGATE_UI_SCREENSHOTS;
    if (evidence !== undefined)
      await table.screenshot({ path: `${evidence}/parts-1280-${theme}.png` });
  });
}

test("every number, id, hash, unit and key is set in the bundled mono, tabular, with the zero apart", async ({
  page,
}) => {
  const seen = await open(page, "light", 1440);
  for (const selector of [
    ".pg-quantity",
    ".pg-id",
    ".pg-kbd",
    ".pg-tally-n",
    ".pg-source",
    ".pg-node-id",
  ]) {
    for (const s of await styles(page, selector, ["font-family", "font-variant-numeric"])) {
      expect(s["font-family"], selector).toContain(tokens.font.family.mono);
      expect(s["font-variant-numeric"], selector).toContain("tabular-nums");
      expect(s["font-variant-numeric"], selector).toContain("slashed-zero");
    }
  }
  // The face's own figures are one width: ten zeros are as wide as ten ones.
  const widths = await page.evaluate(() => {
    const probe = (text: string) => {
      const span = document.createElement("span");
      span.className = "mono";
      span.textContent = text;
      document.body.append(span);
      const w = span.getBoundingClientRect().width;
      span.remove();
      return w;
    };
    return [probe("0000000000"), probe("1111111111"), probe("8888888888")];
  });
  expect(widths[0]).toBeGreaterThan(0);
  expect(widths[1]).toBeCloseTo(widths[0] ?? 0, 3);
  expect(widths[2]).toBeCloseTo(widths[0] ?? 0, 3);
  // The faces in use are the bundled ones, loaded from this origin.
  const faces = await page.evaluate(() =>
    [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family.replace(/"/g, "")),
  );
  expect(faces).toEqual(expect.arrayContaining([tokens.font.family.sans, tokens.font.family.mono]));
  expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toMatch(
    new RegExp(`^"?${tokens.font.family.sans}`),
  );
  await nothingLeft(page, seen);
});

test("icons are drawn in the text's colour from files on this origin", async ({ page }) => {
  const seen = await open(page, "dark", 1440);
  const icons = await page.locator(".pg-icon").evaluateAll((all) =>
    all.map((el) => {
      const style = getComputedStyle(el);
      return {
        mask: style.getPropertyValue("mask-image"),
        background: style.backgroundColor,
        color: style.color,
      };
    }),
  );
  expect(icons.length).toBeGreaterThan(40);
  for (const icon of icons) {
    expect(icon.mask).toMatch(new RegExp(`^url\\("${new URL(page.url()).origin}/assets/`));
    expect(icon.background).toBe(icon.color);
  }
  await nothingLeft(page, seen);
});

test("the token colours the browser draws match the oklch arithmetic to two decimals", async ({
  page,
}) => {
  await open(page, "light", 1440);
  for (const theme of THEMES) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    for (const name of [
      "text",
      "accent",
      "pass",
      "fail",
      "warn",
      "observe",
      "whatif",
      "domain-electrical",
      "actor-human",
    ] as const) {
      const drawn = await page.evaluate((token) => {
        const probe = document.createElement("span");
        probe.style.color = `var(--color-${token})`;
        document.body.append(probe);
        const colour = getComputedStyle(probe).color;
        probe.remove();
        const canvas = document.createElement("canvas");
        canvas.width = 1;
        canvas.height = 1;
        const ctx = canvas.getContext("2d");
        if (ctx === null) return null;
        ctx.fillStyle = colour;
        ctx.fillRect(0, 0, 1, 1);
        return [...ctx.getImageData(0, 0, 1, 1).data.slice(0, 3)].map((c) => c / 255);
      }, name);
      const expected = srgbOf(tokens.color[theme][name]);
      expect(drawn, `${theme} ${name}`).not.toBeNull();
      for (const [i, channel] of expected.entries())
        expect(Math.abs((drawn?.[i] ?? 0) - channel), `${theme} ${name}`).toBeLessThan(0.01);
    }
  }
});

for (const density of ["compact", "comfortable"] as const) {
  test(`every control has a hit area of 44 by 44 px and a 2 px focus ring (${density})`, async ({
    page,
  }) => {
    const seen = await open(page, "light", 1440);
    if (density === "comfortable") await page.locator('button[title^="Density"]').click();
    await expect(page.locator("html")).toHaveAttribute("data-density", density);
    // Every kind of control a person can reach, the disclosures and graph nodes among them.
    const controls =
      ".pg-btn, .pg-seg button, .pg-hit, .pg-nav-link, .pg-table-filter, .pg-term-word, " +
      "button:not([disabled]), a[href], summary, select, [tabindex='0']";
    expect(await hitAreasShort(page, controls)).toEqual([]);
    const focus = await page.evaluate(() => {
      const probe = document.createElement("span");
      probe.style.color = "var(--color-focus)";
      document.body.append(probe);
      const colour = getComputedStyle(probe).color;
      probe.remove();
      return colour;
    });
    expect(focus).not.toBe(TRANSPARENT);
    // Every focusable control shows the ring when reached by keyboard; a text field shows it on
    // the wrapper around it.
    const rings = await page
      .locator("button:not([disabled]), a[href], input, textarea, select, [tabindex='0']")
      .evaluateAll((all) =>
        all
          .filter(
            (el) => el.getClientRects().length > 0 && el.closest("dialog:not([open])") === null,
          )
          .map((el) => {
            (el as HTMLElement).focus({ focusVisible: true });
            const field = el.matches("input, textarea")
              ? el.closest(".pg-field, .pg-table-filter")
              : null;
            const style = getComputedStyle(field ?? el);
            return {
              name: el.outerHTML.slice(0, 60),
              style: style.outlineStyle,
              width: style.outlineWidth,
              colour: style.outlineColor,
            };
          }),
      );
    expect(rings.length).toBeGreaterThan(30);
    // Solid, 2 px, and drawn in the focus colour: a ring in a transparent or borrowed colour is
    // no ring a person can see.
    expect(
      rings.filter((r) => r.style !== "solid" || r.width !== "2px" || r.colour !== focus),
    ).toEqual([]);
    await nothingLeft(page, seen);
  });
}

test("under observe nothing is filled, and the three gate modes draw apart", async ({ page }) => {
  await open(page, "light", 1440);
  for (const o of await styles(page, ".pg-observed", ["border-top-style", "background-color"]))
    expect(o).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
  const [on] = await styles(page, ".pg-gate-on", ["background-image", "background-color"]);
  const [observe] = await styles(page, ".pg-gate-observe", [
    "background-image",
    "border-top-style",
  ]);
  const [off] = await styles(page, ".pg-gate-off", ["background-image", "background-color"]);
  expect(on?.["background-image"]).toBe("none");
  expect(observe?.["background-image"]).not.toBe("none");
  expect(observe?.["border-top-style"]).toBe("dashed");
  expect(off?.["background-color"]).not.toBe(on?.["background-color"]);
  for (const u of await styles(page, ".pg-verdict-unchecked", [
    "border-top-style",
    "background-color",
  ]))
    expect(u).toEqual({ "border-top-style": "dashed", "background-color": TRANSPARENT });
  for (const w of await styles(page, ".pg-whatif", ["border-top-style"]))
    expect(w["border-top-style"]).toBe("dashed");
});

test("a state that is not a verdict is never drawn in the pass, fail or warn colours", async ({
  page,
}) => {
  await open(page, "light", 1440);
  for (const theme of THEMES) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
    }, theme);
    const tags = await page.locator(".pg-status").evaluateAll((all) => {
      const probe = document.createElement("span");
      document.body.append(probe);
      const verdicts = new Map<string, string>();
      for (const verdict of ["pass", "fail", "warn"])
        for (const part of ["", "-bg", "-border"]) {
          probe.style.color = `var(--color-${verdict}${part})`;
          verdicts.set(getComputedStyle(probe).color, `${verdict}${part}`);
        }
      probe.remove();
      return all.map((el) => {
        const drawn = [el, ...el.querySelectorAll("*")].flatMap((part) => {
          const s = getComputedStyle(part);
          return [
            s.color,
            s.backgroundColor,
            s.borderTopColor,
            s.borderRightColor,
            s.borderBottomColor,
            s.borderLeftColor,
          ];
        });
        return {
          kind: el.getAttribute("data-status-kind"),
          verdict: [...new Set(drawn.flatMap((c) => verdicts.get(c) ?? []))],
        };
      });
    });
    const kinds = new Set(tags.map((t) => t.kind));
    expect(kinds.size).toBeGreaterThanOrEqual(16);
    for (const kind of ["refused", "declined", "seal-tampered", "seal-missing"])
      expect(kinds.has(kind), kind).toBe(true);
    expect(
      tags.filter((t) => t.verdict.length > 0),
      theme,
    ).toEqual([]);
  }
});

test("motion comes from the tokens, and stops under reduced motion", async ({ page }) => {
  const durations = () =>
    page.evaluate(() =>
      [...document.querySelectorAll("*")].flatMap((el) => {
        const s = getComputedStyle(el);
        return [...s.transitionDuration.split(","), ...s.animationDuration.split(",")].map((d) =>
          parseFloat(d),
        );
      }),
    );
  await open(page, "light", 1440);
  expect((await durations()).some((d) => d > 0)).toBe(true);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await expect(page.locator('[data-gallery="data"]')).toBeVisible();
  expect((await durations()).filter((d) => d > 0)).toEqual([]);
});

test("the gallery is not in the navigation or the palette", async ({ page }) => {
  await open(page, "light", 1440);
  await expect(page.locator('nav[aria-label="Areas"] a[href*="gallery"]')).toHaveCount(0);
  await page.keyboard.press("Control+k");
  await expect(
    page.locator('dialog.pg-palette[open] [role="option"]', { hasText: /gallery/i }),
  ).toHaveCount(0);
});

test("density switches at run time, and the controls follow it", async ({ page }) => {
  await open(page, "light", 1440);
  const height = () =>
    page
      .locator('[data-gallery="actions"] .pg-btn')
      .first()
      .evaluate((b) => b.getBoundingClientRect().height);
  const compact = await height();
  await page.locator('button[title^="Density"]').click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "comfortable");
  expect(await height()).toBeGreaterThan(compact);
});
