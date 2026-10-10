//! A scripted walk through the onboarding screens, for screenshots of each step.
//!
//! Compiled only with the `walkthrough` feature, never into a published build, and started
//! only when `PHYSGATE_DESKTOP_WALKTHROUGH` names a folder. Before each screenshot it writes
//! `<step>.ready` there and waits for `<step>.done`, which the script taking the screenshots
//! writes. It is meant to run against a stand-in Claude Code (`PHYSGATE_DESKTOP_CLAUDE`) and a
//! Keychain service of its own (`PHYSGATE_DESKTOP_KEYCHAIN_SERVICE`), with a made-up key in
//! `PHYSGATE_DESKTOP_WALK_KEY`, so no real account or credential is involved.
//!
//! The script it evaluates in the page is fixed here, with the one value it types encoded
//! as a JSON string; nothing from outside the app becomes code.

use std::fs;
use std::path::PathBuf;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};

fn click(text: &str) -> String {
    format!(
        "[...document.querySelectorAll('button, .card')].find((b) => b.textContent.trim().startsWith({})).click()",
        serde_json::to_string(text).unwrap_or_default()
    )
}

#[allow(clippy::too_many_lines)] // one line per step of the script, read top to bottom
pub fn start(app: AppHandle) {
    let Some(folder) = crate::config::switch("PHYSGATE_DESKTOP_WALKTHROUGH").map(PathBuf::from)
    else {
        return;
    };
    let key = crate::config::switch("PHYSGATE_DESKTOP_WALK_KEY")
        .and_then(|k| k.into_string().ok())
        .unwrap_or_default();
    thread::spawn(move || {
        let _ = fs::create_dir_all(&folder);
        let eval = |js: &str| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(js);
            }
        };
        let mut n = 0;
        let mut step = |name: &str, js: Option<String>, settle: u64| {
            if let Some(js) = js {
                eval(&js);
            }
            thread::sleep(Duration::from_millis(settle));
            n += 1;
            let stem = format!("{n:02}-{name}");
            let _ = fs::write(folder.join(format!("{stem}.ready")), "");
            let done = folder.join(format!("{stem}.done"));
            let deadline = Instant::now() + Duration::from_secs(120);
            while !done.exists() && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(100));
            }
        };
        // Each script runs in a block of its own: they share the page's global scope.
        let show = |selector: &str| {
            format!("setTimeout(() => document.querySelector('{selector}')?.scrollIntoView({{ block: 'center' }}), 900)")
        };
        // At three seconds the film shows the gate, not the poster (its last frame).
        step("welcome-intro", None, 3000);
        step(
            "engine-claude-code",
            Some("{ document.getElementById('skip').click(); }".into()),
            2500,
        );
        step(
            "sign-in-running",
            Some(format!("{{ {}; {} }}", click("Sign In"), show("#progress"))),
            2200,
        );
        step(
            "signed-in-for-runs",
            Some(format!("{{ {} }}", show("#sign-in"))),
            6000,
        );
        std::env::set_var("PHYSGATE_DESKTOP_CLAUDE", "/nonexistent/claude");
        step(
            "claude-code-not-installed",
            Some(format!(
                "{{ {}; setTimeout(() => {{ {}; }}, 300); {} }}",
                click("Claude API"),
                click("Claude Code"),
                show("#panel")
            )),
            2500,
        );
        step(
            "api-key-entry",
            Some(format!(
                "{{ {}; setTimeout(() => {{ document.querySelector('input[type=password]').value = {}; }}, 600); {} }}",
                click("Claude API"),
                serde_json::to_string(&key).unwrap_or_default(),
                show("#panel")
            )),
            1800,
        );
        step(
            "api-key-kept",
            Some(format!("{{ {}; {} }}", click("Keep Key"), show("#panel"))),
            1800,
        );
        step(
            "api-models-must-differ",
            Some("{ const r = document.getElementById('reviewer'); r.value = document.getElementById('implementer').value;                   r.dispatchEvent(new Event('change')); r.scrollIntoView({ block: 'center' }); }".into()),
            800,
        );
        step(
            "api-test-key",
            Some(format!(
                "{{ const r = document.getElementById('reviewer'); r.value = 'claude-sonnet-5'; r.dispatchEvent(new Event('change')); {};                  setTimeout(() => document.getElementById('test-result').scrollIntoView({{ block: 'center' }}), 300); }}",
                click("Test Key")
            )),
            5000,
        );
        step(
            "local-model-not-yet",
            Some(format!(
                "{{ {}; {} }}",
                click("A model on this Mac"),
                show("#panel")
            )),
            3500,
        );
        step(
            "other-provider-not-yet",
            Some(format!("{{ {}; {} }}", click("OpenAI API"), show("#panel"))),
            1500,
        );
        step(
            "operator-ui",
            Some(format!(
                "{{ {}; setTimeout(() => document.getElementById('continue').click(), 800); }}",
                click("Claude API")
            )),
            7000,
        );
        let _ = fs::write(folder.join("finished"), "");
    });
}
