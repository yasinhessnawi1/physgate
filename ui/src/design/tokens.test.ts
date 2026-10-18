import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import tokens from "./tokens.json";
import {
  color,
  type ColorName,
  contrast,
  DENSITIES,
  distance,
  DOMAINS,
  durations,
  oklchOf,
  THEMES,
  tokensCss,
} from "./tokens";

/** Every pair of text on its ground the components use. Each must reach 4.5 : 1. */
const TEXT_PAIRS: readonly (readonly [ColorName, ColorName])[] = [
  ["text", "bg"],
  ["text", "surface"],
  ["text", "surface-2"],
  ["text", "surface-3"],
  ["text", "accent-bg"],
  ["text-2", "surface"],
  ["text-2", "bg"],
  ["text-2", "surface-2"],
  ["text-3", "surface"],
  ["text-3", "bg"],
  ["text-3", "surface-2"],
  ["accent", "surface"],
  ["accent", "bg"],
  ["accent", "accent-bg"],
  ["pass", "pass-bg"],
  ["pass", "surface"],
  ["fail", "fail-bg"],
  ["fail", "surface"],
  ["warn", "warn-bg"],
  ["unchecked", "surface"],
  ["unchecked", "bg"],
  ["observe", "observe-hatch"],
  ["observe", "surface"],
  ["gate-on-text", "gate-on-bg"],
  ["gate-off", "gate-off-bg"],
  ["whatif", "whatif-bg"],
  ["whatif", "surface"],
  ["live", "live-bg"],
  ["live", "surface"],
  ["action-text", "action"],
  ["action-text", "action-hover"],
  ["surface", "text"],
  ["actor-deterministic", "actor-deterministic-bg"],
  ["actor-agent", "actor-agent-bg"],
  ["actor-collaborator", "actor-collaborator-bg"],
  ["actor-human", "actor-human-bg"],
  ["actor-deterministic", "surface"],
  ["actor-agent", "surface"],
  ["actor-collaborator", "surface"],
  ["actor-human", "surface"],
  ["actor-human", "surface-2"],
  // A domain chip sits on a surface, a node card (surface), or a selected card (accent ground).
  ...DOMAINS.flatMap((d): [ColorName, ColorName][] => [
    [`domain-${d}` as ColorName, "surface"],
    [`domain-${d}` as ColorName, "surface-2"],
    [`domain-${d}` as ColorName, "accent-bg"],
  ]),
];

/** Dashed borders of the states that are not recorded verdicts, and the focus ring: 3 : 1. */
const LINE_PAIRS: readonly (readonly [ColorName, ColorName])[] = [
  ["unchecked-border", "surface"],
  ["unchecked-border", "bg"],
  ["observe-border", "surface"],
  ["observe-border", "observe-hatch"],
  ["whatif-border", "surface"],
  ["whatif-border", "whatif-bg"],
  ["focus", "surface"],
  ["focus", "bg"],
  ["focus", "surface-2"],
  ["focus", "accent-bg"],
];

/** The colours reserved for a meaning, that carry a hue. A domain must stay clear of them. */
const CHROMATIC_RESERVED: readonly ColorName[] = [
  "actor-agent",
  "actor-collaborator",
  "actor-human",
  "pass",
  "fail",
  "warn",
  "observe",
  "whatif",
  "live",
  "accent",
];
const ACTORS: readonly ColorName[] = [
  "actor-deterministic",
  "actor-agent",
  "actor-collaborator",
  "actor-human",
];
const VERDICTS: readonly ColorName[] = ["pass", "fail", "warn", "unchecked"];

/** The least OKLab distance a domain keeps from a reserved hue, and an actor from a verdict. */
const LEAST_DISTANCE = 0.07;
/** The most chroma a domain may carry: domains are neutral, their word carries the meaning. */
const MOST_DOMAIN_CHROMA = 0.03;

describe("the token stylesheet", () => {
  const css = tokensCss();

  it("declares every colour and elevation of both themes, exactly as the token file says", () => {
    for (const theme of THEMES) {
      const selector = theme === "light" ? ':root, [data-theme="light"]' : '[data-theme="dark"]';
      const start = css.indexOf(`${selector} {`);
      expect(start).toBeGreaterThanOrEqual(0);
      const body = css.slice(start, css.indexOf("}", start));
      for (const [name, value] of Object.entries(tokens.color[theme]))
        expect(body).toContain(`--color-${name}: ${value};`);
      for (const [name, value] of Object.entries(tokens.elevation[theme]))
        expect(body).toContain(`--elevation-${name}: ${value};`);
    }
  });

  it("declares the type and the density of both densities under their selector", () => {
    for (const density of DENSITIES) {
      const selector =
        density === "compact" ? ':root, [data-density="compact"]' : '[data-density="comfortable"]';
      const start = css.indexOf(`${selector} {`);
      expect(start).toBeGreaterThanOrEqual(0);
      const body = css.slice(start, css.indexOf("}", start));
      for (const [name, style] of Object.entries(tokens.type[density]))
        expect(body).toContain(`--type-${name}-size: ${String(style[0])}px;`);
      for (const [name, value] of Object.entries(tokens.density[density]))
        expect(body).toMatch(new RegExp(`--[a-z-]*${name}: ${String(value)}px;`));
    }
    expect(css).toContain("--type-page-title-size: 22px;");
    expect(css).toContain("--type-page-title-size: 26px;");
    expect(css).toContain("--size-control: 30px;");
    expect(css).toContain("--size-control: 36px;");
  });

  it("declares space from zero, the sizes, the motion and the font stacks once", () => {
    tokens.space.forEach((value, index) => {
      expect(css.split(`--space-${String(index)}: ${String(value)}px;`)).toHaveLength(2);
    });
    expect(css).toContain("--space-0: 2px;");
    expect(css).toContain("--size-sidebar: 232px;");
    expect(css).toContain("--size-content-max: 1600px;");
    expect(css).toContain("--motion-fast: 100ms;");
    expect(css).toContain('--font-mono: "JetBrains Mono"');
    expect(css).toContain('--font-sans: "Instrument Sans"');
  });

  it("zeroes every duration under reduced motion", () => {
    const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(durations().length).toBeGreaterThan(3);
    for (const [name] of durations()) expect(reduced).toContain(`--motion-${name}: 0ms;`);
  });
});

