/**
 * IBM Plex Sans and IBM Plex Mono (SIL OFL 1.1), bundled as woff2 and registered through the
 * FontFace API. Nothing is fetched from elsewhere, and no inline style is needed, so the
 * server's content security policy can stay at "this origin only".
 */
import mono400 from "@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2?url";
import mono500 from "@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-500-normal.woff2?url";
import mono600 from "@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-600-normal.woff2?url";
import sans400 from "@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2?url";
import sans500 from "@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-500-normal.woff2?url";
import sans600 from "@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-600-normal.woff2?url";
import sans700 from "@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-700-normal.woff2?url";

/** Each face the design names: family, weight, file. */
export const FACES: readonly (readonly [string, string, string])[] = [
  ["IBM Plex Sans", "400", sans400],
  ["IBM Plex Sans", "500", sans500],
  ["IBM Plex Sans", "600", sans600],
  ["IBM Plex Sans", "700", sans700],
  ["IBM Plex Mono", "400", mono400],
  ["IBM Plex Mono", "500", mono500],
  ["IBM Plex Mono", "600", mono600],
];

/** Register every face with the document. Text renders in the fallback until each loads. */
export function loadFonts(): void {
  for (const [family, weight, url] of FACES) {
    const face = new FontFace(family, `url(${url}) format("woff2")`, { weight, display: "swap" });
    document.fonts.add(face);
    void face.load();
  }
}
