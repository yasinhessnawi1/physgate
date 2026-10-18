//! The shell's state and its one routine: (re)start the server and show what it serves.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::Duration;

use tauri::{AppHandle, Manager, Url, WebviewWindow};

use crate::checkout::{self, Worktree};
use crate::config::{Paths, Settings};
use crate::navigation::Gate;
use crate::runs;
use crate::server::{self, Server};
use crate::status::Status;
use crate::tour;

/// How often the watcher looks at the build stamp and the server.
const WATCH_EVERY: Duration = Duration::from_millis(750);

pub struct Shell {
    pub paths: Paths,
    /// Where the window may go; shared with the webview's navigation check.
    gate: Arc<Gate>,
    state: Mutex<State>,
    /// Held for the whole of a restart, so two never interleave.
    restarting: Mutex<()>,
    /// The app's own page last shown, without its one-use value, so a reload can show it again.
    shown: Mutex<Option<Url>>,
    /// Whether this launch has said that the UI is read-only for want of an operator's name.
    told_read_only: std::sync::atomic::AtomicBool,
    /// Where a tour's findings go, when the app was started to take one.
    tour: Option<PathBuf>,
}

struct State {
    settings: Settings,
    server: Option<Server>,
    worktrees: Vec<Worktree>,
    /// The build stamp the running server (or the last refusal) saw.
    stamp: Option<String>,
}

impl Shell {
    pub fn new(paths: Paths, tour: Option<PathBuf>) -> Self {
        let settings = Settings::load(&paths.settings()).unwrap_or_default();
        let worktrees = checkout::worktrees(&settings.checkout);
        Self {
            paths,
            gate: Arc::new(Gate::default()),
            state: Mutex::new(State {
                settings,
                server: None,
                worktrees,
                stamp: None,
            }),
            restarting: Mutex::new(()),
            shown: Mutex::new(None),
            told_read_only: std::sync::atomic::AtomicBool::new(false),
            tour,
        }
    }

