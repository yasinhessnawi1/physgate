import { describe, expect, it } from "vitest";

import tokens from "./tokens.json";
import { color, type ColorName, contrast, type Theme, tokensCss } from "./tokens";

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
  ["domain-electrical", "surface"],
  ["domain-cross", "surface"],
  // A node's domain chip sits on the node card, which is the surface or, selected, the accent's
  // ground.
  ["domain-control", "accent-bg"],
  ["domain-firmware", "accent-bg"],
  ["domain-mechanical", "accent-bg"],
  ["domain-electrical", "accent-bg"],
  ["domain-cross", "accent-bg"],
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
    for (const ground of ["action", "action-hover"] as const) {
      it(`${theme}: action-button text on ${ground}`, () => {
        expect(contrast(color(theme, "action-text"), color(theme, ground))).toBeGreaterThanOrEqual(
          4.5,
        );
      });
    }
  }
});
