//! Where the shell keeps its files, and the settings it remembers between launches.
//!
//! Nothing here lives in the repository: the settings name paths on this machine, and
//! the update channel is filled by the build script on this machine. The folder is
//! `~/Library/Application Support/physgate-desktop`, or `PHYSGATE_DESKTOP_HOME` when set
//! (so a trial run never touches the real one).

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

/// The folders the shell reads and writes, all under one root.
#[derive(Debug, Clone)]
pub struct Paths {
    root: PathBuf,
}

impl Paths {
    /// The root named by `PHYSGATE_DESKTOP_HOME`, or the default under the home folder.
    pub fn from_env() -> Self {
        if let Some(root) = std::env::var_os("PHYSGATE_DESKTOP_HOME") {
            return Self::at(PathBuf::from(root));
        }
        Self::at(home().join("Library/Application Support/physgate-desktop"))
    }

    pub fn at(root: PathBuf) -> Self {
        Self { root }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// The settings file.
    pub fn settings(&self) -> PathBuf {
        self.root.join("settings.json")
    }

    /// What the operator server wrote to its standard error on its latest start.
    pub fn server_log(&self) -> PathBuf {
        self.root.join("server.log")
    }

    /// The running server's pid and program, so a server left by a killed app is stopped
    /// at the next start.
    pub fn server_pid(&self) -> PathBuf {
        self.root.join("server.pid")
    }

    /// The shell's own notes: starts, restarts, update checks.
    pub fn shell_log(&self) -> PathBuf {
        self.root.join("shell.log")
    }

    /// The update channel: `latest.json` and the signed bundle it names.
    pub fn updates(&self) -> PathBuf {
        self.root.join("updates")
    }
}

/// Append a line to the shell's own log in `paths`. Never given a credential.
pub fn note(paths: &Paths, line: &str) {
    use std::io::Write as _;
    let _ = fs::create_dir_all(paths.root());
    if let Ok(mut log) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(paths.shell_log())
    {
        let at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs());
        let _ = writeln!(log, "{at} {line}");
    }
}

/// The user's home folder.
pub fn home() -> PathBuf {
    std::env::var_os("HOME").map_or_else(|| PathBuf::from("/"), PathBuf::from)
}

/// What the shell remembers. Every field has a default, so an old or partial file still loads.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    /// The physgate checkout whose `physgate ui` the shell starts.
    pub checkout: PathBuf,
    /// The folders served: each a run directory or a directory of run directories.
    pub run_folders: Vec<PathBuf>,
    /// Paths passed to the server as `--held-out`, never opened by the shell.
    pub held_out: Vec<PathBuf>,
    /// Paths passed to the server as `--answer-key`, never opened by the shell.
    pub answer_keys: Vec<PathBuf>,
    /// Whether the welcome and the engine step have been through once.
    pub onboarded: bool,
    /// Whether the intro has been shown (it is shown once; the menu replays it).
    pub intro_seen: bool,
    /// The engine chosen: `claude-code` or `claude-api` today. A record of the choice only:
    /// a run's own parameters still name its credential mode and models.
    pub engine: Option<String>,
    /// For the Claude API: the model that implements and the model that reviews. Stored
    /// for a later change to wire; never overrides a run's parameters.
    pub implementer_model: Option<String>,
    pub reviewer_model: Option<String>,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            checkout: home().join("dev/physgate"),
            run_folders: Vec::new(),
            held_out: Vec::new(),
            answer_keys: Vec::new(),
            onboarded: false,
            intro_seen: false,
            engine: None,
            implementer_model: None,
            reviewer_model: None,
        }
    }
}

impl Settings {
    /// The settings at `path`; the defaults when there is no file yet.
    ///
    /// A file that is there but unreadable is an error rather than a silent reset, so a
    /// typing mistake in a hand edit never throws away the remembered folders.
    pub fn load(path: &Path) -> Result<Self, String> {
        match fs::read_to_string(path) {
            Ok(text) => serde_json::from_str(&text)
                .map_err(|e| format!("{} is not valid settings: {e}", path.display())),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(Self::default()),
            Err(e) => Err(format!("{} could not be read: {e}", path.display())),
        }
    }

    /// Write the settings whole, through a temporary file, so a crash never leaves half a file.
    pub fn save(&self, path: &Path) -> io::Result<()> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let text = serde_json::to_string_pretty(self).map_err(io::Error::other)?;
        let partial = path.with_extension("json.partial");
        fs::write(&partial, text + "\n")?;
        fs::rename(partial, path)
    }

    /// Add a run folder unless it is already there. Returns whether it was added.
    pub fn add_run_folder(&mut self, folder: PathBuf) -> bool {
        if self.run_folders.contains(&folder) {
            return false;
        }
        self.run_folders.push(folder);
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testdir::TestDir;

    #[test]
    fn a_missing_file_gives_the_defaults() {
        let dir = TestDir::new("settings-missing");
        let loaded = Settings::load(&dir.path().join("settings.json")).unwrap();
        assert_eq!(loaded, Settings::default());
        assert!(
            loaded.run_folders.is_empty(),
            "there is no default run folder"
        );
        assert!(loaded.checkout.ends_with("dev/physgate"));
    }

    #[test]
    fn settings_survive_a_save_and_a_load() {
        let dir = TestDir::new("settings-roundtrip");
        let path = dir.path().join("nested/settings.json");
        let mut settings = Settings::default();
        assert!(settings.add_run_folder(PathBuf::from("/runs/a")));
        assert!(
            !settings.add_run_folder(PathBuf::from("/runs/a")),
            "no duplicates"
        );
        settings.held_out.push(PathBuf::from("/held"));
        settings.save(&path).unwrap();
        assert_eq!(Settings::load(&path).unwrap(), settings);
        assert!(!path.with_extension("json.partial").exists());
    }

    #[test]
    fn a_partial_file_keeps_the_other_defaults() {
        let dir = TestDir::new("settings-partial");
        let path = dir.path().join("settings.json");
        fs::write(&path, r#"{"run_folders": ["/runs"]}"#).unwrap();
        let loaded = Settings::load(&path).unwrap();
        assert_eq!(loaded.run_folders, vec![PathBuf::from("/runs")]);
        assert_eq!(loaded.checkout, Settings::default().checkout);
    }

    #[test]
    fn a_broken_file_is_an_error_not_a_reset() {
        let dir = TestDir::new("settings-broken");
        let path = dir.path().join("settings.json");
        fs::write(&path, "{ not json").unwrap();
        let err = Settings::load(&path).unwrap_err();
        assert!(err.contains("not valid settings"), "{err}");
    }
}
