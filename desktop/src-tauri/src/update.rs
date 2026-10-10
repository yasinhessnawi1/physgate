//! Updating the shell itself from the local channel: check, ask, install, relaunch.
//!
//! The operator UI never needs this: a UI change reaches the window by rebuilding the UI.
//! This is for changes to the shell (its menu, its pages, how it starts the server).

use std::time::Duration;

use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

use crate::channel::Channel;
use crate::shell::Shell;

/// Check the channel. `asked` is true when the person chose the menu item, so every outcome
/// is reported; at launch only a found update is.
pub fn check(app: &AppHandle, asked: bool) {
    let app = app.clone();
    // Its own thread: the dialogs below wait for an answer, and must not hold up the
    // main thread or the async runtime while they do.
    std::thread::spawn(move || {
        let outcome = tauri::async_runtime::block_on(run(&app));
        let shell = app.state::<Shell>();
        match outcome {
            Ok(Some(note)) if asked => tell(&app, "Shell update", &note),
            Ok(_) => {}
            Err(problem) => {
                shell.note(&format!("update check failed: {problem}"));
                if asked {
                    tell(&app, "Shell update", &problem);
                }
            }
        }
    });
}

/// The public key built into this copy of the app; empty when it was built without one.
fn public_key(app: &AppHandle) -> String {
    app.config()
        .plugins
        .0
        .get("updater")
        .and_then(|updater| updater.get("pubkey"))
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default()
        .to_string()
}

/// `Ok(Some(note))` to tell the person, `Ok(None)` when an update was installed (the app
/// relaunches before this returns) or declined.
async fn run(app: &AppHandle) -> Result<Option<String>, String> {
    if public_key(app).is_empty() {
        return Err(
            "This copy of the app was built without an update key, so it cannot \
                    update itself. Build it with scripts/build-desktop.sh."
                .into(),
        );
    }
    let shell = app.state::<Shell>();
    let folder = shell.paths.updates();
    let Some(channel) = Channel::open(&folder).map_err(|e| format!("{}: {e}", folder.display()))?
    else {
        return Ok(Some("No shell update has been published yet.".into()));
    };
    let updater = app
        .updater_builder()
        .endpoints(vec![channel.manifest_url()])
        .map_err(|e| e.to_string())?
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| e.to_string())?;
    let Some(update) = updater.check().await.map_err(|e| e.to_string())? else {
        let version = app.package_info().version.to_string();
        shell.note(&format!("update check: {version} is the newest"));
        return Ok(Some(format!(
            "This is the newest version of the shell ({version})."
        )));
    };
    shell.note(&format!(
        "update check: {} is published, {} is running",
        update.version, update.current_version
    ));
    // A scripted check of the update path, in a verification build only, answers the
    // question by environment instead of by click. The bundle is still verified against the
    // built-in key before anything is replaced.
    let scripted =
        crate::config::switch("PHYSGATE_DESKTOP_ACCEPT_UPDATE").is_some_and(|v| v == "1");
    if scripted {
        shell.note("update accepted by PHYSGATE_DESKTOP_ACCEPT_UPDATE=1");
    }
    let install = scripted
        || app
            .dialog()
            .message(format!(
                "Version {} of the physgate app is ready (this one is {}).\n\n\
             Installing takes a few seconds and reopens the app. Your view is kept.",
                update.version, update.current_version
            ))
            .title("Update the physgate app?")
            .kind(MessageDialogKind::Info)
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Install and Restart".into(),
                "Later".into(),
            ))
            .blocking_show();
    if !install {
        shell.note("update declined");
        return Ok(None);
    }
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|e| format!("the update could not be installed: {e}"))?;
    drop(channel);
    shell.note(&format!("update {} installed; relaunching", update.version));
    shell.remember_view(app);
    shell.stop_server();
    app.restart();
}

fn tell(app: &AppHandle, title: &str, message: &str) {
    app.dialog()
        .message(message)
        .title(title)
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::Ok)
        .blocking_show();
}