    fn state(&self) -> MutexGuard<'_, State> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub fn gate(&self) -> Arc<Gate> {
        Arc::clone(&self.gate)
    }

    /// Show the app's own page in this state: the only way the window reaches that page.
    pub fn show(&self, window: &WebviewWindow, status: &Status) {
        self.go(window, &status.url());
    }

    /// Send the window to one of the app's own pages, with the ticket that lets it in.
    pub fn go(&self, window: &WebviewWindow, url: &Url) {
        *self
            .shown
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(url.clone());
        let ticketed = self.gate.issue(url);
        let _ = window.navigate(ticketed);
    }

    /// Once a launch, when the UI opens read-only for want of a name, say so and how to set one.
    fn say_read_only(&self, app: &AppHandle) {
        if self
            .told_read_only
            .swap(true, std::sync::atomic::Ordering::SeqCst)
        {
            return;
        }
        self.note("no operator name is set: the UI is read-only; said how to set one");
        let app = app.clone();
        thread::spawn(move || {
            use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
            let set = app
                .dialog()
                .message(READ_ONLY_NOTICE)
                .title("The operator UI is read-only")
                .kind(MessageDialogKind::Info)
                .buttons(MessageDialogButtons::OkCancelCustom(
                    "Set a Name…".into(),
                    "Stay Read-Only".into(),
                ))
                .blocking_show();
            if set {
                app.state::<Shell>().onboard(&app, "operator");
            }
        });
    }

    /// Reload what the window shows: the server's page as it is, or the app's own page again
    /// through a fresh ticket (its old one is used up, so a plain reload would be refused).
    pub fn reload(&self, app: &AppHandle, window: &WebviewWindow) {
        let Ok(current) = window.url() else {
            return;
        };
        let shown = self
            .shown
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone();
        let operator = self
            .state()
            .server
            .as_ref()
            .is_some_and(|server| server.operator().is_some());
        match reload_target(&current, shown.as_ref(), operator) {
            Reload::ShowAgain(page) => self.go(window, &page),
            Reload::Page => {
                let _ = window.eval("window.location.reload()");
            }
            Reload::Restart => {
                // The page keeps the action token in memory only, and opening the operator's
                // address again from the page would only change its fragment: no load, and the
                // token back in the address. A restart is a real load, from the app's own
                // page, with a new server's token, taken once and cleared by the page.
                let app = app.clone();
                thread::spawn(move || app.state::<Shell>().restart(&app));
            }
            Reload::Nothing => {}
        }
    }

    /// Show the onboarding page at a step (`intro` or `engine`), with the server stopped.
    pub fn onboard(&self, app: &AppHandle, step: &str) {
        if let Some(window) = app.get_webview_window("main") {
            self.stop_server();
            self.go(&window, &crate::onboarding::page(step));
        }
    }

    pub fn tour(&self) -> Option<&PathBuf> {
        self.tour.as_ref()
    }

    pub fn settings(&self) -> Settings {
        self.state().settings.clone()
    }

    pub fn worktrees(&self) -> Vec<Worktree> {
        self.state().worktrees.clone()
    }

    /// Change the settings, save them, and list the worktrees again.
    pub fn change_settings(&self, change: impl FnOnce(&mut Settings)) -> Result<(), String> {
        let mut state = self.state();
        let mut settings = state.settings.clone();
        change(&mut settings);
        settings
            .save(&self.paths.settings())
            .map_err(|e| format!("the settings could not be saved: {e}"))?;
        state.worktrees = checkout::worktrees(&settings.checkout);
        state.settings = settings;
        Ok(())
    }

    /// Make sure the settings file exists, so it can be opened for editing.
    pub fn settings_file(&self) -> PathBuf {
        let path = self.paths.settings();
        if !path.exists() {
            let _ = self.state().settings.save(&path);
        }
        path
    }

    /// Append a line to the shell's log.
    pub fn note(&self, line: &str) {
        crate::config::note(&self.paths, line);
    }

    pub fn stop_server(&self) {
        self.gate.serve(None);
        let server = self.state().server.take();
        drop(server);
    }

    /// Keep the view the window shows, so a relaunch after an update opens on it again.
    pub fn remember_view(&self, app: &AppHandle) {
        if let Some(window) = app.get_webview_window("main") {
            if let Some(fragment) = rememberable(self.server_fragment(&window)) {
                let _ = fs::write(self.paths.root().join("view.txt"), fragment);
            }
        }
    }

    fn take_remembered_view(&self) -> Option<String> {
        let path = self.paths.root().join("view.txt");
        let view = fs::read_to_string(&path).ok();
        let _ = fs::remove_file(path);
        view
    }

    /// The fragment of the operator UI's page the window shows now, if it shows one.
    fn server_fragment(&self, window: &WebviewWindow) -> Option<String> {
        let url = window.url().ok()?;
        let origin = self.gate.origin()?;
        (url.origin().ascii_serialization() == origin)
            .then(|| url.fragment().map(ToString::to_string))
            .flatten()
    }

    /// Stop any server, read the settings again, start a server and show it, or show why not.
    ///
    /// Blocks while the server starts, so it runs on a thread of its own, never the main one.
    pub fn restart(&self, app: &AppHandle) {
        let _one_at_a_time = self
            .restarting
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Some(window) = app.get_webview_window("main") else {
            return;
        };
        let view = self
            .server_fragment(&window)
            .or_else(|| self.take_remembered_view());
        self.stop_server();

        let mut settings = match Settings::load(&self.paths.settings()) {
            Ok(settings) => settings,
            Err(problem) => {
                self.show(
                    &window,
                    &Status::from_start_error(
                        &server::StartError::Failed(problem),
                        &self.settings().checkout,
                    ),
                );
                return;
            }
        };
        // With no run folder set, the default root is served: no folder is ever picked.
        let root = runs::default_root(&self.paths);
        if runs::with_default(&mut settings, &root) {
            if let Err(problem) = settings.save(&self.paths.settings()) {
                self.note(&format!("the settings could not be saved: {problem}"));
            }
        }
        {
            let mut state = self.state();
            state.worktrees = checkout::worktrees(&settings.checkout);
            state.settings = settings.clone();
            state.stamp = checkout::build_stamp(&settings.checkout);
        }
        crate::menu::refresh(app);

        match opening(&settings, &root, |line| self.note(line)) {
            Opening::Onboarding(step) => {
                self.go(&window, &crate::onboarding::page(step));
                return;
            }
            Opening::Page(status) => {
                self.show(&window, &status);
                return;
            }
            Opening::Serve => {}
        }
        self.show(&window, &Status::starting(&settings.checkout));
        self.note(&format!(
            "starting the server from {}",
            settings.checkout.display()
        ));
        self.serve(app, &window, &settings, view.as_deref());
    }

    /// Start the server for `settings` and show its page: the operator's address, exactly as
    /// announced, or the page at the view the window had; or say why it could not start.
    fn serve(
        &self,
        app: &AppHandle,
        window: &WebviewWindow,
        settings: &Settings,
        view: Option<&str>,
    ) {
        match Server::start(settings, &self.paths.server_log(), &self.paths.server_pid()) {
            Ok(server) => {
                // An operator's page is opened at exactly the address the server announced,
                // which carries the action token; any other page at its address and the view.
                let target: Url = if let Some(operator) = server.operator() {
                    operator.url().clone()
                } else {
                    let mut plain = server.url().clone();
                    plain.set_fragment(view);
                    plain
                };
                // The origin trusted is the one this child announced and that passed the
                // loopback check; nothing a page does can change it.
                self.gate.serve(Some(server.url()));
                self.note(&format!("serving {}", server.url()));
                self.state().server = Some(server);
                let read_only = self
                    .state()
                    .server
                    .as_ref()
                    .is_some_and(|s| s.operator().is_none());
                let _ = window.navigate(target);
                if read_only {
                    self.say_read_only(app);
                }
                if let Some(out) = &self.tour {
                    tour::take(window.clone(), out.clone(), self.paths.server_log());
                }
            }
            Err(error) => {
                self.note(&format!("the server did not start: {error:?}"));
                self.show(
                    window,
                    &Status::from_start_error(&error, &settings.checkout),
                );
            }
        }
    }

    /// Watch, for as long as the app runs, for a finished UI build (restart and reload) and for
    /// a server that stopped by itself (say so).
    pub fn watch(app: AppHandle) {
        thread::spawn(move || loop {
            thread::sleep(WATCH_EVERY);
            let shell = app.state::<Shell>();
            let (rebuilt, stopped) = {
                let mut state = shell.state();
                let now = checkout::build_stamp(&state.settings.checkout);
                let rebuilt = (now.is_some() && now != state.stamp)
                    .then_some("the UI was rebuilt; restarting the server");
                let gone = state
                    .server
                    .as_mut()
                    .is_some_and(|server| !server.running());
                let stopped = if gone { state.server.take() } else { None };
                (rebuilt, stopped)
            };
            if let Some(why) = rebuilt {
                shell.note(why);
                shell.restart(&app);
            } else if let Some(server) = stopped {
                drop(server);
                shell.gate.serve(None);
                let log = fs::read_to_string(shell.paths.server_log()).unwrap_or_default();
                if let Some(window) = app.get_webview_window("main") {
                    shell.show(
                        &window,
                        &Status::from_start_error(
                            &server::StartError::Refused(
                                server::refusal_in(&log),
                                server::tail(&log, 20),
                            ),
                            &shell.settings().checkout,
                        ),
                    );
                }
            }
        });
    }
}

