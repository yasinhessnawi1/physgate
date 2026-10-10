//! The menu bar: every control the shell has. The served page gets none.

use std::path::PathBuf;
use std::process::Command;
use std::thread;

use tauri::menu::{
    CheckMenuItemBuilder, Menu, MenuBuilder, MenuEvent, MenuItemBuilder, SubmenuBuilder,
};
use tauri::{AppHandle, Manager, Wry};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

use crate::shell::Shell;
use crate::update;

const CHECK_UPDATE: &str = "check-update";
const SETTINGS: &str = "settings";
const ENGINE: &str = "engine";
const REPLAY_INTRO: &str = "replay-intro";
const RELOAD: &str = "reload";
const RESTART: &str = "restart";
const SERVER_LOG: &str = "server-log";
const CHOOSE_CHECKOUT: &str = "checkout-choose";
const ADD_RUN_FOLDER: &str = "run-add";
const CHECKOUT_PREFIX: &str = "checkout:";
const REMOVE_PREFIX: &str = "run-remove:";

/// Build the menu bar from the current settings and worktrees.
pub fn build(app: &AppHandle) -> tauri::Result<Menu<Wry>> {
    let shell = app.state::<Shell>();
    let settings = shell.settings();
    let worktrees = shell.worktrees();

    let app_menu = SubmenuBuilder::new(app, "physgate")
        .about(None)
        .separator()
        .item(&MenuItemBuilder::with_id(CHECK_UPDATE, "Check for Shell Update…").build(app)?)
        .item(&MenuItemBuilder::with_id(ENGINE, "Engine…").build(app)?)
        .item(&MenuItemBuilder::with_id(REPLAY_INTRO, "Replay Intro").build(app)?)
        .item(&MenuItemBuilder::with_id(SETTINGS, "Open Settings File").build(app)?)
        .separator()
        .hide()
        .hide_others()
        .show_all()
        .separator()
        .quit()
        .build()?;

    let edit = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;

    let view = SubmenuBuilder::new(app, "View")
        .item(
            &MenuItemBuilder::with_id(RELOAD, "Reload")
                .accelerator("CmdOrCtrl+R")
                .build(app)?,
        )
        .item(
            &MenuItemBuilder::with_id(RESTART, "Restart Server")
                .accelerator("CmdOrCtrl+Shift+R")
                .build(app)?,
        )
        .separator()
        .item(&MenuItemBuilder::with_id(SERVER_LOG, "Show Server Log").build(app)?)
        .separator()
        .fullscreen()
        .build()?;

    let mut checkout = SubmenuBuilder::new(app, "Checkout");
    for (i, worktree) in worktrees.iter().enumerate() {
        checkout = checkout.item(
            &CheckMenuItemBuilder::with_id(format!("{CHECKOUT_PREFIX}{i}"), &worktree.label)
                .checked(worktree.path == settings.checkout)
                .build(app)?,
        );
    }
    let checkout = checkout
        .separator()
        .item(&MenuItemBuilder::with_id(CHOOSE_CHECKOUT, "Choose Another Checkout…").build(app)?)
        .build()?;

    let mut runs = SubmenuBuilder::new(app, "Run Folders");
    if settings.run_folders.is_empty() {
        runs = runs.item(
            &MenuItemBuilder::new("No run folders yet")
                .enabled(false)
                .build(app)?,
        );
    }
    for folder in &settings.run_folders {
        runs = runs.item(
            &MenuItemBuilder::new(folder.display().to_string())
                .enabled(false)
                .build(app)?,
        );
    }
    runs = runs.separator().item(
        &MenuItemBuilder::with_id(ADD_RUN_FOLDER, "Add Run Folder…")
            .accelerator("CmdOrCtrl+O")
            .build(app)?,
    );
    if !settings.run_folders.is_empty() {
        let mut remove = SubmenuBuilder::new(app, "Remove Run Folder");
        for (i, folder) in settings.run_folders.iter().enumerate() {
            remove = remove.item(
                &MenuItemBuilder::with_id(
                    format!("{REMOVE_PREFIX}{i}"),
                    folder.display().to_string(),
                )
                .build(app)?,
            );
        }
        runs = runs.item(&remove.build()?);
    }
    let runs = runs.build()?;

    let window = SubmenuBuilder::new(app, "Window")
        .minimize()
        .maximize()
        .separator()
        .close_window()
        .build()?;

    MenuBuilder::new(app)
        .items(&[&app_menu, &edit, &view, &checkout, &runs, &window])
        .build()
}

