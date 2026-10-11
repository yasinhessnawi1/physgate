//! physgate's desktop shell: one window showing the operator UI that `physgate ui` serves.
//!
//! The shell is never a second copy of the UI. It starts `physgate ui` from a checkout on
//! loopback, shows the page that server serves, and restarts it when the UI is rebuilt,
//! so a UI change never needs a new app. The app's own updater, fed from a folder on this
//! machine, only carries changes to the shell itself.
//!
//! The served page gets no access to the app: no capability is granted to any remote
//! address, the window may only go to the server's own origin or the shell's bundled
//! page, and it may open no other window. Every control is in the native menu bar.

mod channel;
mod checkout;
mod config;
mod engine;
mod instance;
mod keychain;
mod menu;
mod navigation;
mod onboarding;
mod runs;
mod server;
mod shell;
mod signals;
mod status;
#[cfg(test)]
mod testdir;
mod tour;
mod update;
#[cfg(feature = "walkthrough")]
mod walkthrough;

use std::path::PathBuf;
use std::time::Duration;

use tauri::webview::NewWindowResponse;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

use crate::config::Paths;
use crate::shell::Shell;

/// The app's folders. A trial build starts only with a trial folder and run root of its own,
/// so it never reads the installed app's settings, `server.pid` or update channel, nor its run
/// folder; without them it says why and exits.
fn paths_or_exit() -> Paths {
    let checked = Paths::from_env().and_then(|paths| {
        if !config::PUBLISHED_BUILD {
            runs::check_trial_root(&runs::default_root(&paths))?;
        }
        Ok(paths)
    });
    checked.unwrap_or_else(|problem| {
        eprintln!("physgate: {problem}");
        std::process::exit(2);
    })
}

/// Where a trial build's `~/Library` should be (its web storage and caches), if this
/// process is not there yet: inside its trial folder, so a trial run makes nothing in the
/// operator's `~/Library`. `None` for the published build, or once it is so.
fn confinement(
    published: bool,
    root: &std::path::Path,
    current: Option<&std::ffi::OsStr>,
) -> Option<PathBuf> {
    if published {
        return None;
    }
    let wanted = root.join("user-home");
    (current != Some(wanted.as_os_str())).then_some(wanted)
}

/// A trial build restarts itself, once and before anything else starts, with its home for
/// `~/Library` inside its trial folder. The Keychain is not moved by this.
fn confine_trial_build(paths: &Paths) {
    use std::os::unix::process::CommandExt;
    let current = std::env::var_os("CFFIXED_USER_HOME");
    let Some(wanted) = confinement(config::PUBLISHED_BUILD, paths.root(), current.as_deref())
    else {
        return;
    };
    let _ = std::fs::create_dir_all(&wanted);
    let problem = std::env::current_exe().map(|exe| {
        std::process::Command::new(exe)
            .args(std::env::args_os().skip(1))
            .env("CFFIXED_USER_HOME", &wanted)
            .exec()
    });
    eprintln!("physgate: a trial build could not restart inside its trial folder: {problem:?}");
    std::process::exit(2);
}

/// Claim the data folder for this instance, before anything starts: if another instance has
/// it, ask that one to come forward and quit here.
fn claim_or_exit(paths: &Paths) -> (Option<std::os::unix::net::UnixListener>, Option<PathBuf>) {
    let claimed = std::fs::create_dir_all(paths.root())
        .and_then(|()| instance::socket_path(paths.root()))
        .and_then(|socket| instance::claim(&socket).map(|claim| (claim, socket)));
    match claimed {
        Ok((instance::Claim::HandedOver, _)) => std::process::exit(0),
        Ok((instance::Claim::First(listener), socket)) => (Some(listener), Some(socket)),
        Err(problem) => {
            config::note(paths, &format!("no single-instance guard: {problem}"));
            (None, None)
        }
    }
}

/// A second launch reached this one: bring the window forward.
fn hand_over(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
    app.state::<Shell>()
        .note("a second launch was handed to this one");
}

/// Catch the stopping signals; when one comes, stop the server and quit.
fn stop_on_signal(app: tauri::AppHandle) {
    signals::install();
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_millis(100));
        if signals::requested() {
            let shell = app.state::<Shell>();
            shell.note("asked to stop by a signal; stopping the server");
            shell.stop_server();
            app.exit(0);
            break;
        }
    });
}

