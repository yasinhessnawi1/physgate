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
gate "lint (published build)" cargo clippy --all-targets --locked --features published -- -D warnings -W clippy::pedantic
gate "lint (walkthrough build)" cargo clippy --all-targets --locked --features walkthrough -- -D warnings -W clippy::pedantic
gate "tests" cargo test --locked
gate "tests (published build)" cargo test --locked --features published
gate "tests (verification build)" cargo test --locked --features verification
gate "tests (walkthrough build)" cargo test --locked --features walkthrough
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
walkthrough_refused() {
    local said
    said="$(env -i HOME="$HOME" PATH=/usr/bin:/bin PHYSGATE_DESKTOP_HOME="$real" \
        bash ../../scripts/build-desktop.sh --walkthrough 2>&1)" && return 1
    case "$said" in *"installed app's folder"*) return 0 ;; *) return 1 ;; esac
}
gate "build script refuses the installed app's folder" refuses "installed app's folder" PHYSGATE_DESKTOP_HOME="$real"
gate "build script refuses a folder inside it" refuses "installed app's folder" PHYSGATE_DESKTOP_HOME="$real/trial"
gate "build script refuses the installed app's folder for a walkthrough build" walkthrough_refused
gate "build script refuses another capitalisation of it" refuses "installed app's folder" PHYSGATE_DESKTOP_HOME="$HOME/library/application support/PHYSGATE-DESKTOP"
# The firmlink spelling: no link and no case difference, so only the identity check sees it.
gate "build script refuses it by its firmlink spelling" refuses "installed app's folder" PHYSGATE_DESKTOP_HOME="/System/Volumes/Data$real"
gate "build script refuses it through a link" refuses "installed app's folder" PHYSGATE_DESKTOP_HOME="$trial/looks-elsewhere/x"
gate "build script lets a trial folder through to the next check" refuses "cargo is not on PATH" PHYSGATE_DESKTOP_HOME="$trial/own"
install_refused() {
    local said
    said="$(env -i HOME="$HOME" PATH=/usr/bin:/bin PHYSGATE_DESKTOP_HOME="$trial/own" \
        bash ../../scripts/build-desktop.sh --verification --install 2>&1)" && return 1
    case "$said" in *"never installed"*) return 0 ;; *) return 1 ;; esac
}
gate "build script refuses to install a trial build" install_refused
# What each kind of build would be signed with and built as, asked without building or
# reading any key: a trial build never plans the real key folder or identifier.
plan_is() {
    local expected="$1"
    shift
    local said
    said="$(env -i HOME="$HOME" PATH=/usr/bin:/bin "$@" --print-plan 2>&1)" || return 1
    case "$said" in *"$expected"*) return 0 ;; *) echo "planned: $said" >&2; return 1 ;; esac
}
build=(bash ../../scripts/build-desktop.sh)
for kind in --verification --walkthrough; do
    gate "a $kind build plans the trial key" plan_is "key_dir=$HOME/.config/physgate-desktop/trial" \
        PHYSGATE_DESKTOP_HOME="$trial/own" "${build[@]}" "$kind"
    gate "a $kind build plans the trial identifier" plan_is "identifier=local.physgate.desktop.trial" \
        PHYSGATE_DESKTOP_HOME="$trial/own" "${build[@]}" "$kind"
done
gate "the published build plans the real key and identifier" plan_is \
    "key_dir=$HOME/.config/physgate-desktop
identifier=local.physgate.desktop
features=--features published" "${build[@]}"
# Where both keys exist, the trial key is not the real one (public halves compared only).
keys_differ() {
    local real_pub="$HOME/.config/physgate-desktop/updater.key.pub"
    local trial_pub="$HOME/.config/physgate-desktop/trial/updater.key.pub"
    [ -f "$real_pub" ] && [ -f "$trial_pub" ] || return 0
    ! cmp -s "$real_pub" "$trial_pub"
}
gate "the trial signing key differs from the real one" keys_differ
rm -rf "$trial"
bash -n ../../scripts/build-desktop.sh || {
    echo "FAILED: desktop — build script syntax" >&2
    exit 1
}
echo "desktop: all gates passed"
