#!/usr/bin/env bash
#
# The operator UI's gates: types, lint, format, unit tests, build, browser tests. Stops at the
# first failure and names it, like the Python gates it runs after.
#
# Without Node or pnpm this fails rather than skips: a gate that quietly does not run reports
# green while proving nothing.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
root=$PWD

fail() {
  echo
  echo "FAILED: $1"
  exit 1
}

command -v node >/dev/null || fail "ui — Node is not installed; the UI's gates cannot run"
command -v pnpm >/dev/null || fail "ui — pnpm is not on the PATH (enable it with corepack)"
[ -d ui/node_modules ] || fail "ui — dependencies are not installed: (cd ui && pnpm install --frozen-lockfile)"

run() {
  local name=$1
  shift
  echo "== ui: $name =="
  "$@" || fail "ui — $name"
}

# pnpm runs from inside ui/, where package.json pins its exact version for corepack; run from
# the repository root, corepack would find no pin and use whatever version it has.
cd ui
run "types" pnpm run typecheck
run "lint" pnpm run lint
run "format" pnpm run format:check
run "unit tests" pnpm run test
run "build" "$root/scripts/build-ui.sh"

# The browser tests serve on PHYSGATE_UI_E2E_PORT. Unset, every worktree used to ask for the same
# port, so two worktrees' checks running at once collided and the second refused to start. Unset
# now means a free loopback port, taken for this run alone, and the runs it built (named by the
# port, under the system's temporary directory) are removed when the run ends. A port that is
# named is used as before, and its runs are kept.
if [ -z "${PHYSGATE_UI_E2E_PORT:-}" ]; then
  PHYSGATE_UI_E2E_PORT=$(node -e '
    const net = require("node:net");
    const take = () => {
      const s = net.createServer().listen(0, "127.0.0.1", () => {
        const { port } = s.address();
        s.close(() => (port < 65535 ? console.log(port) : take()));
      });
    };
    take();') || fail "ui — no free loopback port for the browser tests"
  export PHYSGATE_UI_E2E_PORT
  e2e_runs="$(node -p 'require("node:os").tmpdir()')/physgate-ui-e2e-$PHYSGATE_UI_E2E_PORT"
  trap 'rm -rf "$e2e_runs"' EXIT
fi
run "browser tests" pnpm run e2e
