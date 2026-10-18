/**
 * The design tokens: `tokens.json` is the one source of every colour, type size, space, radius,
 * elevation, size, duration and font family. This module turns it into CSS custom properties,
 * once, at build time; no component writes a value of its own.
 *
 * - Colour and elevation per theme: light under `:root` and `[data-theme="light"]`, dark under
 *   `[data-theme="dark"]`. Both are designed; neither is the other inverted.
 * - Type and density per `[data-density]`: compact is the default, comfortable steps up.
 * - Space (0-indexed: `--space-0` is 2 px), radius, size, motion and the font stacks once.
 * - Under `prefers-reduced-motion` every duration is zero.
 *
 * It also measures colour: oklch to sRGB, for the contrast ratio and the OKLab distance the token
 * tests hold the palette to.
 */
import tokens from "./tokens.json" with { type: "json" };

export type Theme = "light" | "dark";
export type Density = "compact" | "comfortable";
export type ColorName = keyof typeof tokens.color.light;

export const THEMES: readonly Theme[] = ["light", "dark"];
export const DENSITIES: readonly Density[] = ["compact", "comfortable"];
/** The schema's domains, in the tokens' order. */
export const DOMAINS: readonly string[] = tokens.domains;

type Declarations = [string, string][];

function block(selector: string, declarations: Declarations): string {
  const body = declarations.map(([name, value]) => `  --${name}: ${value};`).join("\n");
  return `${selector} {\n${body}\n}\n`;
}

const px = (value: number): string => `${String(value)}px`;
const ms = (value: number): string => `${String(value)}ms`;

function colors(theme: Theme): Declarations {
  return Object.entries(tokens.color[theme]).map(([name, value]): [string, string] => [
    `color-${name}`,
    value,
  ]);
}

function elevation(theme: Theme): Declarations {
  return Object.entries(tokens.elevation[theme]).map(([name, value]): [string, string] => [
    `elevation-${name}`,
    value,
  ]);
}

/** One type style: [size, line, weight, transform, tracking]; a null or missing entry is unset. */
type TypeStyle = readonly (number | string | null)[];

function type(density: Density): Declarations {
  const found: Declarations = [];
  for (const [name, style] of Object.entries(tokens.type[density]) as [string, TypeStyle][]) {
    const [size, line, weight, transform, tracking] = style;
    if (typeof size === "number") found.push([`type-${name}-size`, px(size)]);
    if (typeof line === "number") found.push([`type-${name}-line`, px(line)]);
    if (typeof weight === "number") found.push([`type-${name}-weight`, String(weight)]);
    if (typeof transform === "string") found.push([`type-${name}-transform`, transform]);
    if (typeof tracking === "string") found.push([`type-${name}-tracking`, tracking]);
  }
  return found;
}

/** The density group's custom-property names: control and row heights, cell and card padding. */
const DENSITY_NAMES: Readonly<Record<string, string>> = {
  control: "size-control",
  row: "size-row",
  "nav-row": "size-nav-row",
  "cell-y": "pad-cell-y",
  "cell-x": "pad-cell-x",
  card: "pad-card",
  "gap-stack": "gap-stack",
};

function density(which: Density): Declarations {
  return Object.entries(tokens.density[which]).map(([name, value]): [string, string] => {
    const property = DENSITY_NAMES[name];
    if (property === undefined) throw new Error(`a density token with no property: ${name}`);
    return [property, px(value)];
  });
}

/** The motion durations, in milliseconds; easings and notes are not durations. */
export function durations(): [string, number][] {
  return Object.entries(tokens.motion).filter(
    (entry): entry is [string, number] => typeof entry[1] === "number",
  );
}

function shared(): Declarations {
  const found: Declarations = [
    ["font-sans", tokens.font.stack.sans],
    ["font-mono", tokens.font.stack.mono],
  ];
  tokens.space.forEach((value, index) => {
    found.push([`space-${String(index)}`, px(value)]);
  });
  for (const [name, value] of Object.entries(tokens.radius))
    found.push([`radius-${name}`, px(value)]);
  for (const [name, value] of Object.entries(tokens.size)) found.push([`size-${name}`, px(value)]);
  for (const [name, value] of Object.entries(tokens.border))
    found.push([`border-${name}`, px(value)]);
  for (const [name, value] of durations()) found.push([`motion-${name}`, ms(value)]);
  found.push(["ease-standard", tokens.motion["ease-standard"]]);
  found.push(["ease-exit", tokens.motion["ease-exit"]]);
  return found;
}

