//! The shell's state and its one routine: (re)start the server and show what it serves.

use std::fs;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::Duration;

use tauri::{AppHandle, Manager, Url, WebviewWindow};

use crate::checkout::{self, Worktree};
use crate::config::{Paths, Settings};
use crate::navigation::Gate;
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
        self.go(window, status.url());
    }

    /// Send the window to one of the app's own pages, with the ticket that lets it in.
    pub fn go(&self, window: &WebviewWindow, url: Url) {
        self.gate.issue(&url);
        let _ = window.navigate(url);
    }

    /// Show the onboarding page at a step (`intro` or `engine`), with the server stopped.
    pub fn onboard(&self, app: &AppHandle, step: &str) {
        if let Some(window) = app.get_webview_window("main") {
            self.stop_server();
            self.go(&window, crate::onboarding::page(step));
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
            if let Some(fragment) = self.server_fragment(&window) {
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

        let settings = match Settings::load(&self.paths.settings()) {
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
        {
            let mut state = self.state();
            state.worktrees = checkout::worktrees(&settings.checkout);
            state.settings = settings.clone();
            state.stamp = checkout::build_stamp(&settings.checkout);
        }
        crate::menu::refresh(app);

        if !settings.onboarded {
            let step = if settings.intro_seen {
                "engine"
            } else {
                "intro"
            };
            self.go(&window, crate::onboarding::page(step));
            return;
        }
        if !checkout::is_checkout(&settings.checkout) {
            self.show(&window, &Status::no_checkout(&settings.checkout));
            return;
        }
        if settings.run_folders.is_empty() {
            self.show(&window, &Status::no_run_folders());
            return;
        }
        self.show(&window, &Status::starting(&settings.checkout));
        self.note(&format!(
            "starting the server from {}",
            settings.checkout.display()
        ));
        match Server::start(&settings, &self.paths.server_log()) {
            Ok(server) => {
                let mut target: Url = server.url().clone();
                target.set_fragment(view.as_deref());
                // The origin trusted is the one this child announced and that passed the
                // loopback check; nothing a page does can change it.
                self.gate.serve(Some(server.url()));
                self.note(&format!("serving {}", server.url()));
                self.state().server = Some(server);
                let _ = window.navigate(target);
                if let Some(out) = &self.tour {
                    tour::take(window.clone(), out.clone(), self.paths.server_log());
                }
            }
            Err(error) => {
                self.note(&format!("the server did not start: {error:?}"));
                self.show(
                    &window,
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
                let rebuilt = now.is_some() && now != state.stamp;
                let gone = state
                    .server
                    .as_mut()
                    .is_some_and(|server| !server.running());
                let stopped = if gone { state.server.take() } else { None };
                (rebuilt, stopped)
            };
            if rebuilt {
                shell.note("the UI was rebuilt; restarting the server");
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