/// What a start shows first.
#[derive(Debug, PartialEq, Eq)]
pub enum Opening {
    /// The onboarding page, at this step.
    Onboarding(&'static str),
    /// The app's own page: the operator UI cannot be shown, and this says why.
    Page(Status),
    /// Start the server and show the operator UI. With no runs yet, it says so itself.
    Serve,
}

/// What a start with `settings` shows first, making the default run root `root` if it is
/// served and missing. Whether any run exists yet plays no part: an empty run folder is
/// served like any other, and the operator UI shows its own empty state.
pub fn opening(settings: &Settings, root: &Path, mut note: impl FnMut(&str)) -> Opening {
    if !settings.onboarded {
        return Opening::Onboarding(if settings.intro_seen {
            "engine"
        } else {
            "intro"
        });
    }
    if operator_mode(settings) == OperatorMode::Ask {
        return Opening::Onboarding("operator");
    }
    if !checkout::is_checkout(&settings.checkout) {
        return Opening::Page(Status::no_checkout(&settings.checkout));
    }
    if settings.run_folders.iter().any(|folder| folder == root) {
        match runs::ensure(root) {
            Ok(runs::Root::Created) => note(&format!("made {}", runs::shown(root))),
            Ok(runs::Root::Existing) => {}
            Err(reason) => {
                note(&format!("the run folder was refused: {reason}"));
                return Opening::Page(Status::root_refused(&reason));
            }
        }
    }
    Opening::Serve
}

/// The view worth keeping across a relaunch: the window's fragment, unless it carries an
/// action token, which is never written to a file.
pub fn rememberable(fragment: Option<String>) -> Option<String> {
    fragment.filter(|f| !f.contains("act="))
}

/// What the app says when the UI opens read-only, and how to change that.
pub const READ_ONLY_NOTICE: &str = "No operator name is set, so the app can read everything \
    but approve or reject nothing. To decide from the app, choose physgate → Operator Name… \
    and give the name decisions are recorded under.";

/// How the operator UI is opened, from the settings.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OperatorMode {
    /// Not asked yet: ask for the name, once.
    Ask,
    /// Asked, and no name given: the UI reads everything and acts on nothing.
    ReadOnly,
    /// Decisions are recorded under this name.
    Decide(String),
}

