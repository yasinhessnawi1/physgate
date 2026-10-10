//! The shell's state and its one routine: (re)start the server and show what it serves.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use tauri::{AppHandle, Manager, Url, WebviewWindow};

use crate::checkout::{self, Worktree};
use crate::config::{Paths, Settings};
use crate::server::{self, Server};
use crate::status::Status;
use crate::tour;

/// How often the watcher looks at the build stamp and the server.
const WATCH_EVERY: Duration = Duration::from_millis(750);

/// The origin the window may show besides the shell's own page, shared with the navigation check.
pub type Origin = Arc<Mutex<Option<String>>>;

pub struct Shell {
    pub paths: Paths,
    origin: Origin,
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
            origin: Arc::new(Mutex::new(None)),
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

    pub fn origin(&self) -> Origin {
        Arc::clone(&self.origin)
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
        let _ = fs::create_dir_all(self.paths.root());
        if let Ok(mut log) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.paths.shell_log())
        {
            let at = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_or(0, |d| d.as_secs());
            let _ = writeln!(log, "{at} {line}");
        }
    }

    pub fn stop_server(&self) {
        *self
            .origin
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = None;
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
        let origin = self.origin.lock().ok()?.clone()?;
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
                show(
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

        if !checkout::is_checkout(&settings.checkout) {
            show(&window, &Status::no_checkout(&settings.checkout));
            return;
        }
        if settings.run_folders.is_empty() {
            show(&window, &Status::no_run_folders());
            return;
        }
        show(&window, &Status::starting(&settings.checkout));
        self.note(&format!(
            "starting the server from {}",
            settings.checkout.display()
        ));
        match Server::start(&settings, &self.paths.server_log()) {
            Ok(server) => {
                let mut target: Url = server.url().clone();
                target.set_fragment(view.as_deref());
                *self
                    .origin
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner) =
                    Some(server.url().origin().ascii_serialization());
                self.note(&format!("serving {}", server.url()));
                self.state().server = Some(server);
                let _ = window.navigate(target);
                if let Some(out) = &self.tour {
                    tour::take(window.clone(), out.clone(), self.paths.server_log());
                }
            }
            Err(error) => {
                self.note(&format!("the server did not start: {error:?}"));
                show(
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
                *shell
                    .origin
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner) = None;
                let log = fs::read_to_string(shell.paths.server_log()).unwrap_or_default();
                if let Some(window) = app.get_webview_window("main") {
                    show(
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

/// Show the shell's own page in this state.
pub fn show(window: &WebviewWindow, status: &Status) {
    let _ = window.navigate(status.url());
}

/// Whether the window may go to `url`: the shell's own page, or the running server's origin.
/// Everything else (a link to another site, another port) is refused, and the window stays.
pub fn may_navigate(url: &Url, origin: Option<&str>) -> bool {
    let own_page = url.scheme() == "tauri" && url.host_str() == Some("localhost");
    let served = origin.is_some_and(|origin| url.origin().ascii_serialization() == origin);
    own_page || served
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_window_goes_only_to_its_own_page_or_the_running_server() {
        let origin = Some("http://127.0.0.1:52011");
        let allowed = [
            "tauri://localhost/index.html#x",
            "http://127.0.0.1:52011/",
            "http://127.0.0.1:52011/#/runs/run-on",
        ];
        for url in allowed {
            assert!(may_navigate(&Url::parse(url).unwrap(), origin), "{url}");
        }
        let refused = [
            "http://127.0.0.1:8765/",
            "http://localhost:52011/",
            "https://127.0.0.1:52011/",
            "https://example.com/",
            "file:///etc/passwd",
            "tauri://elsewhere/index.html",
            "about:blank",
        ];
        for url in refused {
            assert!(!may_navigate(&Url::parse(url).unwrap(), origin), "{url}");
        }
        assert!(!may_navigate(
            &Url::parse("http://127.0.0.1:52011/").unwrap(),
            None
        ));
    }
}
