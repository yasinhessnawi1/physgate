import "virtual:physgate-tokens.css";
import "./design/components.css";
import "./shell/shell.css";
import "./views/legacy.css";
import "./screens/screens.css";

import { lazy, StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { takeTokenFromAddress } from "./api/client";
import { loadFonts } from "./design/fonts";
import {
  DENSITY_KEY,
  densityChoice,
  prefersDark,
  readStored,
  resolvedTheme,
  THEME_KEY,
  themeChoice,
  themeOverride,
} from "./shell/prefs";
import { Shell } from "./shell/Shell";
import { VIEWS } from "./screens/registry";

// The theme and density are set before the first paint, as the shell will keep them: the viewer's
// stored choice, or the system's theme until one is chosen. `?theme=dark` or `?theme=light`
// fixes the theme for this page without storing it, which is how both themes are checked.
document.documentElement.dataset.theme = resolvedTheme(
  themeOverride(window.location.search) ?? themeChoice(readStored(THEME_KEY)),
  prefersDark(),
);
document.documentElement.dataset.density = densityChoice(readStored(DENSITY_KEY));
// The operator's address carries the action token in its fragment; it is taken once, kept in
// memory, and cleared from the address bar before anything else reads the address.
takeTokenFromAddress();
loadFonts();

const pages = {
  gallery: lazy(() => import("./gallery/Gallery")),
  about: lazy(() => import("./about/About")),
};

const root = document.getElementById("root");
if (root === null) throw new Error("the page has no root element");
createRoot(root).render(
  <StrictMode>
    <Shell views={VIEWS} pages={pages} />
  </StrictMode>,
);
