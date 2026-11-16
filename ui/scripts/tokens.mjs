// Writes the desktop app's copy of the design tokens, `desktop/status/tokens.css`, from the
// generator the operator UI builds with. The desktop app's pages have no build step, so the copy
// is committed, and a test holds it to the generator byte for byte. Node strips the generator's
// types as it loads it. An argument names another file to write, for that test.
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { shellTokensCss } from "../src/design/tokens.ts";

const COPY = new URL("../../desktop/status/tokens.css", import.meta.url);

writeFileSync(process.argv[2] ?? fileURLToPath(COPY), shellTokensCss());
