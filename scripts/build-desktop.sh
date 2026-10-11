#!/usr/bin/env bash
#
# Build the desktop app around the operator UI, and publish it to the app's local update
# channel when the app itself changed.
#
#   scripts/build-desktop.sh            build; publish if the app changed
#   scripts/build-desktop.sh --install  the same, then put the app in ~/Applications
#   scripts/build-desktop.sh --verification
#                                       a trial build that honours the PHYSGATE_DESKTOP_...
#                                       switches; never for the real install
#
# The app shows whatever `physgate ui` serves from a checkout, so a UI change needs only
# scripts/build-ui.sh, never this. This is for changes under desktop/.
#
# Everything this writes outside the repository stays on this machine:
#   ~/.config/physgate-desktop/updater.key   the update signing key, made on the first run
#   ~/Library/Application Support/physgate-desktop/updates/
#                                             the update channel the installed app reads
# The signing key never enters the repository: the build reads it from that file, and
# only its public half is built into the app.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

install=0
features=()
for arg in "$@"; do
    case "$arg" in
        --install) install=1 ;;
        --verification) features=(--features verification) ;;
        -h | --help)
            sed -n '3,8p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "build-desktop: unknown option $arg (try --help)" >&2
            exit 2
            ;;
    esac
done

real_home="$HOME/Library/Application Support/physgate-desktop"
app_home="${PHYSGATE_DESKTOP_HOME:-$real_home}"
channel="$app_home/updates"
applications="${PHYSGATE_DESKTOP_APPLICATIONS:-$HOME/Applications}"
key_dir="$HOME/.config/physgate-desktop"
identifier=""
if [ ${#features[@]} -gt 0 ]; then
    # A trial build is signed with a key of its own and built under another identifier, so
    # the installed app refuses its bundles even if one reached the real channel, and the
    # two never share a window, a lock or WebKit's storage.
    key_dir="$HOME/.config/physgate-desktop/trial"
    identifier=",\"identifier\":\"local.physgate.desktop.trial\""
fi
key="$key_dir/updater.key"

die() {
    echo "build-desktop: $*" >&2
    exit 1
}

# A verification build honours the trial switches, so it never reaches the real install:
# it is not installed, and it is published only to a trial channel.
if [ ${#features[@]} -gt 0 ]; then
    [ "$install" = 0 ] || die "a --verification build is for trials and is never installed"
    [ -n "${PHYSGATE_DESKTOP_HOME:-}" ] || die "a --verification build needs PHYSGATE_DESKTOP_HOME set to a trial folder"
    # Compared after links and .. are resolved, so no spelling of the installed app's folder
    # (or of a folder inside it) gets through.
    resolve() { /usr/bin/python3 -I -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
    given="$(resolve "$PHYSGATE_DESKTOP_HOME")"
    real="$(resolve "$real_home")"
    case "$given/" in
        "$real/"*) die "$PHYSGATE_DESKTOP_HOME is the installed app's folder, or inside it; a --verification build needs a trial folder of its own" ;;
    esac
fi

command -v cargo > /dev/null || die "cargo is not on PATH; install Rust (brew install rust) and try again"
command -v node > /dev/null || die "node is not on PATH; open a new Terminal window or install Node 22"
pnpm="$(command -v pnpm || echo "$HOME/Library/pnpm/pnpm")"
[ -x "$pnpm" ] || die "pnpm is not on PATH; install it (https://pnpm.io/installation) and try again"

(cd desktop && "$pnpm" install --frozen-lockfile --silent)
tauri() { (cd desktop && "$pnpm" exec tauri "$@"); }

if [ ! -f "$key" ]; then
    echo "build-desktop: making the update signing key at $key (once)"
    mkdir -p "$key_dir"
    chmod 700 "$key_dir"
    tauri signer generate --ci --password "" --write-keys "$key" > /dev/null
fi
chmod 600 "$key" "$key.pub"

# What the app is built from: the tracked files under desktop/, as they are on disk. The
# channel is only filled when this changes, so rebuilding an unchanged app never offers an
# update, and an untracked file (a local package folder) never counts.
digest="$(
    {
        git ls-files -z -- desktop | LC_ALL=C sort -z | xargs -0 shasum -a 256
        echo "features: ${features[*]+${features[*]}}"
    } | shasum -a 256 | cut -d' ' -f1
)"
version="0.1.$(date -u +%Y%m%d%H%M%S)"
pubkey="$(cat "$key.pub")"
override="{\"version\":\"$version\"$identifier,\"bundle\":{\"createUpdaterArtifacts\":true},\"plugins\":{\"updater\":{\"pubkey\":\"$pubkey\"}}}"

echo "build-desktop: building physgate $version"
TAURI_SIGNING_PRIVATE_KEY="$key" TAURI_SIGNING_PRIVATE_KEY_PASSWORD="" \
    tauri build --ci --bundles app ${features[@]+"${features[@]}"} --config "$override" -- --locked

bundle="desktop/src-tauri/target/release/bundle/macos"
app="$bundle/physgate.app"
tarball="$bundle/physgate.app.tar.gz"
[ -d "$app" ] && [ -f "$tarball" ] && [ -f "$tarball.sig" ] || die "the build left no app, bundle or signature in $bundle"

published="$(cat "$channel/published-digest" 2> /dev/null || true)"
if [ "$digest" = "$published" ]; then
    echo "build-desktop: the app is unchanged since the last published version; nothing to publish"
else
    mkdir -p "$channel"
    name="physgate-$version.app.tar.gz"
    cp "$tarball" "$channel/$name.partial"
    mv "$channel/$name.partial" "$channel/$name"
    # The manifest goes in last and whole, so the app never reads one naming a missing bundle.
    printf '{\n  "version": "%s",\n  "pub_date": "%s",\n  "notes": "Built from desktop/ at %s.",\n  "platforms": {\n    "darwin-aarch64": {\n      "signature": "%s",\n      "url": "%s"\n    }\n  }\n}\n' \
        "$version" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(git rev-parse --short HEAD)" \
        "$(cat "$tarball.sig")" "$name" > "$channel/latest.json.partial"
    mv "$channel/latest.json.partial" "$channel/latest.json"
    echo "$digest" > "$channel/published-digest"
    find "$channel" -name 'physgate-*.app.tar.gz' -not -name "$name" -delete
    echo "build-desktop: published $version; the installed app offers it at its next start, or from physgate → Check for Shell Update…"
fi

if [ "$install" = 1 ]; then
    if pgrep -xq physgate-desktop; then
        die "the app is open; quit it (⌘Q) and run this again"
    fi
    mkdir -p "$applications"
    rm -rf "$applications/physgate.app"
    ditto "$app" "$applications/physgate.app"
    echo "build-desktop: installed $applications/physgate.app; open it from Spotlight or Finder"
fi
