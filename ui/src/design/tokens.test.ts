import { describe, expect, it } from "vitest";

import tokens from "./tokens.json";
import { color, type ColorName, contrast, ON_ACTION, type Theme, tokensCss } from "./tokens";

const THEMES: readonly Theme[] = ["light", "dark"];

/** Every pair of text on its ground the components use. Each must reach 4.5 : 1. */
const TEXT_PAIRS: readonly (readonly [ColorName, ColorName])[] = [
  ["text", "bg"],
  ["text", "surface"],
  ["text", "surface-2"],
  ["text-2", "surface"],
  ["text-2", "bg"],
  ["text-3", "surface"],
  ["text-3", "bg"],
  ["text-3", "surface-2"],
  ["accent", "surface"],
  ["accent", "accent-bg"],
  ["pass", "pass-bg"],
  ["fail", "fail-bg"],
  ["fail", "surface"],
  ["warn", "warn-bg"],
  ["unchecked", "surface"],
  ["observe", "observe-hatch"],
  ["observe", "surface"],
  ["gate-on-text", "gate-on-bg"],
  ["gate-off", "gate-off-bg"],
  ["whatif", "whatif-bg"],
  ["whatif", "surface"],
  ["live", "live-bg"],
  ["domain-control", "surface"],
  ["domain-firmware", "surface"],
  ["domain-mechanical", "surface"],
];

describe("the token stylesheet", () => {
  it("declares every colour of both themes, and the scale once", () => {
    const css = tokensCss();
    for (const theme of THEMES) {
      for (const [name, value] of Object.entries(tokens.color[theme])) {
        expect(css).toContain(`--color-${name}: ${value};`);
      }
    }
    expect(css).toContain('[data-theme="dark"]');
    expect(css).toContain("--type-page-title-size: 28px;");
    expect(css).toContain("--size-sidebar: 256px;");
    expect(css).toContain('--font-mono: "IBM Plex Mono"');
  });
});

describe("contrast: all text at least 4.5 : 1 on its ground, in both themes", () => {
  for (const theme of THEMES) {
    for (const [fore, ground] of TEXT_PAIRS) {
      it(`${theme}: ${fore} on ${ground}`, () => {
        expect(contrast(color(theme, fore), color(theme, ground))).toBeGreaterThanOrEqual(4.5);
      });
    }
    it(`${theme}: action-button text on action`, () => {
      expect(contrast(ON_ACTION, color(theme, "action"))).toBeGreaterThanOrEqual(4.5);
    });
  }
  it("light: action-button text on action-hover", () => {
    expect(contrast(ON_ACTION, color("light", "action-hover"))).toBeGreaterThanOrEqual(4.5);
  });
  // The design's dark action-hover is lighter than its action, and white text on it measures
  // 3.78 : 1, below the design's own rule. Built as specified and raised with the design's owner;
  // this is marked as failing so the suite stays honest about it, and it turns red the day the
  // token changes, which is the signal to delete this marker.
  it.fails("dark: action-button text on action-hover (a known gap in the design)", () => {
    expect(contrast(ON_ACTION, color("dark", "action-hover"))).toBeGreaterThanOrEqual(4.5);
  });
});
