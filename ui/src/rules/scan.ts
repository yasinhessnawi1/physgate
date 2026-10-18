/**
 * The source scans the rules tests run: every file of the app's sources, read once, with the
 * patterns each rule refuses. Each scan has a planted example in its test that it must find.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const SRC = fileURLToPath(new URL("..", import.meta.url));

export interface SourceFile {
  readonly path: string;
  readonly text: string;
}

/** Every file under ``dir``, with its path relative to the sources. */
export function files(dir: string = SRC): SourceFile[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return files(path);
    return [{ path: relative(SRC, path), text: readFileSync(path, "utf8") }];
  });
}

export const isTest = (path: string): boolean => /\.test\.(ts|tsx)$/.test(path);

/** The words the operator UI never uses, in any case and any hyphenation. */
export const BANNED_WORDS: readonly RegExp[] = [/interview/i, /state[\s-]*of[\s-]*the[\s-]*art/i];

/** The private working tier's vocabulary, which no UI text carries. */
export const PRIVATE_WORDS: readonly RegExp[] = [
  /\bD-[A-Z][A-Z0-9]*-\d+/, // decision ids
  /\.docs\b/, // the private folder
  /\bspec_[A-Z]/, // spec files
  /\bUX\d+\b/, // UI slice ids
  /\bM-\d{2,3}\b/, // maintenance rows
  /\bT4\.\d/, // work-package task ids
  /SIGNOFF|kickoff|orchestrator ruling/i,
];

/** Quoted strings in a TypeScript source: what could end up on a page. */
export function strings(text: string): string[] {
  return [...text.matchAll(/"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`/g)].map(
    (m) => m[1] ?? m[2] ?? m[3] ?? "",
  );
}

const NAMED_COLOURS =
  "white|black|red|green|blue|gray|grey|orange|purple|yellow|pink|navy|teal|silver|maroon|olive|lime|aqua|fuchsia|cyan|magenta|brown|gold|indigo|violet|crimson|coral|salmon|tomato|tan|beige|ivory|khaki|lavender|plum|orchid|turquoise|transparentize";

/** A colour, a duration or a font family written as a value. */
export const LITERALS: readonly (readonly [string, RegExp])[] = [
  ["a hex colour", /#[0-9a-fA-F]{3,8}\b/],
  ["a colour function", /\b(rgba?|hsla?|hwb|oklch|oklab|lab|lch|color-mix|color)\(/],
  ["a named colour", new RegExp(`(^|[\\s:,(])(${NAMED_COLOURS})(?![\\w-])`, "i")],
  ["a duration", /(^|[^\w.-])\d*\.?\d+m?s\b/],
  [
    "a font family",
    /Instrument Sans|JetBrains Mono|IBM Plex|Helvetica|Arial|Roboto|Inter\b|Menlo|Consolas|system-ui|sans-serif|monospace|\bserif\b/,
  ],
];

/** The CSS declarations of a stylesheet, comments removed: the values a literal could hide in. */
export function declarations(css: string): string[] {
  return [...css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/[\w-]+\s*:\s*([^;{}]+)[;}]/g)].map(
    (m) => m[1] ?? "",
  );
}

/** The literal values a source writes: in a stylesheet, its declarations; in code, its strings. */
export function literalsIn(file: SourceFile): string[] {
  const values = file.path.endsWith(".css") ? declarations(file.text) : strings(file.text);
  return values.flatMap((value) =>
    LITERALS.filter(([, shape]) => shape.test(value)).map(
      ([what]) => `${file.path}: ${what} in "${value.trim().slice(0, 80)}"`,
    ),
  );
}

/** The module specifiers a source imports or re-exports, static and dynamic. */
export function specifiers(text: string): string[] {
  return [
    ...text.matchAll(
      /(?:import|export)\s[^'"]*?from\s*["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\)|import\s+["']([^"']+)["']/g,
    ),
  ].map((m) => m[1] ?? m[2] ?? m[3] ?? "");
}

export const THESIS = join(SRC, "thesis");

/** Whether ``spec``, imported from ``from``, lands inside the thesis folder. */
export function reachesThesis(from: string, spec: string): boolean {
  if (!spec.startsWith(".")) return /(^|\/)thesis(\/|$)/.test(spec);
  const target = resolve(dirname(join(SRC, from)), spec);
  return target === THESIS || target.startsWith(`${THESIS}/`);
}