fn main() {
    #[cfg(feature = "walkthrough")]
    if let Err(problem) = walkthrough::preflight(
        config::switch("PHYSGATE_DESKTOP_WALKTHROUGH").as_deref(),
        config::switch("PHYSGATE_DESKTOP_CLAUDE").as_deref(),
    ) {
        eprintln!("physgate: {problem}");
        std::process::exit(2);
    }
    let paths = paths_or_exit();
    confine_trial_build(&paths);
    let (listener, socket) = claim_or_exit(&paths);
    let tour = config::switch("PHYSGATE_DESKTOP_TOUR").map(PathBuf::from);
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Shell::new(paths, tour))
        .manage(engine::SignIn::default())
        .invoke_handler(tauri::generate_handler![
            onboarding::onboarding_state,
            onboarding::claude_code_detect,
            onboarding::claude_code_install,
            onboarding::sign_in_start,
            onboarding::sign_in_status,
            onboarding::sign_in_return,
            onboarding::sign_in_cancel,
            onboarding::sign_in_in_terminal,
            onboarding::store_secret,
            onboarding::forget_secret,
            onboarding::test_api_key,
            onboarding::choose_engine,
            onboarding::device_report,
            onboarding::intro_seen,
            onboarding::finish_onboarding,
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            let shell = app.state::<Shell>();
            let gate = shell.gate();
            let refusals = shell.paths.clone();
            let new_windows = shell.paths.clone();
            // The window's first load: the app's own page with no state in its address, which
            // shows only "Starting". One ticket, for exactly the address the webview reports.
            gate.first_load();
            let mut window =
                WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                    .title("physgate")
                    .inner_size(1360.0, 900.0)
                    .min_inner_size(760.0, 560.0)
                    .on_navigation(move |url| {
                        let decision = gate.decide(url);
                        if decision == navigation::Decision::Refused {
                            config::note(&refusals, &format!("navigation refused: {url}"));
                        }
                        decision != navigation::Decision::Refused
                    })
                    .on_new_window(move |url, _| {
                        config::note(&new_windows, &format!("new window refused: {url}"));
                        NewWindowResponse::Deny
                    });
            if shell.tour().is_some() {
                window = window.initialization_script(tour::WATCH_SCRIPT);
            }
            window.build()?;
            app.set_menu(menu::build(&handle)?)?;
            shell.note(&format!(
                "launched version {}",
                handle.package_info().version
            ));
            if let Some(pid) = server::reap(&shell.paths.server_pid()) {
                shell.note(&format!(
                    "stopped a server ({pid}) an earlier run left behind"
                ));
            }
            stop_on_signal(handle.clone());
            if let Some(listener) = listener {
                let forward = handle.clone();
                instance::listen(listener, move || hand_over(&forward));
            }
            menu::restart_in_background(handle.clone());
            Shell::watch(handle.clone());
            #[cfg(feature = "walkthrough")]
            walkthrough::start(handle.clone());
            let later = handle.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_secs(4));
                update::check(&later, false);
            });
            Ok(())
        })
        .on_menu_event(|app, event| menu::on_event(app, &event))
        .build(tauri::generate_context!())
        .expect("the app could not be built");
    app.run(move |app, event| {
        if let RunEvent::Exit = event {
            app.state::<Shell>().stop_server();
            if let Some(socket) = &socket {
                let _ = std::fs::remove_file(socket);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsStr;
    use std::path::Path;

    #[test]
    fn a_trial_build_keeps_its_library_inside_its_trial_folder() {
        let root = Path::new("/trial/home");
        let wanted = root.join("user-home");
        assert_eq!(
            confinement(true, root, None),
            None,
            "the published build stays put"
        );
        assert_eq!(confinement(false, root, None), Some(wanted.clone()));
        assert_eq!(
            confinement(false, root, Some(OsStr::new("/elsewhere"))),
            Some(wanted.clone())
        );
        assert_eq!(
            confinement(false, root, Some(wanted.as_os_str())),
            None,
            "once is enough"
        );
    }
}
