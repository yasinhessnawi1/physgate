/**
 * What the Simulation screen's sources may not hold, read from the sources themselves: no
 * what-if, nothing that acts, no number the record lacks and no value rounded. Each rule has a
 * planted example it must find, built at run time so this file does not hold one itself.
 */
import { describe, expect, it } from "vitest";

import { files, isTest, type SourceFile } from "../../rules/scan";

/** The screen's own files and its words, not their tests. */
const SCREEN: readonly SourceFile[] = files().filter(
  (f) =>
    !isTest(f.path) && (f.path.startsWith("screens/simulation/") || f.path === "words/series.ts"),
);

const j = (...parts: string[]) => parts.join("");

/** A what-if element, a dashed series, or a control that runs or writes. */
const NO_WHAT_IF: readonly RegExp[] = [
  new RegExp(j("WhatIf", "Marker")),
  new RegExp(j("what", "If")),
  new RegExp(j('kind="what', 'if"')),
  new RegExp(j("pg-what", "if")),
  new RegExp(j("flask", "-conical")),
  new RegExp(j('variant="', 'act"')),
  new RegExp(j("Run ", "as")),
  /\bdash\s*:/,
  new RegExp(j("State", "Banner")),
];

/** A value rounded, or a number worked out over the samples. */
const NO_NUMBER_BORN_HERE: readonly RegExp[] = [
  new RegExp(j("to", "Fixed")),
  new RegExp(j("to", "Precision")),
  new RegExp(j("Math", "\\.(round|floor|ceil|min|max|trunc)")),
  new RegExp(j("Intl", "\\.NumberFormat")),
  new RegExp(j("rounded", "Label")),
  new RegExp(j("decimals", "=")),
  new RegExp(j("interpol", "at"), "i"),
];

/** Words that say more than the record does. */
const NO_CLAIM: readonly RegExp[] = [
  new RegExp(j("over", "shoot"), "i"),
  new RegExp(j("set", "tl"), "i"),
  new RegExp(j("rise", " time"), "i"),
  new RegExp(j("within ", "rating"), "i"),
  new RegExp(j("veri", "fied"), "i"),
  new RegExp(j("re", "-run"), "i"),
];

/** The one sentence that may say "re-run": that the harness did not. */
const PROVENANCE = j("The harness did not ", "re", "-run that code to confirm the curve.");

function found(rules: readonly RegExp[], text: (f: SourceFile) => string = (f) => f.text) {
  return SCREEN.flatMap((f) =>
    rules.filter((rule) => rule.test(text(f))).map((rule) => `${f.path}: ${String(rule)}`),
  );
}

describe("the Simulation screen's sources", () => {
  it("are found", () => {
    expect(SCREEN.map((f) => f.path)).toEqual(
      expect.arrayContaining([
        "screens/simulation/Simulation.tsx",
        "screens/simulation/model.ts",
        "screens/simulation/toolViews.ts",
        "words/series.ts",
      ]),
    );
  });

  it("hold no what-if element, no dashed series and no control that runs or writes", () => {
    expect(found(NO_WHAT_IF)).toEqual([]);
  });

  it("round no value and work out no number over the samples", () => {
    expect(found(NO_NUMBER_BORN_HERE)).toEqual([]);
  });

  it("claim nothing the record does not say, but that the harness did not re-run its code", () => {
    expect(found(NO_CLAIM, (f) => f.text.replace(PROVENANCE, ""))).toEqual([]);
    expect(SCREEN.find((f) => f.path === "words/series.ts")?.text).toContain(PROVENANCE);
  });

  it("would find each kind", () => {
    const planted = [
      j("<", "WhatIf", "Marker />"),
      j("what", "If: true"),
      j('<StateBanner kind="what', 'if" />'),
      j('<Button variant="', 'act" label="Run as a new run…" />'),
      j('icon="flask', '-conical"'),
      j("dash", ": [6, 4]"),
      j("value.to", "Fixed(2)"),
      j("Math", ".max(...values)"),
      j("new Intl", ".NumberFormat()"),
      j("rounded", "Label(v, 2)"),
      j("linear interpol", "ation"),
      j("settles in 38 ms with 4 % over", "shoot"),
      j("rise", " time"),
      j("within ", "rating"),
      j("veri", "fied by a re", "-run"),
    ];
    const all = [...NO_WHAT_IF, ...NO_NUMBER_BORN_HERE, ...NO_CLAIM];
    for (const text of planted)
      expect(
        all.some((rule) => rule.test(text)),
        text,
      ).toBe(true);
  });
});
