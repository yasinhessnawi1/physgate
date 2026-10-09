#!/usr/bin/env bash
#
# Build the operator UI and stamp the build with the digest of its sources.
#
# `physgate ui` refuses to serve a build whose stamp does not match the sources in the
# checkout, so a stale UI is never served; the stamp is written by the same Python code that
# checks it, so the two cannot disagree about what was hashed.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

(cd ui && pnpm run build)
uv run python -m physgate.ui.assets stamp ui