pub fn operator_mode(settings: &Settings) -> OperatorMode {
    match (&settings.operator, settings.operator_asked) {
        (Some(name), _) => OperatorMode::Decide(name.clone()),
        (None, false) => OperatorMode::Ask,
        (None, true) => OperatorMode::ReadOnly,
    }
}

/// What a reload does.
#[derive(Debug, PartialEq, Eq)]
pub enum Reload {
    /// Show the app's own page again, through a fresh ticket.
    ShowAgain(Url),
    /// Reload the server's page in place (a read-only page holds no token to lose).
    Page,
    /// Start the server again and load the operator's new address from the app's own page.
    Restart,
    /// Nothing to reload.
    Nothing,
}

/// What reloading `current` means, given the app's own page last shown and whether the server's
/// page is an operator's.
pub fn reload_target(current: &Url, shown: Option<&Url>, operator: bool) -> Reload {
    if current.scheme() == "tauri" {
        return shown.map_or(Reload::Nothing, |page| Reload::ShowAgain(page.clone()));
    }
    if operator {
        Reload::Restart
    } else {
        Reload::Page
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::navigation::Decision;
    use crate::testdir::TestDir;

    #[test]
    fn a_reload_shows_the_apps_own_page_again_through_a_fresh_ticket() {
        let page = Url::parse("tauri://localhost/index.html#%7B%7D").unwrap();
        let mut current = page.clone();
        current.set_query(Some("t=used-up"));
        assert_eq!(
            reload_target(&current, Some(&page), false),
            Reload::ShowAgain(page.clone())
        );
        assert_eq!(reload_target(&current, None, false), Reload::Nothing);
        let served = Url::parse("http://127.0.0.1:52011/#/runs").unwrap();
        assert_eq!(reload_target(&served, Some(&page), false), Reload::Page);
        // Shown again, the page gets a ticket of its own, not the used-up one.
        let gate = crate::navigation::Gate::default();
        let first = gate.issue(&page);
        assert_eq!(gate.decide(&first), Decision::OwnPage);
        let again = gate.issue(&page);
        assert_ne!(again, first);
        assert_eq!(gate.decide(&again), Decision::OwnPage);
    }

    #[test]
    fn the_name_is_asked_once_then_decides_or_leaves_the_ui_read_only() {
        let mut settings = Settings::default();
        assert_eq!(operator_mode(&settings), OperatorMode::Ask);
        settings.operator_asked = true;
        assert_eq!(operator_mode(&settings), OperatorMode::ReadOnly);
        settings.operator = Some("Ada Lovelace".into());
        assert_eq!(
            operator_mode(&settings),
            OperatorMode::Decide("Ada Lovelace".into())
        );
        // Read-only says how to set a name.
        assert!(READ_ONLY_NOTICE.contains("physgate → Operator Name…"));
        // A read-only start asks the server for no operator; a named one does.
        settings.operator = None;
        assert!(!crate::server::arguments(&settings)
            .iter()
            .any(|a| a.starts_with("--operator")));
        settings.operator = Some("Ada Lovelace".into());
        assert!(
            crate::server::arguments(&settings).contains(&"--operator=Ada Lovelace".to_string())
        );
        // One argument, so a name that starts with `-` is still taken as the name.
        settings.operator = Some("-x".into());
        assert!(crate::server::arguments(&settings).contains(&"--operator=-x".to_string()));
    }

    #[test]
    fn an_operators_reload_is_a_real_load_that_leaves_no_token_in_the_address() {
        // The operator's page, after the page took its token and cleared the address.
        let served = Url::parse("http://127.0.0.1:52011/#/collaboration/approval-queue").unwrap();
        // Not a navigation to the operator's address, which would be a fragment change on the
        // same document: a restart, which loads the new address from the app's own page.
        assert_eq!(reload_target(&served, None, true), Reload::Restart);
        // The restart goes through the app's own page (another origin) to the new address, so
        // the load is a new document, which takes the token and clears it from the address.
        let own = Url::parse("tauri://localhost/index.html#starting").unwrap();
        let next = Url::parse("http://127.0.0.1:52012/#act=fresh").unwrap();
        assert_ne!(own.origin(), next.origin(), "a cross-document load");
        // A read-only page holds no token: it reloads in place.
        assert_eq!(reload_target(&served, None, false), Reload::Page);
    }

    #[test]
    fn a_view_holding_an_action_token_is_never_remembered() {
        assert_eq!(
            rememberable(Some("/collaboration/approval-queue?run=0%2Frun".into())),
            Some("/collaboration/approval-queue?run=0%2Frun".into())
        );
        assert_eq!(rememberable(Some(format!("act={}", "made-up-token"))), None);
        assert_eq!(
            rememberable(Some(format!("/x?act={}", "made-up-token"))),
            None
        );
        assert_eq!(rememberable(None), None);
    }

    /// A checkout whose entry point records its arguments, announces an address and runs on.
    fn stand_in_checkout(dir: &Path) -> PathBuf {
        use std::os::unix::fs::PermissionsExt;
        let checkout = dir.join("checkout");
        let bin = checkout.join(".venv/bin");
        fs::create_dir_all(&bin).unwrap();
        fs::create_dir_all(checkout.join("ui")).unwrap();
        fs::write(checkout.join("pyproject.toml"), "").unwrap();
        let program = bin.join("physgate");
        fs::write(
            &program,
            format!(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" > '{}'\n\
                 printf '{{\"url\": \"http://127.0.0.1:5555/\"}}\\n'\nwhile :; do sleep 1; done\n",
                dir.join("args.txt").display()
            ),
        )
        .unwrap();
        fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).unwrap();
        checkout
    }

    #[test]
    fn a_start_with_an_empty_run_root_serves_the_operator_ui() {
        let dir = TestDir::new("empty-start");
        let root = dir.path().join("physgate-runs");
        let mut settings = Settings {
            checkout: stand_in_checkout(dir.path()),
            onboarded: true,
            intro_seen: true,
            operator_asked: true,
            ..Settings::default()
        };
        assert!(runs::with_default(&mut settings, &root));
        let mut notes = Vec::new();

        // The first start: the root is made, holds nothing, and the server is started.
        assert_eq!(
            opening(&settings, &root, |l| notes.push(l.to_string())),
            Opening::Serve
        );
        assert!(root.is_dir());
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0, "no run in it");
        assert_eq!(notes, [format!("made {}", runs::shown(&root))]);

        // Later starts over a root still empty (a hidden file is no run) serve it too.
        fs::write(root.join(".DS_Store"), "").unwrap();
        assert_eq!(opening(&settings, &root, |_| {}), Opening::Serve);
        // So does a run folder of the operator's own choosing that holds nothing.
        let chosen = dir.path().join("chosen");
        fs::create_dir(&chosen).unwrap();
        let elsewhere = Settings {
            run_folders: vec![chosen.clone()],
            ..settings.clone()
        };
        assert_eq!(opening(&elsewhere, &root, |_| {}), Opening::Serve);

        // And the server it starts is given the empty root.
        let server = Server::start(
            &settings,
            &dir.path().join("server.log"),
            &dir.path().join("server.pid"),
        )
        .unwrap();
        assert_eq!(server.url().as_str(), "http://127.0.0.1:5555/");
        let args = fs::read_to_string(dir.path().join("args.txt")).unwrap();
        let args: Vec<&str> = args.lines().collect();
        let at = args.iter().position(|a| *a == "--root").unwrap();
        assert_eq!(args[at + 1], root.display().to_string());
        drop(server);
    }

    #[test]
    fn the_app_shows_its_own_page_only_when_the_ui_cannot_be_shown() {
        let dir = TestDir::new("own-page");
        let root = dir.path().join("physgate-runs");
        let ready = Settings {
            checkout: stand_in_checkout(dir.path()),
            run_folders: vec![root.clone()],
            onboarded: true,
            intro_seen: true,
            operator_asked: true,
            ..Settings::default()
        };
        // Onboarding and the name come first, as before.
        let fresh = Settings {
            onboarded: false,
            intro_seen: false,
            ..ready.clone()
        };
        assert_eq!(opening(&fresh, &root, |_| {}), Opening::Onboarding("intro"));
        let unnamed = Settings {
            operator_asked: false,
            ..ready.clone()
        };
        assert_eq!(
            opening(&unnamed, &root, |_| {}),
            Opening::Onboarding("operator")
        );
        // No checkout: the app's page, which says where to choose one.
        let lost = Settings {
            checkout: dir.path().join("nowhere"),
            ..ready.clone()
        };
        let Opening::Page(page) = opening(&lost, &root, |_| {}) else {
            panic!("no checkout is the app's own page");
        };
        assert_eq!(page.title, "No physgate checkout here");
        assert!(page
            .lines
            .iter()
            .any(|l| l.contains("Choose Another Checkout")));
        // A root that is not a folder: the app's page.
        fs::write(&root, "a file").unwrap();
        let Opening::Page(page) = opening(&ready, &root, |_| {}) else {
            panic!("a refused root is the app's own page");
        };
        assert_eq!(page.title, "The run folder can't be used");
    }

    #[test]
    fn stopping_the_server_stops_trusting_its_origin() {
        let dir = TestDir::new("stop-trust");
        let shell = Shell::new(Paths::at(dir.path().to_path_buf()), None);
        let page = Url::parse("http://127.0.0.1:52011/#/runs").unwrap();
        shell.gate().serve(Some(&page));
        assert_eq!(shell.gate().decide(&page), Decision::Served);
        shell.stop_server();
        assert_eq!(shell.gate().decide(&page), Decision::Refused);
    }
}
