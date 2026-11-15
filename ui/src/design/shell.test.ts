import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { namesACommand, shownText } from "../rules/commands";
import { literalsIn } from "../rules/scan";
import * as tokens from "./tokens";
import tokenFile from "./tokens.json" with { type: "json" };

/**
 * The desktop app's own pages (`desktop/status/`) are static files the shell bundles as they are,
 * with no build step. What holds them to the operator UI's design is here: their tokens are the
 * generator's output byte for byte, their fonts, icons and mark are the UI's own files, their
 * stylesheets write no colour, duration or font family of their own, and their markup and script
 * set no inline style, insert no markup and show no terminal command.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const UI = join(HERE, "..", "..");
const DESKTOP = join(UI, "..", "desktop");
const STATUS = join(DESKTOP, "status");
const WALKTHROUGH = join(DESKTOP, "src-tauri", "src", "walkthrough.rs");
const ENGINES = join(DESKTOP, "onboarding", "engines.json");

/** The app's own token stylesheet, as it was before the shell's copy was added beside it. */
const APP_TOKENS_SHA256 = "e8b66bfce78ecf2b24a807647a1310505fe7c0ccf9daff82fb3b1689e69d5097";

const sha256 = (bytes: Buffer): string => createHash("sha256").update(bytes).digest("hex");
const text = (path: string): string => readFileSync(path, "utf8");

/** The generator for the shell's copy, looked up so its absence fails an assertion. */
function shellTokensCss(): unknown {
  return (tokens as unknown as Record<string, unknown>).shellTokensCss;
}

/** The pages' files of one kind: `onboarding.js`, `status.js` and the like. */
function pages(extension: string): string[] {
  return readdirSync(STATUS)
    .filter((name) => name.endsWith(extension))
    .map((name) => join(STATUS, name));
}

const LABEL = /\b(?:aria-label|alt|title|placeholder|value)="([^"]*)"/g;

/**
 * The text an HTML page can show: all of it read whole (so a command split across elements is
 * still one text), each piece between tags, and its labels and alternatives.
 */
function htmlText(html: string): string[] {
  const uncommented = html.replace(/<!--[\s\S]*?-->/g, "");
  const body = uncommented.replace(/<(script|style)\b[\s\S]*?<\/\1>/gi, "");
  const pieces = body.split(/<[^>]*>/).map((piece) => piece.replace(/\s+/g, " ").trim());
  const labels = [...body.matchAll(LABEL)].map((m) => m[1] ?? "");
  return [pieces.join(" "), ...pieces.filter((piece) => piece !== ""), ...labels];
}

/** The two stylesheets that write the values every other one reads. */
const SHARED_SHEETS = ["tokens.css", "fonts.css"];
const CLICK = /click\("([^"]+)"\)/g;

const FONTS = text(join(HERE, "fonts.ts"));
const FACE = /"(@fontsource\/[^"?]+\.woff2)\?url"/g;
/** The faces the operator UI bundles, as `fonts.ts` imports them from their packages. */
const FACES = [...FONTS.matchAll(FACE)].map((m) => m[1] ?? "");

