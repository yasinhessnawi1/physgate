/**
 * The design tokens: `tokens.json` is the one source of every colour, type size, space, radius
 * and elevation, copied exactly from the design. This module turns it into CSS custom
 * properties, once, at build time; no component writes a value of its own.
 *
 * Light is the default theme and dark is defined from the start, under `[data-theme="dark"]`.
 */
import tokens from "./tokens.json" with { type: "json" };

export type Theme = "light" | "dark";
export type ColorName = keyof typeof tokens.color.light;

const FONT_STACKS = {
  sans: '"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif',
  mono: '"IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace',
} as const;

function block(selector: string, declarations: [string, string][]): string {
  const body = declarations.map(([name, value]) => `  --${name}: ${value};`).join("\n");
  return `${selector} {\n${body}\n}\n`;
}

function colors(theme: Theme): [string, string][] {
  return Object.entries(tokens.color[theme]).map(([name, value]): [string, string] => [
    `color-${name}`,
    value,
  ]);
}

function scale(): [string, string][] {
  const found: [string, string][] = [
    ["font-sans", FONT_STACKS.sans],
    ["font-mono", FONT_STACKS.mono],
  ];
  for (const [name, style] of Object.entries(tokens.type)) {
    found.push([`type-${name}-size`, `${String(style.size)}px`]);
    if ("line" in style) found.push([`type-${name}-line`, `${String(style.line)}px`]);
    found.push([`type-${name}-weight`, String(style.weight)]);
  }
  tokens.space.forEach((value, index) => {
    found.push([`space-${String(index + 1)}`, `${String(value)}px`]);
  });
  for (const [name, value] of Object.entries(tokens.radius))
    found.push([`radius-${name}`, `${String(value)}px`]);
  for (const [name, value] of Object.entries(tokens.elevation))
    found.push([`elevation-${name}`, value]);
  for (const [name, value] of Object.entries(tokens.size))
    found.push([`size-${name}`, `${String(value)}px`]);
  return found;
}

/** The stylesheet of custom properties: theme-independent values, then each theme's colours. */
export function tokensCss(): string {
  return [
    block(':root, [data-theme="light"]', [...scale(), ...colors("light")]),
    block('[data-theme="dark"]', colors("dark")),
  ].join("\n");
}

/** A colour of ``theme`` by its token name. */
export function color(theme: Theme, name: ColorName): string {
  return tokens.color[theme][name];
}

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const digits = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16)) as [
    number,
    number,
    number,
  ];
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** The WCAG 2 contrast ratio of two colours. */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}
