//! The commands the onboarding page calls: the welcome, the engine step, and the hand-over to
//! the operator UI.
//!
//! Only the app's own bundled pages can call these (the onboarding capability names no
//! remote address), and the window reaches those pages only where the shell sends it.
//! Credentials pass one way: in from the sign-in or the key field, into the Keychain. No
//! command returns one, and the state a page can read says only whether one is kept.

// Tauri hands a command its arguments by value (the app handle, the managed state), so a
// command cannot take them by reference.
#![allow(clippy::needless_pass_by_value)]

use std::path::PathBuf;

use tauri::{AppHandle, Manager, State, Url};

use crate::engine::{self, ClaudeCode, Device, SignIn, SignInView};
use crate::keychain::{self, Secret};
use crate::shell::Shell;

/// The onboarding page, opened at a step: `intro` or `engine`.
pub fn page(step: &str) -> Url {
    let mut url = Url::parse("tauri://localhost/onboarding.html").expect("the page address parses");
    url.set_fragment(Some(step));
    url
}

#[tauri::command]
pub fn onboarding_state(app: AppHandle) -> serde_json::Value {
    let settings = app.state::<Shell>().settings();
    serde_json::json!({
        "intro_seen": settings.intro_seen,
        "engine": settings.engine,
        "implementer": settings.implementer_model,
        "reviewer": settings.reviewer_model,
        "catalogue": engine::catalogue(),
        "install_command": engine::INSTALL_COMMAND,
        "kept": {
            "subscription_token": keychain::is_stored(Secret::SubscriptionToken),
            "api_key": keychain::is_stored(Secret::ApiKey),
        },
        "handover": {
            "subscription_token": keychain::handover_line(Secret::SubscriptionToken),
            "api_key": keychain::handover_line(Secret::ApiKey),
        },
    })
}

#[tauri::command]
pub fn claude_code_detect() -> ClaudeCode {
    engine::detect()
}

/// Open Terminal with Claude Code's official installer, on the operator's click.
#[tauri::command]
pub fn claude_code_install(app: AppHandle) -> Result<(), String> {
    let shell = app.state::<Shell>();
    shell.note("opened the Claude Code installer in Terminal");
    engine::open_in_terminal(
        shell.paths.root(),
        "install-claude-code.command",
        &engine::install_script(),
    )
}

fn claude_path() -> Result<PathBuf, String> {
    engine::detect()
        .path
        .map(PathBuf::from)
        .ok_or_else(|| "Claude Code is not installed".to_string())
}

#[tauri::command]
pub fn sign_in_start(app: AppHandle, sign_in: State<'_, SignIn>) -> Result<SignInView, String> {
    app.state::<Shell>().note("sign-in for runs started");
    sign_in.start(&claude_path()?)
}

#[tauri::command]
pub fn sign_in_status(sign_in: State<'_, SignIn>) -> SignInView {
    sign_in.view()
}

#[tauri::command]
pub fn sign_in_return(sign_in: State<'_, SignIn>) {
    sign_in.press_return();
}

#[tauri::command]
pub fn sign_in_cancel(sign_in: State<'_, SignIn>) {
    sign_in.cancel();
}

/// The fallback: sign in in Terminal, then paste the token into the masked field.
#[tauri::command]
pub fn sign_in_in_terminal(app: AppHandle) -> Result<(), String> {
    let path = claude_path()?;
    let shell = app.state::<Shell>();
    shell.note("opened the sign-in in Terminal");
    engine::open_in_terminal(
        shell.paths.root(),
        "sign-in-claude-code.command",
        &engine::sign_in_script(&path.display().to_string()),
    )
}

/// Keep a credential typed or pasted into the page. It goes to the Keychain and nowhere else.
#[tauri::command]
pub fn store_secret(app: AppHandle, secret: Secret, value: String) -> Result<(), String> {
    let result = keychain::store(secret, value.trim());
    drop(value);
    let shell = app.state::<Shell>();
    match &result {
        Ok(()) => shell.note(&format!("{} kept in the Keychain", secret.account())),
        Err(_) => shell.note(&format!("{} refused", secret.account())),
    }
    result
}

#[tauri::command]
pub fn forget_secret(app: AppHandle, secret: Secret) {
    keychain::forget(secret);
    app.state::<Shell>()
        .note(&format!("{} removed from the Keychain", secret.account()));
}

/// The one request the app makes for the operator, only on this click: is the kept key
/// accepted by Anthropic?
#[tauri::command]
pub async fn test_api_key(app: AppHandle) -> Result<String, String> {
    app.state::<Shell>()
        .note("Test Key: one request to api.anthropic.com, asked for by the operator");
    engine::test_api_key().await
}

#[tauri::command]
pub fn choose_engine(
    app: AppHandle,
    engine: String,
    implementer: Option<String>,
    reviewer: Option<String>,
) -> Result<(), String> {
    engine::check_choice(&engine, implementer.as_deref(), reviewer.as_deref())?;
    let api = engine == "claude-api";
    app.state::<Shell>().change_settings(|s| {
        s.engine = Some(engine);
        if api {
            s.implementer_model = implementer;
            s.reviewer_model = reviewer;
        }
    })
}

#[tauri::command]
pub fn device_report() -> Device {
    engine::device()
}

#[tauri::command]
pub fn intro_seen(app: AppHandle) -> Result<(), String> {
    app.state::<Shell>()
        .change_settings(|s| s.intro_seen = true)
}

/// Done: remember it, and show the operator UI.
#[tauri::command]
pub fn finish_onboarding(app: AppHandle) -> Result<(), String> {
    app.state::<Shell>().change_settings(|s| {
        s.onboarded = true;
        s.intro_seen = true;
    })?;
    crate::menu::restart_in_background(app);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_capability_reaches_a_remote_address() {
        let text = include_str!("../capabilities/onboarding.json");
        let capability: serde_json::Value = serde_json::from_str(text).unwrap();
        assert!(
            capability.get("remote").is_none(),
            "a remote URL is granted"
        );
        assert_eq!(capability["windows"], serde_json::json!(["main"]));
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        assert_eq!(
            config["app"]["security"]["capabilities"],
            serde_json::json!(["onboarding"]),
            "only this capability is enabled"
        );
    }

    #[test]
    fn the_state_a_page_reads_never_holds_a_credential() {
        // The page's state is built from booleans and fixed text; this checks the fixed text.
        let lines = [
            keychain::handover_line(Secret::SubscriptionToken),
            keychain::handover_line(Secret::ApiKey),
            engine::INSTALL_COMMAND.to_string(),
        ];
        assert!(lines.iter().all(|l| !l.contains("sk-ant-")));
    }

    #[test]
    fn the_page_opens_at_its_step() {
        assert_eq!(
            page("intro").as_str(),
            "tauri://localhost/onboarding.html#intro"
        );
    }
}
