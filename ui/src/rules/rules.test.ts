import { describe, expect, it } from "vitest";

import { namesACommand, shownText, stylesheetText } from "./commands";
import {
  BANNED_WORDS,
  files,
  isTest,
  literalsIn,
  PRIVATE_WORDS,
  reachesThesis,
  specifiers,
} from "./scan";

const ALL = files();
/** The scans read every source but the tests and this folder, which hold the planted examples. */
const SHIPPED = ALL.filter((f) => !isTest(f.path) && !f.path.startsWith("rules/"));

describe("the sources", () => {
  it("are found", () => {
    expect(SHIPPED.length).toBeGreaterThan(40);
    expect(SHIPPED.some((f) => f.path.endsWith(".css"))).toBe(true);
  });
});

describe("the operator UI never says 'interview' or 'state of the art'", () => {
  it("finds neither in any source, in any case or hyphenation", () => {
    const found = SHIPPED.flatMap((f) =>
      BANNED_WORDS.filter((w) => w.test(f.text)).map((w) => `${f.path}: ${String(w)}`),
    );
    expect(found).toEqual([]);
  });

  it("would find either", () => {
    for (const planted of [
      "The Interview",
      "state-of-the-art",
      "State of the  Art",
      "STATE OF THE ART",
    ])
      expect(BANNED_WORDS.some((w) => w.test(planted))).toBe(true);
  });
});

describe("no private vocabulary reaches the UI", () => {
  it("finds none in any source", () => {
    const found = SHIPPED.flatMap((f) =>
      PRIVATE_WORDS.filter((w) => w.test(f.text)).map((w) => `${f.path}: ${String(w)}`),
    );
    expect(found).toEqual([]);
  });

  it("would find each kind", () => {
    // Each planted string is built at run time from parts, so no literal id sits in this file.
    const id = (...parts: string[]) => parts.join("-");
    for (const planted of [
      `see ${id("D", "QQQ", "0")}`,
      id("D", "QQ9", "0"),
      ["in .", "docs/specs"].join(""),
      ["spec", "Q9"].join("_"),
      ["U", "X0 adds it"].join(""),
      id("M", "00"),
      ["T4", "0-S00"].join("."),
    ])
      expect(PRIVATE_WORDS.some((w) => w.test(planted))).toBe(true);
  });
});

describe("the token file (and the module that turns it into CSS) is the only place a colour, a duration or a font family is written", () => {
  it("finds none in any stylesheet or source but the token file", () => {
    // The token module turns the token file into custom properties, so it alone writes them.
    const found = SHIPPED.filter(
      (f) => /\.(css|ts|tsx)$/.test(f.path) && f.path !== "design/tokens.ts",
    ).flatMap(literalsIn);
    expect(found).toEqual([]);
  });

  it("would find each kind", () => {
    const planted = [
      { path: "a.css", text: ".x { color: #fff; }" },
      { path: "a.css", text: ".x { background: oklch(0.5 0.1 200); }" },
      { path: "a.css", text: ".x { color: white; }" },
      { path: "a.css", text: ".x { transition: opacity 120ms ease; }" },
      { path: "a.css", text: ".x { animation: spin 1.4s linear infinite; }" },
      { path: "a.css", text: '.x { font-family: "Inter", sans-serif; }' },
      { path: "a.tsx", text: 'const s = { color: "#3b6fe0" };' },
      { path: "a.tsx", text: 'const s = { transition: "all 200ms" };' },
      { path: "a.tsx", text: 'const f = "JetBrains Mono";' },
    ];
    for (const file of planted) expect(literalsIn(file)).not.toEqual([]);
  });

  it("lets the tokens through", () => {
    expect(
      literalsIn({
        path: "a.css",
        text: ".x { color: var(--color-text); transition: opacity var(--motion-fast) var(--ease-standard); }",
      }),
    ).toEqual([]);
  });
});

describe("product code never imports the thesis-only views", () => {
  it("finds no import of the thesis folder from outside it", () => {
    const found = SHIPPED.filter(
      (f) => /\.(ts|tsx)$/.test(f.path) && !f.path.startsWith("thesis/"),
    ).flatMap((f) =>
      specifiers(f.text)
        .filter((s) => reachesThesis(f.path, s))
        .map((s) => `${f.path}: ${s}`),
    );
    expect(found).toEqual([]);
  });

  it("would find one, however it is written", () => {
    expect(reachesThesis("views/x/View.tsx", "../../thesis/Dashboard")).toBe(true);
    expect(reachesThesis("main.tsx", "./thesis")).toBe(true);
    expect(reachesThesis("main.tsx", "./thesis-free")).toBe(false);
    expect(specifiers('const D = lazy(() => import("./thesis/D"));')).toEqual(["./thesis/D"]);
    expect(specifiers('export { a } from "../thesis/a";')).toEqual(["../thesis/a"]);
  });
});

describe("no screen shows a terminal command", () => {
  /** The product's sources: every shipped source but the thesis-only views. */
  const PRODUCT = SHIPPED.filter((f) => !f.path.startsWith("thesis/"));

  it("finds none in any text a product source can show", () => {
    const sources = PRODUCT.filter((f) => /\.(ts|tsx|css)$/.test(f.path));
    expect(sources.length).toBeGreaterThan(40);
    const found = sources.flatMap((f) =>
      (f.path.endsWith(".css") ? stylesheetText(f.text) : shownText(f.path, f.text))
        .filter(namesACommand)
        .map((text) => `${f.path}: ${text.trim().slice(0, 120)}`),
    );
    expect(found).toEqual([]);
  });

  it("would find each kind", () => {
    for (const planted of [
      "physgate decompose <brief> --seed 1",
      "then physgate ui",
      "(physgate queue resolve)",
      "physgate\trun",
      'export CLAUDE_CODE_OAUTH_TOKEN="$(x)"',
      "export  A_1=b",
      "security find-generic-password -s physgate-trial",
      "physgate-x --run-dir /r",
      "cd /c && uv run pytest",
      "cd /c && uv sync",
      "scripts/build-ui.sh",
      "(cd ui && pnpm install --frozen-lockfile)",
    ])
      expect(namesACommand(planted), planted).toBe(true);
  });

  it("lets plain words through", () => {
    for (const prose of [
      "The physgate operator",
      "the physgate UI",
      "a physgate checkout",
      "physgate runs",
      "Export the table",
      "export as CSV",
      "the physgateui",
      "nophysgate run",
    ])
      expect(namesACommand(prose), prose).toBe(false);
  });

  it("reads the text a page shows, and not comments or code", () => {
    const source = [
      "// physgate run, in a comment",
      "/** physgate ui, in a doc comment */",
      "export const run = 1;",
      'const a = "one";',
      "const b = `two ${a} three`;",
      'const c = <p className="mono">Start with <code className="mono">physgate</code>{" "}<b>run</b>.</p>;',
    ].join("\n");
    const shown = shownText("a.tsx", source);
    expect(shown).toContain("one");
    expect(shown).toContain("two ");
    expect(shown).toContain(" three");
    expect(shown).toContain("Start with physgate run.");
    expect(shown.filter(namesACommand)).toEqual(["Start with physgate run."]);
    expect(shown.join(" ")).not.toMatch(/comment|const/);
    expect(stylesheetText('/* physgate ui */ .x::after { content: "uv run"; }')[0]).not.toMatch(
      /physgate/,
    );
    expect(stylesheetText('.x::after { content: "uv run"; }').some(namesACommand)).toBe(true);
  });
});
