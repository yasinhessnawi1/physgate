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

## The first start: welcome, engine, then the operator UI

1. **Welcome.** A seven-second intro plays once. **Skip**, Esc or Return passes it, and
   **physgate → Replay Intro** shows it again. With reduced motion turned on in System
   Settings, it shows as a still.
2. **Engine.** You choose how physgate's roles reach a model. Two choices work today:
   - **Claude Code**, signed in with your Claude subscription.
     - **If Claude Code is missing,** the app shows Anthropic's official installer
       (`curl -fsSL https://claude.ai/install.sh | bash`) and opens Terminal with it when you
       click. The app downloads nothing itself. Then **Check Again**.
     - **Sign In** runs `claude setup-token` inside the app and opens your browser. The
       token it prints goes straight into the macOS Keychain and is never shown. If that
       doesn't work, **Sign in in Terminal instead** runs it in Terminal, and you paste the
       token into a masked field.
   - **The Claude API**, with an API key.
     - Paste the key into the masked field. It goes into the Keychain, and nothing is sent
       anywhere.
     - **Test Key — contacts Anthropic** makes one request, only when you click it, and says
       whether Anthropic accepts the key.
     - Choose an implementing and a reviewing model. They must differ.

   Other providers, and a model run on this Mac, are listed as **not available yet**. The
   local-model card shows what this Mac could run (chip, memory, GPU cores, free disk, and
   which models would fit), but nothing is downloaded. **Set Up Later** skips the step,
   and **physgate → Engine…** returns to it.
3. **The operator UI.** The app serves `~/physgate-runs` without asking. It makes the
   folder on the first start (readable by you only), uses it as it is afterwards, and
   refuses it if it is a link. Runs appear as soon as one is made there. Until then the
   window says so and shows the two steps that make one:

   ```sh
   physgate decompose <brief> --seed <seed> --run-id <id> --params <params.json> --target <repository> --run-dir ~/physgate-runs/<id>
   physgate run --run-dir ~/physgate-runs/<id> --target <repository> --install <hooks folder> --review-root ~/review-scratch
   ```

**Runs still use Claude Code today.** What the engine step stores (the engine, and for the
API the two models) is a record for later. A run still uses the credential and models its
own parameters name, and runs on an API key still ask the owner before they spend.

### Where credentials live

- **Only in the macOS Keychain.** The service is `physgate`, and the account is the
  variable a run reads (`CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`).
- **Never anywhere else:** not in the settings, a log, the repository, or the operator UI
  the server serves. The app's commands only store a credential, forget one, or say
  whether one is kept. None hands one back.
- **To start a run from Terminal,** load the credential first with the line the engine
  step shows. It holds no secret; macOS asks you once to allow it:

  ```sh
  export CLAUDE_CODE_OAUTH_TOKEN="$(security find-generic-password -s physgate -a CLAUDE_CODE_OAUTH_TOKEN -w)"
  ```

- **After a shell update, macOS may ask once to allow access to the Keychain item**, on Test
  Key or when a credential is replaced. The app is signed ad hoc, so each update is a new
  app to the Keychain. Checking whether a credential is kept reads no secret and doesn't ask.
- **Only the app's own pages can call these commands.** The capability that grants them
  names no remote address, so the served operator UI can call none of them.

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
| physgate → Engine… | The engine step again: Claude Code or the Claude API, and the credential kept for runs |
| physgate → Replay Intro | The welcome intro again |
| physgate → Open Settings File | The remembered checkout, run folders and held-out paths, as JSON |
| View → Reload (⌘R) | Reloads the page |
| View → Restart Server (⇧⌘R) | Reads the settings again, restarts `physgate ui` and shows it |
| View → Show Server Log | What `physgate ui` wrote on its latest start: its request log, or why it refused |
| Checkout | Every worktree of the repository, to try a UI branch before it merges; or another folder |
| Run Folders | The folders served (`~/physgate-runs` unless you set others), and adding or removing one |

When the server can't start, the window says why, in the server's own words. If the UI
build is missing or out of date, the window shows the command that builds it. You run it
in Terminal; the app never runs it.

## What stays on this machine, and what stays local

| Where | What |
|---|---|
| `~/Library/Application Support/physgate-desktop/settings.json` | The settings |
| `~/Library/Application Support/physgate-desktop/server.log`, `shell.log` | The server's log, and the app's own notes (starts, update checks) |
| `~/Library/Application Support/physgate-desktop/updates/` | The update channel: `latest.json` and the signed bundle it names |
| The macOS Keychain, service `physgate` | The subscription token or API key for runs, and nothing else holds them |
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
  then closes. A manifest naming anything but a file in that folder is refused before the
  updater runs (see below).

### Why `dangerousInsecureTransportProtocol` is set

The updater refuses a plain `http` address in a release build unless this flag is set, and
it makes no exception for loopback. The flag is set because both of the following hold:

- **The channel is loopback only, and the manifest can't change that.**
  - The updater is given two kinds of address: the manifest's, and the bundle's that the
    manifest names. The manifest is checked before the updater starts.
  - Every platform's `url` must be a plain file name in the `updates/` folder: no scheme,
    host, path, query or `..`, not a link, and the same file for all platforms. A manifest
    naming anything else (`https://…`, `http://127.0.0.1:other-port/…`, `x?y`) is refused
    whole, and no update check runs.
  - The bundle's address is then built from that file name and the app's own listener on
    `127.0.0.1`. So both addresses are that listener, and no request leaves the machine.
