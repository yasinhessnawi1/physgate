import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

/**
 * The built bundle, read from disk: fonts and licences inside it, nothing that names another
 * origin, no inline style in the page, every asset under a name the server serves, and none of
 * the words the operator UI never uses.
 */

const UI = fileURLToPath(new URL("..", import.meta.url));
const DIST = join(UI, "dist");
const ASSETS = join(DIST, "assets");
/** The server's asset-name rule (`routes.py`), as written there. */
const ASSET_NAME = /^[A-Za-z0-9_][A-Za-z0-9._-]{0,255}$/;

function assets(): string[] {
  return readdirSync(ASSETS);
}

function read(name: string): string {
  return readFileSync(join(ASSETS, name), "utf8");
}

/** A reference to another origin in a stylesheet or a script: in url(), @import or src. */
const OUTBOUND: readonly RegExp[] = [
  /url\(\s*["']?\s*(https?:)?\/\//i,
  /@import\s+(url\()?\s*["']?\s*(https?:)?\/\//i,
  /\bsrc\s*[:=]\s*["'`]\s*(https?:)?\/\//i,
];

const BANNED: readonly RegExp[] = [/interview/i, /state[\s-]*of[\s-]*the[\s-]*art/i];

test("the fonts are bundled, and the Plex packages are gone", () => {
  const fonts = assets().filter((a) => a.endsWith(".woff2"));
  expect(fonts.filter((f) => f.startsWith("instrument-sans-latin-"))).toHaveLength(4);
  expect(fonts.filter((f) => f.startsWith("jetbrains-mono-latin-"))).toHaveLength(3);
  const pkg = JSON.parse(readFileSync(join(UI, "package.json"), "utf8")) as {
    dependencies: Record<string, string>;
  };
  expect(Object.keys(pkg.dependencies).filter((d) => d.includes("plex"))).toEqual([]);
  expect(pkg.dependencies["@fontsource/instrument-sans"]).toBe("5.3.0");
  expect(pkg.dependencies["@fontsource/jetbrains-mono"]).toBe("5.3.0");
});

test("the licences ship inside the app, for the fonts and the icons", () => {
  const scripts = assets()
    .filter((a) => a.endsWith(".js"))
    .map(read)
    .join("\n");
  expect(scripts).toContain("Copyright 2022 The Instrument Sans Project Authors");
  expect(scripts).toContain("Copyright 2020 The JetBrains Mono Project Authors");
  expect(scripts).toContain("SIL OPEN FONT LICENSE Version 1.1");
  expect(scripts).toContain("ISC License");
  expect(scripts).toContain("Lucide Contributors");
  // No licence is served as a file of a kind the server does not send.
  expect(assets().filter((a) => a.endsWith(".txt"))).toEqual([]);
});

test("the icons are the vendored files, drawn from this origin", () => {
  const svgs = assets().filter((a) => a.endsWith(".svg"));
  expect(svgs.length).toBeGreaterThanOrEqual(66 + 2);
  for (const svg of svgs) expect(read(svg)).not.toContain("c2pa");
});

test("no stylesheet or script names another origin in url(), @import or src", () => {
  const found = assets()
    .filter((a) => a.endsWith(".css") || a.endsWith(".js"))
    .flatMap((a) =>
      OUTBOUND.filter((shape) => shape.test(read(a))).map((shape) => `${a}: ${String(shape)}`),
    );
  expect(found).toEqual([]);
});

test("the outbound scan would find each form", () => {
  for (const planted of [
    "src: url(https://cdn.example/x.woff2)",
    '@import "//fonts.example/css";',
    'img.src = "https://example.org/p.png"',
  ])
    expect(OUTBOUND.some((shape) => shape.test(planted))).toBe(true);
  expect(OUTBOUND.some((shape) => shape.test("src: url(/assets/x.woff2)"))).toBe(false);
});

test("the page holds no inline style, and every asset has a name the server serves", () => {
  const index = readFileSync(join(DIST, "index.html"), "utf8");
  expect(index).not.toMatch(/<style/i);
  expect(index).not.toMatch(/\sstyle=/i);
  expect(assets().filter((a) => !ASSET_NAME.test(a))).toEqual([]);
});

test("the bundle never says 'interview' or 'state of the art'", () => {
  const all = [
    readFileSync(join(DIST, "index.html"), "utf8"),
    ...assets()
      .filter((a) => !a.endsWith(".woff2"))
      .map(read),
  ];
  const found = all.flatMap((text, i) =>
    BANNED.filter((w) => w.test(text)).map((w) => `${String(i)}: ${String(w)}`),
  );
  expect(found).toEqual([]);
  expect(BANNED.some((w) => w.test("STATE-OF-THE-ART"))).toBe(true);
});