describe("the desktop app's tokens are the operator UI's", () => {
  it("the shell's copy is the generator's output, byte for byte", () => {
    const generator = shellTokensCss();
    expect(typeof generator).toBe("function");
    const file = join(STATUS, "tokens.css");
    expect(existsSync(file)).toBe(true);
    expect(text(file)).toBe((generator as () => string)());
  });

  it("the shell's copy has both themes from the system's preference, and compact type", () => {
    const file = join(STATUS, "tokens.css");
    expect(existsSync(file)).toBe(true);
    const css = text(file);
    expect(css).toContain(`--color-bg: ${tokenFile.color.light.bg};`);
    expect(css).toContain("@media (prefers-color-scheme: dark) {\n:root {\n");
    expect(css).toContain(`--color-bg: ${tokenFile.color.dark.bg};`);
    expect(css).toContain(`--type-body-size: ${String(tokenFile.type.compact.body[0])}px;`);
    expect(css).not.toContain("data-theme");
    expect(css).not.toContain("data-density");
  });

  it("the operator UI's own stylesheet is unchanged by it", () => {
    expect(sha256(Buffer.from(tokens.tokensCss()))).toBe(APP_TOKENS_SHA256);
  });

  it("the writer script writes exactly the generator's output, under the pinned Node", () => {
    const script = join(UI, "scripts", "tokens.mjs");
    expect(existsSync(script)).toBe(true);
    const out = mkdtempSync(join(tmpdir(), "physgate-shell-tokens-"));
    try {
      const written = join(out, "tokens.css");
      const run = spawnSync(process.execPath, [script, written], { encoding: "utf8" });
      expect(run.status, run.stderr).toBe(0);
      expect(text(written)).toBe((shellTokensCss() as () => string)());
    } finally {
      rmSync(out, { recursive: true, force: true });
    }
  });
});

describe("the desktop app's fonts, icons and mark are the operator UI's own files", () => {
  it("finds the faces the operator UI bundles", () => {
    expect(FACES.length).toBe(7);
  });

  it("each face is the pinned package's file, byte for byte, with its licence beside it", () => {
    for (const face of FACES) {
      const copy = join(STATUS, "fonts", basename(face));
      expect(existsSync(copy), copy).toBe(true);
      const pinned = sha256(readFileSync(join(UI, "node_modules", face)));
      expect(sha256(readFileSync(copy)), face).toBe(pinned);
    }
    for (const licence of readdirSync(join(HERE, "licences"))) {
      const copy = join(STATUS, "fonts", licence);
      expect(existsSync(copy), copy).toBe(true);
      expect(text(copy)).toBe(text(join(HERE, "licences", licence)));
    }
  });

  it("the faces are registered for the families and weights the tokens name", () => {
    const file = join(STATUS, "fonts.css");
    expect(existsSync(file)).toBe(true);
    const registered = [...text(file).matchAll(/@font-face\s*{([^}]*)}/g)].map((m) => {
      const rule = m[1] ?? "";
      const family = /font-family:\s*"([^"]+)"/.exec(rule)?.[1] ?? "";
      const weight = /font-weight:\s*(\d+)/.exec(rule)?.[1] ?? "";
      const src = /src:\s*url\("fonts\/([^"]+)"\)\s*format\("woff2"\)/.exec(rule)?.[1] ?? "";
      return `${family} ${weight} ${src}`;
    });
    const { sans, mono } = tokenFile.font.family;
    const wanted = FACES.map((face) => {
      const [, family, weight] = /\/files\/(.+)-latin-(\d+)-normal\.woff2$/.exec(face) ?? [];
      const name = family === "jetbrains-mono" ? mono : sans;
      return `${name} ${weight ?? ""} ${basename(face)}`;
    });
    expect(registered.sort()).toEqual(wanted.sort());
  });

  it("each icon is the operator UI's own, byte for byte, with Lucide's licence", () => {
    const icons = join(STATUS, "icons");
    expect(existsSync(icons)).toBe(true);
    const copies = readdirSync(icons);
    expect(copies).toContain("LICENSE.txt");
    expect(copies.length).toBeGreaterThan(1);
    for (const name of copies)
      expect(text(join(icons, name)), name).toBe(text(join(HERE, "icons", name)));
  });

  it("the mark is the design's", () => {
    const mark = join(STATUS, "mark.svg");
    expect(existsSync(mark)).toBe(true);
    expect(text(mark)).toBe(text(join(HERE, "brand", "mark.svg")));
  });

  it("every icon a stylesheet names is in the folder", () => {
    const missing: string[] = [];
    for (const sheet of pages(".css"))
      for (const m of text(sheet).matchAll(/url\("(icons\/[^"]+)"\)/g))
        if (!existsSync(join(STATUS, m[1] ?? ""))) missing.push(m[1] ?? "");
    expect(missing).toEqual([]);
  });
});

