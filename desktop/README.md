# physgate desktop app

A Mac app that shows the operator UI in its own window. It is a thin shell. It starts
`physgate ui` from a checkout on this machine, on loopback, and shows the page that server
serves. It is never a second copy of the UI.

- **A UI change needs no new app.** Rebuild the UI with `scripts/build-ui.sh` in the
  checkout the app points at. The app sees the finished build, restarts its server and
  reloads by itself, and the view stays where it was.
- **A change to the app itself** (anything under `desktop/`) reaches the installed app
  through its own updater. It offers the new version at its next start, or from
  **physgate → Check for Shell Update…**. One click installs it and reopens the app.

## Install (once)

You need Rust (`brew install rust`), Node 22 and pnpm. In a Terminal, from the repository:

```sh
scripts/build-desktop.sh --install
```

That builds the app, takes about three minutes the first time, and puts it in
`~/Applications/physgate.app`. Open it from Spotlight or Finder. It isn't downloaded from
the internet, so macOS opens it without a warning.

On the first start the app asks for nothing. It shows how to add a run folder:
**Run Folders → Add Run Folder…** in the menu bar. Pick a run, or a folder of runs, and
it is remembered.

## Update

- **After a UI change:** nothing to do in the app. Whoever changed the UI runs
  `scripts/build-ui.sh` in the checkout, and the open app reloads.
- **After a change to the app:** run `scripts/build-desktop.sh`. Without `--install`, it
  builds the app and publishes it to the update channel. The installed app offers it, and
  you click **Install and Restart**. If the app itself did not change, nothing is
  published and the app offers nothing.

## The menu

| Menu | What it does |
|---|---|
| physgate → Check for Shell Update… | Looks for a newer app in the local update channel |
| physgate → Open Settings File | The remembered checkout, run folders and held-out paths, as JSON |
| View → Reload (⌘R) | Reloads the page |
| View → Restart Server (⇧⌘R) | Reads the settings again, restarts `physgate ui` and shows it |
| View → Show Server Log | What `physgate ui` wrote on its latest start: its request log, or why it refused |
| Checkout | Every worktree of the repository, to try a UI branch before it merges; or another folder |
| Run Folders | The folders served, and adding or removing one |

When the server can't start, the window says why, in the server's own words. If the UI
build is missing or out of date, the window shows the command that builds it. You run it
in Terminal; the app never runs it.

## What stays on this machine, and what stays local

| Where | What |
|---|---|
| `~/Library/Application Support/physgate-desktop/settings.json` | The settings |
| `~/Library/Application Support/physgate-desktop/server.log`, `shell.log` | The server's log, and the app's own notes (starts, update checks) |
| `~/Library/Application Support/physgate-desktop/updates/` | The update channel: `latest.json` and the signed bundle it names |
| `~/.config/physgate-desktop/updater.key` | The update signing key, mode 0600, made by the first build. Never in the repository |

- **Loopback only.** The app runs the checkout's own `.venv/bin/physgate ui --bind
  127.0.0.1 --port 0`. It runs the entry point directly, not `uv run`, so starting never
  syncs packages or touches the network. The port is free and chosen by the system, so it
  never collides with a server started by hand.
- **The server's checks are unchanged.** The window loads the server's address as an
  ordinary page, so its `Host` and `Origin` are the server's own and pass its checks as
  they are. Its Content-Security-Policy is untouched.
- **The page gets nothing from the app.** No capability is granted to any remote address,
  so every call into the app from the served page is refused. Every control is in the
  native menu bar.
- **The window goes only where the app sends it.** Every navigation the webview starts is
  decided first:
  - **The server's origin:** scheme, host and port, compared whole. This is the origin the
    app's own child announced, after the loopback check. A page cannot choose it.
  - **The app's own status page:** only at the exact address the app itself just sent the
    window to, with a one-use ticket. So a served page cannot show its own text in that
    page.

  Everything else is refused and logged in `shell.log`, and the window stays put: links,
  scripts and redirects alike, `data:` and `file:` addresses, another port, and `localhost`
  by name. New windows (`window.open`, `target=_blank`) are refused too.
- **Held-out paths and answer keys** in the settings are passed to the server as
  `--held-out` and `--answer-key`. The app never opens them. The server's own refusals
  (the checkout's `corpora`, credentials) stand whatever the settings say.
- **The update channel never leaves the machine.** The updater only fetches over HTTP. So
  for the length of one check, the app serves its own `updates/` folder on `127.0.0.1` and
  a free port. It answers two requests, the manifest and the bundle the manifest names,
  then closes.

### Why `dangerousInsecureTransportProtocol` is set

The updater refuses a plain `http` address in a release build unless this flag is set, and
it makes no exception for loopback. The flag is set because both of the following hold:

- **The channel is loopback only.** The only address the updater is ever given is the app's
  own listener on `127.0.0.1`, which serves a folder on this machine. No request leaves the
  machine, so there is no network path for anyone to tamper with.
- **Every update is signature-checked.** The updater verifies each bundle against the
  public key built into the installed app before replacing anything, and that check can't
  be switched off. Only a bundle signed with the key in `~/.config/physgate-desktop/` is
  installed. A bundle that was changed, or signed with any other key, is refused.

The flag concerns only how the app fetches its own update. The operator server's rules
(loopback, `Host`/`Origin`, the allowlist) are not touched by it.

## For whoever works on the app

- **Gates:** `scripts/check-desktop.sh` runs formatting, clippy (pedantic, warnings as
  errors) and the unit tests. It isn't part of `scripts/check.sh` or CI. Run it before
  building.
- **Trying it without touching the real install:** set `PHYSGATE_DESKTOP_HOME` (settings,
  logs, channel) and `PHYSGATE_DESKTOP_APPLICATIONS` (where `--install` puts the app). Both
  the app and the build script read them.
- **A click-through inside the app's own webview:**
  ```sh
  open -n --env PHYSGATE_DESKTOP_TOUR=/tmp/tour.json ~/Applications/physgate.app
  ```
  This clicks every in-app link and the buttons on each view. It writes to the named file:
  - Content-Security-Policy violations, counted from the first byte of each page load;
  - any request to another origin;
  - the server's responses by status, every 403 listed.
- **A scripted update check:** `PHYSGATE_DESKTOP_ACCEPT_UPDATE=1` answers the install
  question without the dialog. The bundle is still verified against the built-in key.
- **The key is lost?** Delete `~/.config/physgate-desktop/updater.key*` and the `updates/`
  folder, then run `scripts/build-desktop.sh --install` once. The new key is built into the
  new app.
