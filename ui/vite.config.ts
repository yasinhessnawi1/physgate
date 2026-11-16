import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

import { tokensCss } from "./src/design/tokens.ts";
import { thesisViews } from "./src/thesisSlot.ts";

/** The thesis folder's list of views: the slot holds it when the folder ships, and none if not. */
const THESIS_VIEWS = fileURLToPath(new URL("./src/thesis/views.ts", import.meta.url));

const TOKENS_ID = "virtual:physgate-tokens.css";
const RESOLVED_TOKENS_ID = "\0physgate-tokens.css";

/** The design tokens as CSS custom properties, generated from `tokens.json` at build time. */
function designTokens(): Plugin {
  return {
    name: "physgate-design-tokens",
    resolveId(id) {
      return id === TOKENS_ID ? RESOLVED_TOKENS_ID : null;
    },
    load(id) {
      return id === RESOLVED_TOKENS_ID ? tokensCss() : null;
    },
  };
}

// The app is served by the Python server from the build's own files, so the build reaches for
// nothing at run time: no CDN, no inline script or style, no chunk loaded from elsewhere.
// Every asset lands flat in `assets/`, which is all the server loads.
export default defineConfig({
  base: "/",
  plugins: [designTokens(), thesisViews(existsSync(THESIS_VIEWS) ? THESIS_VIEWS : null)],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets",
    assetsInlineLimit: 0,
    sourcemap: false,
    modulePreload: { polyfill: false },
  },
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    environment: "node",
    passWithNoTests: false,
  },
});
