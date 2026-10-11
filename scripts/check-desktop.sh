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
gate "tests (verification build)" cargo test --locked --features verification
# The build script's refusals, run with no cargo or node on PATH, so a refusal that fails
# to happen stops at "cargo is not on PATH" and is caught here, and nothing is ever built.
refuses() {
    local expected="$1"
    shift
    local said
    said="$(env -i HOME="$HOME" PATH=/usr/bin:/bin "$@" bash ../../scripts/build-desktop.sh --verification 2>&1)" && return 1
    case "$said" in *"$expected"*) return 0 ;; *) echo "said: $said" >&2; return 1 ;; esac
}
trial="$(mktemp -d)"
real="$HOME/Library/Application Support/physgate-desktop"
ln -s "$real" "$trial/looks-elsewhere"
gate "build script refuses a trial build with no trial folder" refuses "needs PHYSGATE_DESKTOP_HOME"
gate "build script refuses the installed app's folder" refuses "installed app's folder" PHYSGATE_DESKTOP_HOME="$real"
gate "build script refuses a folder inside it" refuses "installed app's folder" PHYSGATE_DESKTOP_HOME="$real/trial"
gate "build script refuses it through a link" refuses "installed app's folder" PHYSGATE_DESKTOP_HOME="$trial/looks-elsewhere/x"
gate "build script lets a trial folder through to the next check" refuses "cargo is not on PATH" PHYSGATE_DESKTOP_HOME="$trial/own"
install_refused() {
    local said
    said="$(env -i HOME="$HOME" PATH=/usr/bin:/bin PHYSGATE_DESKTOP_HOME="$trial/own" \
        bash ../../scripts/build-desktop.sh --verification --install 2>&1)" && return 1
    case "$said" in *"never installed"*) return 0 ;; *) return 1 ;; esac
}
gate "build script refuses to install a trial build" install_refused
rm -rf "$trial"
bash -n ../../scripts/build-desktop.sh || {
    echo "FAILED: desktop — build script syntax" >&2
    exit 1
}
echo "desktop: all gates passed"
