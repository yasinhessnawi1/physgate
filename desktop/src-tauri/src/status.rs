//! The shell's own page: what it shows whenever the operator UI itself cannot be shown.
//!
//! That is only while the server starts, when it could not start or stopped, and when there is
//! no checkout to start it from. A run folder with no runs in it is not one of these: the
//! operator UI is shown, and says so itself.
//!
//! The page is bundled with the app and takes everything it shows from its address's
//! fragment, as JSON. So it needs no channel back into the app, and the app grants it
//! none: the page can only display what the shell put in its address.
//!
//! No state of the page shows a terminal command. It says in plain words what happened and
//! where to look next (View → Show Server Log, the Checkout menu), and a line the server wrote
//! that names a command is left out, so even a refusal cannot put one on the page.

use std::path::Path;

use serde::Serialize;
use tauri::Url;

use crate::commands::names_a_command;
use crate::server::{Refusal, StartError};

/// The address the bundled page is served at on macOS.
pub const PAGE: &str = "tauri://localhost/index.html";

/// One state of the page.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Status {
    /// Which picture the page shows: `starting` or `problem`.
    pub kind: &'static str,
    pub title: String,
    /// Plain sentences, one paragraph each. None names a terminal command.
    pub lines: Vec<String>,
}

/// Where the whole story is, on every page that reports a problem.
const SEE_THE_LOG: &str = "View → Show Server Log has everything the server wrote.";

/// Where another checkout is chosen.
const CHOOSE_A_CHECKOUT: &str =
    "To use another checkout, choose Checkout → Choose Another Checkout… in the menu bar.";

impl Status {
    /// A page in this state. Any line that names a terminal command is left out.
    fn new(kind: &'static str, title: impl Into<String>, lines: Vec<String>) -> Self {
        Self {
            kind,
            title: title.into(),
            lines: lines
                .into_iter()
                .filter(|line| !names_a_command(line))
                .collect(),
        }
    }

    pub fn starting(checkout: &Path) -> Self {
        Self::new(
            "starting",
            "Starting the operator UI",
            vec![format!("From the checkout at {}.", checkout.display())],
        )
    }

    /// The default run root is there but cannot be used, for the reason given.
    pub fn root_refused(reason: &str) -> Self {
        Self::new(
            "problem",
            "The run folder can't be used",
            vec![
                format!("{reason}."),
                "Remove what is there (whatever a link points at is not touched), then choose \
                 View → Restart Server; the app makes the folder afresh."
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
                CHOOSE_A_CHECKOUT.into(),
            ],
        )
    }

    /// The page for a start that gave no address.
    pub fn from_start_error(error: &StartError, checkout: &Path) -> Self {
        match error {
            StartError::NoEntryPoint(program) => Self::new(
                "problem",
                "This checkout is not set up yet",
                vec![
                    format!(
                        "The checkout at {} has no Python environment, so the operator UI \
                         cannot start from it: {} is missing.",
                        checkout.display(),
                        program.display()
                    ),
                    "Set the checkout up as its README describes, then choose View → Restart \
                     Server."
                        .into(),
                    CHOOSE_A_CHECKOUT.into(),
                ],
            ),
            StartError::Refused(refusal) => Self::from_refusal(refusal.as_ref()),
            StartError::Failed(reason) => Self::new(
                "problem",
                "The operator UI could not start",
                vec![
                    reason.clone(),
                    SEE_THE_LOG.into(),
                    "Choose View → Restart Server to try again.".into(),
                ],
            ),
        }
    }

    fn from_refusal(refusal: Option<&Refusal>) -> Self {
        let Some(refusal) = refusal else {
            return Self::new(
                "problem",
                "The server stopped before it started",
                vec![
                    "It wrote why to its log before it stopped.".into(),
                    SEE_THE_LOG.into(),
                    "Choose View → Restart Server to try again.".into(),
                ],
            );
        };
        if is_about_the_build(&refusal.error) {
            return Self::new(
                "problem",
                "The operator UI is not built",
                vec![
                    "This checkout's operator UI has no build yet, or its build is older than \
                     its sources."
                        .into(),
                    "The app starts the server by itself as soon as a build of this checkout \
                     finishes."
                        .into(),
                    SEE_THE_LOG.into(),
                    CHOOSE_A_CHECKOUT.into(),
                ],
            );
        }
        let mut lines = vec![format!("It said: {}.", refusal.error)];
        lines.extend(refusal.context.iter().map(|(k, v)| format!("{k}: {v}")));
        lines.push(SEE_THE_LOG.into());
        Self::new("problem", "The server refused to start", lines)
    }