- **Every update is signature-checked.** The updater verifies each bundle against the
  public key built into the installed app before replacing anything, and that check can't
  be switched off. Only a bundle signed with the key in `~/.config/physgate-desktop/` is
  installed. A bundle that was changed, or signed with any other key, is refused.

The flag concerns only how the app fetches its own update. The operator server's rules
(loopback, `Host`/`Origin`, the allowlist) are not touched by it.

## For whoever works on the app

- **One app per data folder.** A second launch brings the running window forward and
  quits. The guard's socket is in your private temporary folder, not `/tmp`. A trial build
  has its own folder, so one can run beside the installed app.
- **A trial build makes nothing in `~/Library`.** It restarts itself once at start, with its
  `~/Library` (WebKit's storage and caches) inside its trial folder, in `user-home/`. The
  Keychain is not moved by this: a trial build still uses only `physgate-trial`.

- **The intro** is a Remotion composition in `intro/`. To change it, edit `intro/src/Intro.tsx`
  and render it again:

  ```sh
  cd desktop/intro && pnpm install && pnpm run render
  ```

  This writes `status/intro.gif` (an animated image, played once) and
  `status/intro-poster.png` (its last frame), which are committed. It is an image rather
  than a film because WebKit in the app won't start a film without a click, and an image
  needs no permission. Remotion is free for individuals; check its licence before a company
  uses it. The fonts in `intro/public/fonts` are IBM Plex, under the OFL.
- **A scripted walk through the onboarding**, for screenshots, is built only as a trial
  build (`scripts/build-desktop.sh --walkthrough`), never into a published app. It refuses
  to start without a stand-in Claude Code. See `src/walkthrough.rs` for
  the variables it reads: a stand-in Claude Code, a Keychain service of its own, and a
  made-up key.

- **Gates:** `scripts/check-desktop.sh` runs formatting, clippy (pedantic, warnings as
  errors) and the unit tests. It isn't part of `scripts/check.sh` or CI. Run it before
  building.
- **Only the build script's normal build is published.** It alone sets the `published`
  feature. Any other build is a trial build: `cargo build`, `cargo run`, `tauri dev`, a
  release built by hand, `--verification`, `--walkthrough`. A trial build uses the Keychain
  service `physgate-trial`, needs a trial folder of its own, and has the identifier
  `local.physgate.desktop.trial`.
- **A trial build:** `PHYSGATE_DESKTOP_HOME=<a trial folder> scripts/build-desktop.sh
  --verification` (or `--walkthrough`, which adds the scripted onboarding walk). It honours
  the switches below and is kept apart from the real install:
  - **Its own signing key,** in `~/.config/physgate-desktop/trial/`. The installed app
    refuses its bundles, wherever they end up.
  - **Its own identifier,** `local.physgate.desktop.trial`.
  - **Its own folder.** The script refuses a missing `PHYSGATE_DESKTOP_HOME`, and one that
    is (or is inside) the installed app's folder, compared after links are resolved. It
    also refuses `--install`.
  - **The built app checks the same.** It refuses to start without a trial folder of its
    own. Its run root defaults to `physgate-runs` inside that folder, and it refuses one
    that is (or is inside) `~/physgate-runs`. So it never reads the installed app's
    settings, `server.pid` or update channel.
- **Trying it without touching the real install:** the `PHYSGATE_DESKTOP_…` switches exist
  only in a build with the `verification` feature (`walkthrough` includes it). A published
  build reads none of them. The switches are:
  - `PHYSGATE_DESKTOP_HOME`: settings, logs and the update channel;
  - `PHYSGATE_DESKTOP_RUNS_ROOT`: the default run folder;
  - `PHYSGATE_DESKTOP_CLAUDE`: a stand-in Claude Code;
  - `PHYSGATE_DESKTOP_TOUR`: the click-through below;
  - `PHYSGATE_DESKTOP_ACCEPT_UPDATE`: accept an update without its dialog. The bundle is
    still verified against the built-in key.

  `PHYSGATE_DESKTOP_APPLICATIONS` is the build script's own: where `--install` puts the app.
  A trial build always uses the Keychain service `physgate-trial`, fixed when it is
  compiled; it can't be pointed at `physgate`. Unit tests use a service of the test
  process's own. The walkthrough refuses to start without a stand-in Claude Code.
- **A click-through inside the app's own webview:**
  ```sh
  open -n --env PHYSGATE_DESKTOP_TOUR=/tmp/tour.json path/to/a-verification-build/physgate.app
  ```
  This clicks every in-app link and the buttons on each view. It writes to the named file:
  - Content-Security-Policy violations, counted from the first byte of each page load;
  - any request to another origin;
  - the server's responses by status, every 403 listed.
- **The key is lost?** Delete `~/.config/physgate-desktop/updater.key*` and the `updates/`
  folder, then run `scripts/build-desktop.sh --install` once. The new key is built into the
  new app.
