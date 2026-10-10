//! The shell's own page: what it shows whenever the operator UI itself cannot be shown.
//!
//! The page is bundled with the app and takes everything it shows from its address's
//! fragment, as JSON. So it needs no channel back into the app, and the app grants it
//! none: the page can only display what the shell put in its address.

use std::path::Path;

use serde::Serialize;
use tauri::Url;

use crate::server::{Refusal, StartError};

/// The address the bundled page is served at on macOS.
pub const PAGE: &str = "tauri://localhost/index.html";

/// One state of the page.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Status {
    /// Which picture the page shows: `starting`, `waiting` or `problem`.
    pub kind: &'static str,
    pub title: String,
    /// Plain sentences, one paragraph each.
    pub lines: Vec<String>,
    /// A command to run in Terminal, shown so it can be copied; never run by the app.
    pub command: Option<String>,
    /// Extra detail shown smaller, such as the end of the server's log.
    pub detail: Option<String>,
}

impl Status {
    fn new(kind: &'static str, title: impl Into<String>, lines: Vec<String>) -> Self {
        Self {
            kind,
            title: title.into(),
            lines,
            command: None,
            detail: None,
        }
    }

    pub fn starting(checkout: &Path) -> Self {
        Self::new(
            "starting",
            "Starting the operator UI",
            vec![format!("From the checkout at {}.", checkout.display())],
        )
    }

    pub fn no_run_folders() -> Self {
        Self::new(
            "waiting",
            "No run folders yet",
            vec![
                "The operator UI shows runs from folders you choose.".into(),
                "In the menu bar, choose Run Folders → Add Run Folder…, then pick a run folder, \
                 or a folder that holds run folders. The app remembers it."
                    .into(),
            ],
        )
    }

    pub fn no_checkout(checkout: &Path) -> Self {
        Self::new(
            "problem",
            "No physgate checkout here",
            vec![
                format!("There is no physgate checkout at {}.", checkout.display()),
                "In the menu bar, choose Checkout and pick another one.".into(),
            ],
        )
    }

    /// The page for a start that gave no address.
    pub fn from_start_error(error: &StartError, checkout: &Path) -> Self {
        match error {
            StartError::NoEntryPoint(program) => {
                let mut status = Self::new(
                    "problem",
                    "This checkout has no Python environment",
                    vec![
                        format!("{} is missing.", program.display()),
                        "Run this once in Terminal, then choose View → Restart Server:".into(),
                    ],
                );
                status.command = Some(format!("cd {} && uv sync", quote(checkout)));
                status
            }
            StartError::Refused(refusal, log_tail) => {
                Self::from_refusal(refusal.as_ref(), log_tail, checkout)
            }
            StartError::Failed(reason) => Self::new(
                "problem",
                "The operator UI could not start",
                vec![
                    reason.clone(),
                    "Choose View → Restart Server to try again.".into(),
                ],
            ),
        }
    }

    fn from_refusal(refusal: Option<&Refusal>, log_tail: &str, checkout: &Path) -> Self {
        let Some(refusal) = refusal else {
            let mut status = Self::new(
                "problem",
                "The server stopped before it started",
                vec!["The end of its log is below. View → Show Server Log has all of it.".into()],
            );
            status.detail = Some(log_tail.to_string());
            return status;
        };
        let mut lines = vec![format!("It said: {}.", refusal.error)];
        lines.extend(refusal.context.iter().map(|(k, v)| format!("{k}: {v}")));
        let mut status = Self::new("problem", "The server refused to start", lines);
        if refusal.error.contains("scripts/build-ui.sh") {
            status
                .lines
                .push("Build the UI by running this in Terminal. The app reloads by itself when the build finishes:".into());
            status.command = Some(build_command(checkout));
        }
        status
    }

    /// The page's address, with this state in its fragment.
    pub fn url(&self) -> Url {
        let json = serde_json::to_string(self).expect("a status always serialises");
        let mut url = Url::parse(PAGE).expect("the page address parses");
        url.set_fragment(Some(&percent_encode(&json)));
        url
    }
}

/// The command that builds the checkout's UI, installing its packages first when they are missing.
pub fn build_command(checkout: &Path) -> String {
    let at = quote(checkout);
    if checkout.join("ui/node_modules").is_dir() {
        format!("cd {at} && scripts/build-ui.sh")
    } else {
        format!("cd {at} && (cd ui && pnpm install --frozen-lockfile) && scripts/build-ui.sh")
    }
}

/// A path quoted for the shell, so a space in it does not split the command.
fn quote(path: &Path) -> String {
    let text = path.display().to_string();
    if text
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || "/._-~".contains(c))
    {
        text
    } else {
        format!("'{}'", text.replace('\'', r"'\''"))
    }
}

/// Every byte but an unreserved one written as `%XX`, so the page can decode it whole.
fn percent_encode(text: &str) -> String {
    let mut out = String::with_capacity(text.len() * 3);
    for byte in text.bytes() {
        if byte.is_ascii_alphanumeric() || b"-._~".contains(&byte) {
            out.push(char::from(byte));
        } else {
            const HEX: &[u8; 16] = b"0123456789ABCDEF";
            out.push('%');
            out.push(char::from(HEX[usize::from(byte >> 4)]));
            out.push(char::from(HEX[usize::from(byte & 0x0F)]));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn decoded(url: &Url) -> serde_json::Value {
        let fragment = url.fragment().unwrap();
        let bytes: Vec<u8> = {
            let mut out = Vec::new();
            let raw = fragment.as_bytes();
            let mut i = 0;
            while i < raw.len() {
                if raw[i] == b'%' {
                    let hex = std::str::from_utf8(&raw[i + 1..i + 3]).unwrap();
                    out.push(u8::from_str_radix(hex, 16).unwrap());
                    i += 3;
                } else {
                    out.push(raw[i]);
                    i += 1;
                }
            }
            out
        };
        serde_json::from_slice(&bytes).unwrap()
    }

    #[test]
    fn the_state_travels_whole_in_the_fragment() {
        let status = Status::no_checkout(Path::new("/Users/me/dev/phys gate #1 'x'"));
        let url = status.url();
        assert!(url.as_str().starts_with("tauri://localhost/index.html#"));
        let value = decoded(&url);
        assert_eq!(value["kind"], "problem");
        assert!(value["lines"][0]
            .as_str()
            .unwrap()
            .contains("phys gate #1 'x'"));
    }

    #[test]
    fn a_stale_build_shows_the_command_and_no_button() {
        let refusal = Refusal {
            error: "the UI build is stale; build it with scripts/build-ui.sh".into(),
            context: vec![],
        };
        let checkout = PathBuf::from("/Users/me/dev/physgate");
        let status = Status::from_start_error(
            &StartError::Refused(Some(refusal), String::new()),
            &checkout,
        );
        let command = status.command.unwrap();
        assert!(command.starts_with("cd /Users/me/dev/physgate && "));
        assert!(command.ends_with("scripts/build-ui.sh"));
    }

    #[test]
    fn a_path_with_a_quote_is_quoted_safely() {
        assert_eq!(quote(Path::new("/a/b")), "/a/b");
        assert_eq!(quote(Path::new("/a b/it's")), r"'/a b/it'\''s'");
    }
}
