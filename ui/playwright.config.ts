import { tmpdir } from "node:os";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

import { PORT } from "./e2e/port";

/**
 * Where the browser tests' runs are built: outside the repository, rebuilt every time, and named
 * by the port so two worktrees' runs never share a directory.
 */
export const RUNS = join(tmpdir(), `physgate-ui-e2e-${String(PORT)}`);

// The real server over real runs: the command builds three runs with the real loop (no model),
// then starts `physgate ui` on loopback over them. The app must be built and stamped first,
// which the check script does before this runs.
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${String(PORT)}`,
    trace: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `uv run python tests/ui_e2e_runs.py ${RUNS} && uv run physgate ui --root ${RUNS}/runs --port ${String(PORT)}`,
    cwd: "..",
    url: `http://127.0.0.1:${String(PORT)}/api/runs`,
    reuseExistingServer: false,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
