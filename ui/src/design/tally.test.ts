import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import type { Verdict } from "./components/VerdictBadge";
import { evaluatedOf, tallyOf } from "./tally";

const SRC = fileURLToPath(new URL("..", import.meta.url));

describe("the one tally", () => {
  const outcomes: Verdict[] = [
    "pass",
    "unchecked",
    "fail",
    "unchecked",
    "warn",
    "pass",
    "unchecked",
  ];

  it("counts each outcome as written", () => {
    expect(tallyOf(outcomes)).toEqual({ pass: 2, fail: 1, warn: 1, unchecked: 3 });
  });

  it("never counts unchecked as a pass", () => {
    expect(tallyOf(["unchecked", "unchecked"])).toEqual({
      pass: 0,
      fail: 0,
      warn: 0,
      unchecked: 2,
    });
  });

  it("evaluates pass, fail and warn, and never unchecked", () => {
    expect(evaluatedOf(tallyOf(outcomes))).toBe(4);
    expect(evaluatedOf(tallyOf(["unchecked"]))).toBe(0);
  });

  it("counts nothing in nothing", () => {
    expect(tallyOf([])).toEqual({ pass: 0, fail: 0, warn: 0, unchecked: 0 });
  });
});

/** Every source file of the app, tests and the tally itself aside. */
function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sources(path);
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.(ts|tsx)$/.test(entry.name)) return [];
    return relative(SRC, path) === join("design", "tally.ts") ? [] : [path];
  });
}

/** The shapes a count of outcomes takes when a module writes its own. */
const OWN_COUNTS: readonly RegExp[] = [
  /\{\s*pass:\s*0\b/, // counters initialised
  /\[\s*[\w.]*outcome\s*\]\s*(\+\+|\+=)/, // a counter indexed by outcome
  /outcome\s*===\s*"(pass|fail|warn|unchecked)"[^;\n]*\)\s*\.length/, // a filtered length
  /\.pass\s*\+\s*[\w.]*\.?fail\b/, // an evaluated count summed by hand
];

describe("no module counts outcomes but the tally", () => {
  it("finds the app's sources", () => {
    expect(sources(SRC).length).toBeGreaterThan(10);
  });

  it("finds no count of outcomes outside the tally", () => {
    const found = sources(SRC).flatMap((path) => {
      const text = readFileSync(path, "utf8");
      return OWN_COUNTS.filter((shape) => shape.test(text)).map(
        (shape) => `${relative(SRC, path)}: ${String(shape)}`,
      );
    });
    expect(found).toEqual([]);
  });

  it("would find one", () => {
    const planted =
      "const counts = { pass: 0, fail: 0 };\nfor (const l of ls) counts[l.outcome] += 1;\n";
    expect(OWN_COUNTS.filter((shape) => shape.test(planted)).length).toBeGreaterThan(0);
  });
});
