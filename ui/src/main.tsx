import "virtual:physgate-tokens.css";
import "./design/styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { takeTokenFromAddress } from "./api/client";
import { loadFonts } from "./design/fonts";
import { Shell } from "./shell/Shell";
import { VIEWS } from "./views/registry";

// Light is the default. Dark is defined in the tokens from the start; until the app offers a
// switch, `?theme=dark` selects it, which is how both themes are checked.
const theme =
  new URLSearchParams(window.location.search).get("theme") === "dark" ? "dark" : "light";
document.documentElement.dataset.theme = theme;
// The operator's address carries the action token in its fragment; it is taken once, kept in
// memory, and cleared from the address bar before anything else reads the address.
takeTokenFromAddress();
loadFonts();

const root = document.getElementById("root");
if (root === null) throw new Error("the page has no root element");
createRoot(root).render(
  <StrictMode>
    <Shell views={VIEWS} />
  </StrictMode>,
);
