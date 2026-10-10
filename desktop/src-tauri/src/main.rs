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
mod keychain;
mod menu;
mod navigation;
mod onboarding;
mod runs;
mod server;
mod shell;
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

fn main() {
    let tour = std::env::var_os("PHYSGATE_DESKTOP_TOUR").map(PathBuf::from);
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Shell::new(Paths::from_env(), tour))
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
            // shows only "Starting". The webview names it in any of these forms.
            for first in ["tauri://localhost", "tauri://localhost/", status::PAGE] {
                gate.issue(&tauri::Url::parse(first).expect("the page address parses"));
            }
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
    app.run(|app, event| {
        if let RunEvent::Exit = event {
            app.state::<Shell>().stop_server();
        }
    });
}