describe("the desktop app's stylesheets take every value from the tokens", () => {
  it("writes no colour, duration or font family but in the token and font files", () => {
    const own = pages(".css").filter((path) => !SHARED_SHEETS.includes(basename(path)));
    expect(own.length).toBeGreaterThan(1);
    const found = own.flatMap((path) => literalsIn({ path: basename(path), text: text(path) }));
    expect(found).toEqual([]);
  });

  it("each page loads the tokens, then the fonts, before its own styles", () => {
    for (const page of pages(".html")) {
      const links = [...text(page).matchAll(/<link rel="stylesheet" href="([^"]+)"/g)];
      const hrefs = links.map((m) => m[1] ?? "");
      expect(hrefs.slice(0, 2), basename(page)).toEqual(["tokens.css", "fonts.css"]);
    }
  });
});

describe("the desktop app's pages set no inline style and insert no markup", () => {
  it("no page carries a style attribute or a style element", () => {
    for (const page of pages(".html")) {
      expect(text(page), basename(page)).not.toMatch(/\sstyle\s*=/i);
      expect(text(page), basename(page)).not.toMatch(/<style\b/i);
    }
  });

  it("no script sets a style, or inserts markup", () => {
    const shapes = [
      /\.style\b/,
      /cssText/,
      /setAttribute\(\s*["']style/,
      /["']?style["']?\s*:/,
      /\b(?:innerHTML|outerHTML|insertAdjacentHTML|createContextualFragment|srcdoc)\b/,
      /document\.write/,
      /DOMParser/,
    ];
    const scripts = pages(".js");
    expect(scripts.map((path) => basename(path))).toContain("onboarding.js");
    for (const script of scripts)
      for (const shape of shapes) expect(text(script), basename(script)).not.toMatch(shape);
  });
});

describe("no page of the desktop app shows a terminal command", () => {
  it("finds none in any text a page or its script can show", () => {
    const found: string[] = [];
    for (const path of pages(".js"))
      for (const shown of shownText(path, text(path)))
        if (namesACommand(shown)) found.push(`${basename(path)}: ${shown.trim().slice(0, 120)}`);
    for (const path of pages(".html"))
      for (const shown of htmlText(text(path)))
        if (namesACommand(shown)) found.push(`${basename(path)}: ${shown.slice(0, 120)}`);
    expect(found).toEqual([]);
  });

  it("would find one in a page's text and in its labels, and none in its comments", () => {
    const inText = "<p>Then run <b>uv</b> sync here.</p>";
    const inLabel = '<button aria-label="uv run physgate">Go</button>';
    const inComment = "<!-- uv sync --><p>Plain words.</p>";
    expect(htmlText(inText).some(namesACommand)).toBe(true);
    expect(htmlText(inLabel).some(namesACommand)).toBe(true);
    expect(htmlText(inComment).some(namesACommand)).toBe(false);
  });
});

describe("the walkthrough still finds what it clicks", () => {
  it("every text it clicks by begins a button or an engine on the page", () => {
    const clicked = [...text(WALKTHROUGH).matchAll(CLICK)].map((m) => m[1] ?? "");
    expect(clicked.length).toBeGreaterThan(5);
    const catalogue = JSON.parse(text(ENGINES)) as { engines: { name: string }[] };
    const shown = [
      ...shownText("onboarding.js", text(join(STATUS, "onboarding.js"))),
      ...htmlText(text(join(STATUS, "onboarding.html"))),
      ...catalogue.engines.map((e) => e.name),
    ].map((s) => s.trim());
    const missing = clicked.filter((label) => !shown.some((s) => s.startsWith(label)));
    expect(missing).toEqual([]);
  });
});
