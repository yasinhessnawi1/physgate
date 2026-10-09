import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

import { tokensCss } from "./src/design/tokens.ts";

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
  plugins: [designTokens()],
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