/// Rebuild the menu bar after the settings changed.
pub fn refresh(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Ok(menu) = build(&handle) {
            let _ = handle.set_menu(menu);
        }
    });
}

/// Act on a menu choice. Anything that waits (a dialog, a server start) runs on its own thread.
pub fn on_event(app: &AppHandle, event: &MenuEvent) {
    let id = event.id().as_ref().to_string();
    let app = app.clone();
    match id.as_str() {
        CHECK_UPDATE => update::check(&app, true),
        ENGINE => app.state::<Shell>().onboard(&app, "engine"),
        REPLAY_INTRO => app.state::<Shell>().onboard(&app, "intro"),
        SETTINGS => open_in_editor(app.state::<Shell>().settings_file()),
        SERVER_LOG => open_in_editor(app.state::<Shell>().paths.server_log()),
        RELOAD => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval("window.location.reload()");
            }
        }
        RESTART => restart_in_background(app),
        ADD_RUN_FOLDER => {
            thread::spawn(move || {
                let picked = app
                    .dialog()
                    .file()
                    .set_title("Add a run folder: a run, or a folder of runs")
                    .blocking_pick_folder()
                    .and_then(|p| p.into_path().ok());
                if let Some(folder) = picked {
                    change(&app, |s| {
                        s.add_run_folder(folder);
                    });
                }
            });
        }
        CHOOSE_CHECKOUT => {
            thread::spawn(move || {
                let picked = app
                    .dialog()
                    .file()
                    .set_title("Choose a physgate checkout")
                    .blocking_pick_folder()
                    .and_then(|p| p.into_path().ok());
                if let Some(folder) = picked {
                    change(&app, |s| s.checkout = folder);
                }
            });
        }
        other => {
            if let Some(i) = index_after(other, CHECKOUT_PREFIX) {
                let chosen: Option<PathBuf> = app
                    .state::<Shell>()
                    .worktrees()
                    .get(i)
                    .map(|w| w.path.clone());
                if let Some(path) = chosen {
                    thread::spawn(move || change(&app, |s| s.checkout = path));
                }
            } else if let Some(i) = index_after(other, REMOVE_PREFIX) {
                thread::spawn(move || {
                    change(&app, |s| {
                        if i < s.run_folders.len() {
                            s.run_folders.remove(i);
                        }
                    });
                });
            }
        }
    }
}

fn index_after(id: &str, prefix: &str) -> Option<usize> {
    id.strip_prefix(prefix)?.parse().ok()
}

/// Change the settings, then restart so the server serves what they now name.
fn change(app: &AppHandle, edit: impl FnOnce(&mut crate::config::Settings)) {
    let shell = app.state::<Shell>();
    if let Err(problem) = shell.change_settings(edit) {
        app.dialog()
            .message(problem)
            .kind(MessageDialogKind::Error)
            .buttons(MessageDialogButtons::Ok)
            .blocking_show();
        return;
    }
    shell.restart(app);
}

pub fn restart_in_background(app: AppHandle) {
    thread::spawn(move || app.state::<Shell>().restart(&app));
}

/// Open a text file in the default editor.
fn open_in_editor(path: PathBuf) {
    if !path.exists() {
        return;
    }
    let _ = Command::new("/usr/bin/open").arg("-t").arg(path).spawn();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn indexed_ids_are_read_back() {
        assert_eq!(index_after("checkout:3", CHECKOUT_PREFIX), Some(3));
        assert_eq!(index_after("run-remove:0", REMOVE_PREFIX), Some(0));
        assert_eq!(index_after("run-remove:x", REMOVE_PREFIX), None);
        assert_eq!(index_after("reload", CHECKOUT_PREFIX), None);
    }
}