    /// The page's address, with this state in its fragment.
    pub fn url(&self) -> Url {
        let json = serde_json::to_string(self).expect("a status always serialises");
        let mut url = Url::parse(PAGE).expect("the page address parses");
        url.set_fragment(Some(&percent_encode(&json)));
        url
    }
}

/// Whether a refusal is the server's "no build, or a stale one".
fn is_about_the_build(error: &str) -> bool {
    error.contains("build it with") || error.contains("no build")
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
        // The page carries a title, a kind and sentences: no command field, no log tail.
        let keys: Vec<&String> = value.as_object().unwrap().keys().collect();
        assert_eq!(keys, ["kind", "lines", "title"]);
    }

    fn refused(error: &str, context: &[(&str, &str)]) -> StartError {
        StartError::Refused(Some(Refusal {
            error: error.into(),
            context: context
                .iter()
                .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
                .collect(),
        }))
    }

    /// Every state the page can be put in, with what the server could say at its worst.
    fn every_state() -> Vec<Status> {
        let checkout = PathBuf::from("/Users/me/dev/physgate");
        vec![
            Status::starting(&checkout),
            Status::root_refused("~/physgate-runs is a link"),
            Status::no_checkout(&checkout),
            Status::from_start_error(
                &StartError::NoEntryPoint(checkout.join(".venv/bin/physgate")),
                &checkout,
            ),
            Status::from_start_error(
                &refused(
                    "the UI build is stale; build it with scripts/build-ui.sh",
                    &[("ui", "/Users/me/dev/physgate/ui")],
                ),
                &checkout,
            ),
            Status::from_start_error(
                &refused("there is no build to stamp", &[("dist", "/c/ui/dist")]),
                &checkout,
            ),
            Status::from_start_error(
                &refused(
                    "a root must be an existing directory",
                    &[
                        ("root", "/runs"),
                        ("hint", "physgate run --run-dir /runs/x"),
                    ],
                ),
                &checkout,
            ),
            Status::from_start_error(&StartError::Refused(None), &checkout),
            Status::from_start_error(
                &StartError::Failed("usage: physgate ui [-h] --root ROOT".into()),
                &checkout,
            ),
        ]
    }

    #[test]
    fn no_state_of_the_page_names_a_command_whatever_the_server_said() {
        for status in every_state() {
            let shown = serde_json::to_string(&status).unwrap();
            assert!(!names_a_command(&shown), "{shown}");
            if status.kind == "problem" {
                assert!(
                    status
                        .lines
                        .iter()
                        .any(|l| l.contains("View →") || l.contains("Checkout →")),
                    "a problem says, in the menu bar, where to go next: {shown}"
                );
            }
        }
    }

    #[test]
    fn a_stale_build_is_said_in_plain_words_and_points_at_the_log() {
        let status = Status::from_start_error(
            &refused(
                "the UI build is stale; build it with scripts/build-ui.sh",
                &[],
            ),
            Path::new("/Users/me/dev/physgate"),
        );
        assert_eq!(status.title, "The operator UI is not built");
        assert!(status.lines.contains(&SEE_THE_LOG.to_string()));
        assert!(status.lines.contains(&CHOOSE_A_CHECKOUT.to_string()));
        assert!(!status.lines.iter().any(|l| l.contains("scripts/")));
    }

    #[test]
    fn a_refusal_keeps_its_sentence_and_drops_a_line_that_names_a_command() {
        let status = Status::from_start_error(
            &refused(
                "a root must be an existing directory",
                &[
                    ("root", "/runs"),
                    ("hint", "physgate run --run-dir /runs/x"),
                ],
            ),
            Path::new("/c"),
        );
        assert_eq!(
            status.lines,
            [
                "It said: a root must be an existing directory.",
                "root: /runs",
                SEE_THE_LOG,
            ]
        );
    }
}
