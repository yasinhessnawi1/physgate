/** The four verdicts. Each has a glyph and a word, so none depends on colour alone. */
export type Verdict = "pass" | "fail" | "warn" | "unchecked";

export const VERDICT_SHOWN: Readonly<Record<Verdict, readonly [string, string]>> = {
  pass: ["✓", "Pass"],
  fail: ["✕", "Fail"],
  warn: ["!", "Warn"],
  unchecked: ["○", "Unchecked"],
};