describe("contrast: all text at least 4.5 : 1 on its ground, in both themes", () => {
  for (const theme of THEMES) {
    for (const [fore, ground] of TEXT_PAIRS) {
      it(`${theme}: ${fore} on ${ground}`, () => {
        expect(contrast(color(theme, fore), color(theme, ground))).toBeGreaterThanOrEqual(4.5);
      });
    }
  }
});

describe("contrast: dashed borders and the focus ring at least 3 : 1, in both themes", () => {
  for (const theme of THEMES) {
    for (const [line, ground] of LINE_PAIRS) {
      it(`${theme}: ${line} on ${ground}`, () => {
        expect(contrast(color(theme, line), color(theme, ground))).toBeGreaterThanOrEqual(3);
      });
    }
  }
});

/** The schema's domains, read from the Python source the records are validated against. */
function schemaDomains(): string[] {
  const schema = readFileSync(
    fileURLToPath(new URL("../../../src/physgate/state/schema.py", import.meta.url)),
    "utf8",
  );
  const line = /^DomainKind = Literal\[([^\]]*)\]/m.exec(schema);
  if (line?.[1] === undefined) throw new Error("the schema names no DomainKind");
  return [...line[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1] ?? "");
}

describe("the domains are the schema's five, neutral, and clear of every reserved hue", () => {
  it("are exactly the schema's DomainKind, with one colour token each", () => {
    expect([...DOMAINS].sort()).toEqual(schemaDomains().sort());
    for (const theme of THEMES) {
      const named = Object.keys(tokens.color[theme])
        .filter((k) => k.startsWith("domain-"))
        .map((k) => k.slice("domain-".length));
      expect(named.sort()).toEqual([...DOMAINS].sort());
    }
  });

  for (const theme of THEMES) {
    for (const domain of DOMAINS) {
      const name = `domain-${domain}` as ColorName;
      it(`${theme}: ${domain} is neutral (chroma at most ${String(MOST_DOMAIN_CHROMA)})`, () => {
        expect(oklchOf(color(theme, name)).c).toBeLessThanOrEqual(MOST_DOMAIN_CHROMA);
      });
      it(`${theme}: ${domain} is at least ${String(LEAST_DISTANCE)} from every reserved hue`, () => {
        const near = CHROMATIC_RESERVED.map(
          (other) => [other, distance(color(theme, name), color(theme, other))] as const,
        ).filter(([, d]) => d < LEAST_DISTANCE);
        expect(near).toEqual([]);
      });
    }
    it(`${theme}: electrical and the human actor are at least ${String(LEAST_DISTANCE)} apart`, () => {
      expect(
        distance(color(theme, "domain-electrical"), color(theme, "actor-human")),
      ).toBeGreaterThanOrEqual(LEAST_DISTANCE);
    });
  }
});

describe("the actor colours are distinct from the verdict colours", () => {
  for (const theme of THEMES) {
    for (const actor of ACTORS) {
      it(`${theme}: ${actor} is at least ${String(LEAST_DISTANCE)} from every verdict`, () => {
        const near = VERDICTS.map(
          (v) => [v, distance(color(theme, actor), color(theme, v))] as const,
        ).filter(([, d]) => d < LEAST_DISTANCE);
        expect(near).toEqual([]);
      });
    }
  }
});

describe("the colour arithmetic", () => {
  it("reads oklch and hex, and measures white on black as 21 : 1", () => {
    expect(contrast("#ffffff", "oklch(0 0 0)")).toBeCloseTo(21, 1);
    expect(oklchOf("#ffffff").l).toBeCloseTo(1, 3);
    expect(distance("oklch(0.5 0.1 0)", "oklch(0.5 0.1 0)")).toBe(0);
  });

  it("refuses a colour form the token file does not use", () => {
    expect(() => oklchOf("rebeccapurple")).toThrow(/not a colour/);
  });
});
