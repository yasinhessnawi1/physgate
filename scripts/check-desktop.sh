#!/usr/bin/env bash
#
# The desktop app's own gates: formatting, lints and unit tests, first-red.
#
# Not called from check.sh, so neither CI nor a machine without Rust runs it: the app is
# built and tried on the developer's machine, after each UI change that touches it.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../desktop/src-tauri"

command -v cargo > /dev/null || {
    echo "check-desktop: cargo is not on PATH" >&2
    exit 1
}

gate() {
    local name="$1"
    shift
    if ! "$@"; then
        echo "FAILED: desktop — $name" >&2
        exit 1
    fi
}

gate "format" cargo fmt --check
gate "lint" cargo clippy --all-targets --locked -- -D warnings -W clippy::pedantic
gate "lint (walkthrough build)" cargo clippy --all-targets --locked --features walkthrough -- -D warnings -W clippy::pedantic
gate "tests" cargo test --locked
bash -n ../../scripts/build-desktop.sh || {
    echo "FAILED: desktop — build script syntax" >&2
    exit 1
}
echo "desktop: all gates passed"
