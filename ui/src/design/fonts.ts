/**
 * Instrument Sans and JetBrains Mono (SIL OFL 1.1), bundled as woff2 and registered through the
 * FontFace API. Nothing is fetched from elsewhere, and no inline style is needed, so the
 * server's content security policy can stay at "this origin only". The family names come from
 * the token file, the one place a font family is written.
 *
 * JetBrains Mono's latin files carry no `tnum` or `zero` feature: its digits are all one width
 * and its zero already has an inner mark, so the face itself keeps figures tabular and the zero
 * apart from the letter O.
 */
import mono400 from "@fontsource/jetbrains-mono/files/jetbrains-mono-latin-400-normal.woff2?url";
import mono500 from "@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff2?url";
import mono600 from "@fontsource/jetbrains-mono/files/jetbrains-mono-latin-600-normal.woff2?url";
import sans400 from "@fontsource/instrument-sans/files/instrument-sans-latin-400-normal.woff2?url";
import sans500 from "@fontsource/instrument-sans/files/instrument-sans-latin-500-normal.woff2?url";
import sans600 from "@fontsource/instrument-sans/files/instrument-sans-latin-600-normal.woff2?url";
import sans700 from "@fontsource/instrument-sans/files/instrument-sans-latin-700-normal.woff2?url";

import tokens from "./tokens.json" with { type: "json" };

const SANS = tokens.font.family.sans;
const MONO = tokens.font.family.mono;

/** Each face the design names: family, weight, file. */
export const FACES: readonly (readonly [string, string, string])[] = [
  [SANS, "400", sans400],
  [SANS, "500", sans500],
  [SANS, "600", sans600],
  [SANS, "700", sans700],
  [MONO, "400", mono400],
  [MONO, "500", mono500],
  [MONO, "600", mono600],
];

/** Register every face with the document. Text renders in the fallback until each loads. */
export function loadFonts(): void {
  for (const [family, weight, url] of FACES) {
    const face = new FontFace(family, `url(${url}) format("woff2")`, { weight, display: "swap" });
    document.fonts.add(face);
    void face.load();
  }
}