/** The stylesheet of custom properties. */
export function tokensCss(): string {
  const reduced = durations().map(([name]): [string, string] => [`motion-${name}`, "0ms"]);
  return [
    block(':root, [data-theme="light"]', [...shared(), ...colors("light"), ...elevation("light")]),
    block('[data-theme="dark"]', [...colors("dark"), ...elevation("dark")]),
    block(':root, [data-density="compact"]', [...type("compact"), ...density("compact")]),
    block('[data-density="comfortable"]', [...type("comfortable"), ...density("comfortable")]),
    `@media (prefers-reduced-motion: reduce) {\n${block(":root", reduced)}}\n`,
  ].join("\n");
}

/** A colour of ``theme`` by its token name. */
export function color(theme: Theme, name: ColorName): string {
  return tokens.color[theme][name];
}

/** A colour in OKLab: lightness and the two opposing axes. */
export interface Oklab {
  readonly l: number;
  readonly a: number;
  readonly b: number;
}

/** A colour as oklch: lightness, chroma and hue in degrees. */
export interface Oklch {
  readonly l: number;
  readonly c: number;
  readonly h: number;
}

const OKLCH = /^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:\/\s*[\d.]+\s*)?\)$/;
const HEX = /^#([0-9a-f]{6})$/i;

function linear(channel: number): number {
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function hexToOklab(hex: string): Oklab {
  const [r, g, b] = [0, 2, 4].map((i) => linear(parseInt(hex.slice(i, i + 2), 16) / 255)) as [
    number,
    number,
    number,
  ];
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return {
    l: 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    a: 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    b: 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  };
}

/** A token's value as oklch. Only the forms the token file uses: `oklch(…)` and `#rrggbb`. */
export function oklchOf(value: string): Oklch {
  const match = OKLCH.exec(value.trim());
  if (match !== null) {
    const [, l = "", c = "", h = ""] = match;
    return { l: Number(l), c: Number(c), h: Number(h) };
  }
  const hex = HEX.exec(value.trim());
  if (hex?.[1] !== undefined) {
    const lab = hexToOklab(hex[1]);
    const c = Math.hypot(lab.a, lab.b);
    const h = (Math.atan2(lab.b, lab.a) * 180) / Math.PI;
    return { l: lab.l, c, h: h < 0 ? h + 360 : h };
  }
  throw new Error(`not a colour the token file may hold: ${value}`);
}

/** A token's value in OKLab. */
export function oklabOf(value: string): Oklab {
  const { l, c, h } = oklchOf(value);
  const rad = (h * Math.PI) / 180;
  return { l, a: c * Math.cos(rad), b: c * Math.sin(rad) };
}

/** The Euclidean distance in OKLab (ΔE_OK) between two token values. */
export function distance(one: string, two: string): number {
  const [x, y] = [oklabOf(one), oklabOf(two)];
  return Math.hypot(x.l - y.l, x.a - y.a, x.b - y.b);
}

/** The colour in sRGB, each channel 0..1, clipped into the gamut. */
export function srgbOf(value: string): readonly [number, number, number] {
  const { l: L, a, b } = oklabOf(value);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const lin = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  const gamma = (c: number) =>
    c <= 0.0031308 ? 12.92 * Math.max(0, c) : 1.055 * c ** (1 / 2.4) - 0.055;
  const [r = 0, g = 0, bl = 0] = lin.map((c) => Math.min(1, Math.max(0, gamma(c))));
  return [r, g, bl];
}

function luminance(value: string): number {
  const [r, g, b] = srgbOf(value).map(linear) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** The WCAG 2 contrast ratio of two token values. */
export function contrast(one: string, two: string): number {
  const [hi, lo] = [luminance(one), luminance(two)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}
