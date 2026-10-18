/**
 * No screen shows a terminal command. What a command looks like comes from
 * `terminal-commands.json`, which the desktop shell's own test reads as well; this module turns
 * it into patterns, and reads out of a source the text a page can show: its strings, its JSX
 * text and its stylesheets' generated content, never its comments or its code.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";

interface Shapes {
  readonly subcommands: readonly string[];
  readonly phrases: readonly string[];
}

const SHAPES = JSON.parse(
  // A path, not a URL object: under a simulated DOM, URL is the DOM's own class.
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), "terminal-commands.json"), "utf8"),
) as Shapes;

const escaped = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * A phrase as a pattern. One that starts with a letter or digit starts a word, and one that
 * ends with one ends a word, so `uv run` is not found in `uv runs` nor `git ` in `legit `.
 */
function phraseShape(phrase: string): RegExp {
  const before = /^\w/.test(phrase) ? "(?<![\\w-])" : "";
  const after = /\w$/.test(phrase) ? "(?![\\w-])" : "";
  return new RegExp(`${before}${escaped(phrase)}${after}`);
}

/**
 * A terminal command: `physgate` followed by one of its subcommands, a shell variable exported
 * (`export NAME=`), or any phrase a command is made of.
 */
export const COMMAND_PATTERNS: readonly RegExp[] = [
  new RegExp(`(?<![\\w-])physgate\\s+(?:${SHAPES.subcommands.map(escaped).join("|")})(?![\\w-])`),
  /(?<![\w-])export\s+[A-Za-z_]\w*=/,
  ...SHAPES.phrases.map(phraseShape),
];

export function namesACommand(text: string): boolean {
  return COMMAND_PATTERNS.some((pattern) => pattern.test(text));
}

/**
 * The text a TypeScript source can put on a page: every string and template part, every JSX
 * text, and each JSX element's text read whole (so a command split across elements is still one
 * text). Comments and code are not text.
 */
export function shownText(path: string, source: string): string[] {
  const file = ts.createSourceFile(
    path,
    source,
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const found: string[] = [];
  const whole = (node: ts.Node): string => {
    // An element's attributes (its class names, its labels) are not part of its text.
    if (ts.isJsxAttributes(node)) return "";
    if (ts.isJsxText(node)) return node.text;
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
    return node
      .getChildren(file)
      .map(whole)
      .filter((text) => text !== "")
      .join("");
  };
  const visit = (node: ts.Node): void => {
    if (
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node) ||
      ts.isJsxText(node)
    )
      found.push(node.text);
    if (ts.isJsxElement(node) || ts.isJsxFragment(node))
      found.push(whole(node).replace(/\s+/g, " "));
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

/** A stylesheet's text, comments removed: generated content is the only text it can show. */
export function stylesheetText(css: string): string[] {
  return [css.replace(/\/\*[\s\S]*?\*\//g, "")];
}
