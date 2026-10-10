//! What the engine step needs from this Mac: the engine catalogue, Claude Code (is it there,
//! install it, sign it in for runs), a test of an API key, and what the device could run.

use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::os::fd::{FromRawFd, OwnedFd};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::config::home;
use crate::keychain::{self, Secret};

/// The engines the step offers, as data: two available, the rest not yet.
pub const CATALOGUE: &str = include_str!("../../onboarding/engines.json");

/// Claude Code's official installer, as its documentation gives it.
pub const INSTALL_COMMAND: &str = "curl -fsSL https://claude.ai/install.sh | bash";

pub fn catalogue() -> serde_json::Value {
    serde_json::from_str(CATALOGUE).expect("the bundled catalogue is valid JSON")
}

/// The engine `id` in the catalogue, if it is there and available today.
fn available(id: &str) -> Option<serde_json::Value> {
    catalogue()["engines"]
        .as_array()?
        .iter()
        .find(|e| e["id"] == id && e["status"] == "available")
        .cloned()
}

/// Check an engine choice. The API needs two models from its list, and they must differ: a
/// reviewer on the implementer's own model is no review (dispatch refuses it too).
pub fn check_choice(
    engine: &str,
    implementer: Option<&str>,
    reviewer: Option<&str>,
) -> Result<(), String> {
    let entry = available(engine).ok_or_else(|| format!("{engine} is not available yet"))?;
    if engine != "claude-api" {
        return Ok(());
    }
    let models: Vec<&str> = entry["models"]
        .as_array()
        .map(|m| m.iter().filter_map(|x| x["id"].as_str()).collect())
        .unwrap_or_default();
    let (Some(implementer), Some(reviewer)) = (implementer, reviewer) else {
        return Err("choose a model for implementing and one for reviewing".into());
    };
    for model in [implementer, reviewer] {
        if !models.contains(&model) {
            return Err(format!("{model} is not one of the offered models"));
        }
    }
    if implementer == reviewer {
        return Err("the reviewer must run on a different model from the implementer".into());
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------
// Claude Code

#[derive(Debug, Clone, Default, Serialize)]
pub struct ClaudeCode {
    pub installed: bool,
    pub path: Option<String>,
    pub version: Option<String>,
    /// Claude Code's own interactive sign-in, for information; runs use the kept token.
    pub logged_in: Option<bool>,
    pub auth_method: Option<String>,
    pub subscription: Option<String>,
}

/// Where Claude Code may be. `PHYSGATE_DESKTOP_CLAUDE` names the one place to look, for a
/// trial run against a stand-in.
fn candidates() -> Vec<PathBuf> {
    if let Some(path) = crate::config::switch("PHYSGATE_DESKTOP_CLAUDE") {
        return vec![PathBuf::from(path)];
    }
    let home = home();
    let mut found = vec![
        home.join(".local/bin/claude"),
        PathBuf::from("/opt/homebrew/bin/claude"),
        PathBuf::from("/usr/local/bin/claude"),
        home.join(".claude/local/claude"),
        home.join(".npm-global/bin/claude"),
    ];
    // An app opened from Finder has a bare PATH; a login shell knows the user's.
    if let Some(out) = run(Command::new("/bin/zsh").args(["-lc", "command -v claude"])) {
        if let Some(line) = out.lines().last() {
            found.push(PathBuf::from(line.trim()));
        }
    }
    found
}

/// Run a short command and return its standard output, or `None` if it fails or hangs.
fn run(command: &mut Command) -> Option<String> {
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                let mut out = String::new();
                child.stdout.take()?.read_to_string(&mut out).ok()?;
                return status.success().then_some(out);
            }
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(50)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    }
}

pub fn detect() -> ClaudeCode {
    let Some(path) = candidates().into_iter().find(|p| p.is_file()) else {
        return ClaudeCode::default();
    };
    let version = run(Command::new(&path).arg("--version"))
        .and_then(|out| out.lines().next().map(|l| l.trim().to_string()));
    let status: Option<serde_json::Value> =
        run(Command::new(&path).args(["auth", "status", "--json"]))
            .and_then(|out| serde_json::from_str(&out).ok());
    let text = |key: &str| {
        status
            .as_ref()
            .and_then(|s| s[key].as_str())
            .map(ToString::to_string)
    };
    ClaudeCode {
        installed: true,
        path: Some(path.display().to_string()),
        version,
        logged_in: status.as_ref().and_then(|s| s["loggedIn"].as_bool()),
        auth_method: text("authMethod"),
        subscription: text("subscriptionType"),
    }
}

/// Write a small script into `folder` and open it in Terminal, where the person sees every
/// line run. The app itself downloads nothing.
pub fn open_in_terminal(folder: &Path, name: &str, script: &str) -> Result<(), String> {
    fs::create_dir_all(folder).map_err(|e| e.to_string())?;
    let path = folder.join(name);
    fs::write(&path, script).map_err(|e| e.to_string())?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())?;
    Command::new("/usr/bin/open")
        .args(["-a", "Terminal"])
        .arg(&path)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("Terminal could not be opened: {e}"))
}

pub fn install_script() -> String {
    format!(
        "#!/bin/zsh\n\
         echo 'Installing Claude Code with its official installer:'\n\
         echo '  {INSTALL_COMMAND}'\n\
         echo\n\
         {INSTALL_COMMAND}\n\
         echo\n\
         echo 'When it says it is done, go back to the physgate app and choose Check Again.'\n"
    )
}

pub fn sign_in_script(claude: &str) -> String {
    format!(
        "#!/bin/zsh\n\
         echo 'Signing Claude Code in for physgate runs.'\n\
         echo 'Your browser opens; sign in there. Then copy the token printed here,'\n\
         echo 'paste it into the physgate app, and close this window.'\n\
         echo\n\
         '{}' setup-token\n",
        claude.replace('\'', r"'\''")
    )
}

// ---------------------------------------------------------------------------------------
// Signing in for runs: `claude setup-token` in a pseudo-terminal

/// What the page may know about a sign-in: its phase and its output with the token removed.
#[derive(Debug, Clone, Default, Serialize)]
pub struct SignInView {
    /// `idle`, `running`, `stored` or `failed`.
    pub phase: &'static str,
    pub lines: Vec<String>,
    pub message: Option<String>,
}

#[derive(Default)]
struct SignInState {
    view: SignInView,
    input: Option<File>,
    child: Option<Child>,
}

#[derive(Default, Clone)]
pub struct SignIn(Arc<Mutex<SignInState>>);

/// What replaces the token wherever output is shown.
const KEPT: &str = "[kept in the Keychain]";

fn locked(state: &Mutex<SignInState>) -> MutexGuard<'_, SignInState> {
    state.lock().unwrap_or_else(PoisonError::into_inner)
}

impl SignIn {
    pub fn view(&self) -> SignInView {
        let mut view = locked(&self.0).view.clone();
        if view.phase.is_empty() {
            view.phase = "idle";
        }
        view
    }

    /// Start `claude setup-token` in a pseudo-terminal of its own. Its output is read here:
    /// the token goes straight to the Keychain and is cut from everything shown.
    pub fn start(&self, claude: &Path) -> Result<SignInView, String> {
        {
            let state = locked(&self.0);
            if state.view.phase == "running" {
                return Ok(state.view.clone());
            }
        }
        let (master, slave) =
            open_pty().map_err(|e| format!("no terminal for the sign-in: {e}"))?;
        let mut command = Command::new(claude);
        command
            .arg("setup-token")
            .env("TERM", "xterm-256color")
            .stdin(Stdio::from(slave.try_clone().map_err(|e| e.to_string())?))
            .stdout(Stdio::from(slave.try_clone().map_err(|e| e.to_string())?))
            .stderr(Stdio::from(slave));
        // SAFETY: only async-signal-safe calls between fork and exec: a new session, and the
        // pseudo-terminal (already standard input) made its controlling terminal.
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 || libc::ioctl(0, libc::TIOCSCTTY.into(), 0) == -1 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let child = command
            .spawn()
            .map_err(|e| format!("Claude Code could not be started: {e}"))?;
        drop(command); // the parent's copies of the terminal's other end
        let reader = File::from(master.try_clone().map_err(|e| e.to_string())?);
        {
            let mut state = locked(&self.0);
            state.view = SignInView {
                phase: "running",
                lines: Vec::new(),
                message: None,
            };
            state.input = Some(File::from(master));
            state.child = Some(child);
        }
        let shared = self.clone();
        thread::spawn(move || shared.read(reader));
        Ok(self.view())
    }

    fn read(&self, mut reader: File) {
        let mut raw = String::new();
        let mut buffer = [0u8; 4096];
        let mut stored = false;
        loop {
            let n = reader.read(&mut buffer).unwrap_or(0);
            let ended = n == 0;
            raw.push_str(&String::from_utf8_lossy(&buffer[..n]));
            let clean = strip_terminal_codes(&raw);
            if !stored {
                if let Some(token) = find_token(&clean, ended) {
                    let result = keychain::store(Secret::SubscriptionToken, token);
                    stored = true;
                    let mut state = locked(&self.0);
                    match result {
                        Ok(()) => {
                            state.view.phase = "stored";
                            state.view.message = Some("The token is kept in the Keychain.".into());
                        }
                        Err(problem) => {
                            state.view.phase = "failed";
                            state.view.message = Some(problem);
                        }
                    }
                }
            }
            locked(&self.0).view.lines = shown_lines(&clean);
            if ended {
                break;
            }
        }
        raw.clear();
        let mut state = locked(&self.0);
        if let Some(mut child) = state.child.take() {
            let _ = child.wait();
        }
        state.input = None;
        if state.view.phase == "running" {
            state.view.phase = "failed";
            state.view.message = Some(
                "The sign-in ended without a token. Try again, or sign in in Terminal instead."
                    .into(),
            );
        }
    }

    /// Press Return in the sign-in, for a prompt that waits for it.
    pub fn press_return(&self) {
        if let Some(input) = locked(&self.0).input.as_mut() {
            let _ = input.write_all(b"\r");
        }
    }

    pub fn cancel(&self) {
        let mut state = locked(&self.0);
        if let Some(child) = state.child.as_mut() {
            let _ = child.kill();
        }
        if state.view.phase == "running" {
            state.view.phase = "idle";
            state.view.message = Some("The sign-in was stopped.".into());
        }
    }
}

fn open_pty() -> io::Result<(OwnedFd, OwnedFd)> {
    let mut master = 0;
    let mut slave = 0;
    // Wide, so a long token is never wrapped across lines.
    let mut size = libc::winsize {
        ws_row: 40,
        ws_col: 400,
        ws_xpixel: 0,
        ws_ypixel: 0,
    };
    // SAFETY: openpty writes two descriptors it opened into the two integers given.
    let rc = unsafe {
        libc::openpty(
            &mut master,
            &mut slave,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut size,
        )
    };
    if rc != 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: both descriptors are new and owned by nothing else.
    Ok(unsafe { (OwnedFd::from_raw_fd(master), OwnedFd::from_raw_fd(slave)) })
}

fn token_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '-' || c == '_'
}

/// A complete token in the output: one followed by something else, or by the end of the
/// output once the program has finished.
pub fn find_token(text: &str, ended: bool) -> Option<&str> {
    let start = text.find("sk-ant-oat")?;
    let rest = &text[start..];
    let length = rest.find(|c: char| !token_char(c));
    match length {
        Some(n) => Some(&rest[..n]),
        None if ended => Some(rest),
        None => None,
    }
}

/// Every run that starts like a credential, replaced, partial ones included.
pub fn redact(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(start) = rest.find("sk-ant-") {
        out.push_str(&rest[..start]);
        let after = &rest[start..];
        let length = after.find(|c: char| !token_char(c)).unwrap_or(after.len());
        out.push_str(KEPT);
        rest = &after[length..];
    }
    out.push_str(rest);
    out
}

/// Terminal control sequences removed, so what is shown is the text a person would read.
pub fn strip_terminal_codes(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '\u{1b}' => match chars.next() {
                Some('[') => {
                    for d in chars.by_ref() {
                        if ('@'..='~').contains(&d) {
                            break;
                        }
                    }
                }
                Some(']') => {
                    while let Some(d) = chars.next() {
                        if d == '\u{7}' || (d == '\u{1b}' && chars.peek() == Some(&'\\')) {
                            if d == '\u{1b}' {
                                chars.next();
                            }
                            break;
                        }
                    }
                }
                _ => {}
            },
            '\r' => out.push('\n'),
            c if c.is_control() && c != '\n' && c != '\t' => {}
            c => out.push(c),
        }
    }
    out
}

/// The last lines of the output worth showing, with every credential cut out.
fn shown_lines(clean: &str) -> Vec<String> {
    let lines: Vec<String> = clean
        .lines()
        .map(str::trim_end)
        .filter(|l| !l.trim().is_empty())
        .map(redact)
        .collect();
    lines[lines.len().saturating_sub(30)..].to_vec()
}

// ---------------------------------------------------------------------------------------
// "Test key": the one request the app makes, and only when the operator asks

pub async fn test_api_key() -> Result<String, String> {
    let key = keychain::read(Secret::ApiKey)?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .build()
        .map_err(|_| "the request could not be prepared".to_string())?;
    let response = client
        .get("https://api.anthropic.com/v1/models?limit=1")
        .header("x-api-key", key)
        .header("anthropic-version", "2023-06-01")
        .send()
        .await
        .map_err(|_| "Anthropic could not be reached".to_string())?;
    let status = response.status().as_u16();
    Ok(match status {
        200 => "Anthropic accepted the key.".into(),
        401 => "Anthropic refused the key (401: not a valid key).".into(),
        403 => "Anthropic refused the key (403: not allowed).".into(),
        _ => format!("Anthropic answered {status}."),
    })
}

// ---------------------------------------------------------------------------------------
// What this Mac could run, for the local-model card (data only; nothing is downloaded)

#[derive(Debug, Clone, Serialize)]
pub struct Device {
    pub chip: String,
    pub memory_gb: f64,
    pub gpu_cores: Option<u32>,
    pub apple_silicon: bool,
    pub free_disk_gb: f64,
    pub models: Vec<Fit>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Fit {
    pub name: String,
    pub memory_gb: f64,
    pub disk_gb: f64,
    pub licence: String,
    pub source: String,
    pub fits: bool,
}

fn sysctl_string(name: &str) -> Option<String> {
    let name = std::ffi::CString::new(name).ok()?;
    let mut size = 0usize;
    // SAFETY: the first call asks only for the size; the second fills a buffer of that size.
    unsafe {
        if libc::sysctlbyname(
            name.as_ptr(),
            std::ptr::null_mut(),
            &mut size,
            std::ptr::null_mut(),
            0,
        ) != 0
        {
            return None;
        }
        let mut buffer = vec![0u8; size];
        if libc::sysctlbyname(
            name.as_ptr(),
            buffer.as_mut_ptr().cast(),
            &mut size,
            std::ptr::null_mut(),
            0,
        ) != 0
        {
            return None;
        }
        buffer.truncate(size.saturating_sub(1));
        String::from_utf8(buffer).ok()
    }
}

fn sysctl_u64(name: &str) -> Option<u64> {
    let name = std::ffi::CString::new(name).ok()?;
    let mut value = 0u64;
    let mut size = std::mem::size_of::<u64>();
    // SAFETY: the value is a 64-bit integer, written into one of that size.
    let rc = unsafe {
        libc::sysctlbyname(
            name.as_ptr(),
            (&raw mut value).cast(),
            &mut size,
            std::ptr::null_mut(),
            0,
        )
    };
    (rc == 0).then_some(value)
}

fn free_disk_bytes(path: &Path) -> Option<u64> {
    let path = std::ffi::CString::new(path.as_os_str().as_encoded_bytes()).ok()?;
    // SAFETY: statfs fills the zeroed struct given for the path given.
    let mut stats: libc::statfs = unsafe { std::mem::zeroed() };
    let rc = unsafe { libc::statfs(path.as_ptr(), &mut stats) };
    (rc == 0).then(|| stats.f_bavail * u64::from(stats.f_bsize))
}

fn gpu_cores() -> Option<u32> {
    let out = run(Command::new("/usr/sbin/system_profiler").args(["SPDisplaysDataType", "-json"]))?;
    let value: serde_json::Value = serde_json::from_str(&out).ok()?;
    value["SPDisplaysDataType"]
        .as_array()?
        .iter()
        .find_map(|gpu| gpu["sppci_cores"].as_str()?.parse().ok())
}

#[allow(clippy::cast_precision_loss)] // sizes in GB, shown to one decimal
pub fn device() -> Device {
    let gb = |bytes: u64| bytes as f64 / 1_073_741_824.0;
    let chip = sysctl_string("machdep.cpu.brand_string").unwrap_or_else(|| "unknown".into());
    let memory_gb = sysctl_u64("hw.memsize").map_or(0.0, gb);
    let free_disk_gb = free_disk_bytes(&home()).map_or(0.0, gb);
    let models = catalogue()["engines"]
        .as_array()
        .and_then(|engines| engines.iter().find(|e| e["id"] == "local"))
        .and_then(|local| local["local_models"].as_array().cloned())
        .unwrap_or_default()
        .iter()
        .map(|m| {
            let memory = m["memory_gb"].as_f64().unwrap_or(f64::MAX);
            let disk = m["disk_gb"].as_f64().unwrap_or(f64::MAX);
            Fit {
                name: m["name"].as_str().unwrap_or_default().into(),
                memory_gb: memory,
                disk_gb: disk,
                licence: m["licence"].as_str().unwrap_or_default().into(),
                source: m["source"].as_str().unwrap_or_default().into(),
                // Leave a quarter of memory to everything else, and the disk must hold it.
                fits: memory <= memory_gb * 0.75 && disk <= free_disk_gb,
            }
        })
        .collect();
    Device {
        apple_silicon: chip.starts_with("Apple"),
        chip,
        memory_gb,
        gpu_cores: gpu_cores(),
        free_disk_gb,
        models,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn two_engines_work_today_and_the_rest_are_shown_as_not_yet() {
        let catalogue = catalogue();
        let engines = catalogue["engines"].as_array().unwrap();
        let available: Vec<&str> = engines
            .iter()
            .filter(|e| e["status"] == "available")
            .filter_map(|e| e["id"].as_str())
            .collect();
        assert_eq!(available, ["claude-code", "claude-api"]);
        assert!(engines
            .iter()
            .all(|e| e["status"] == "available" || e["status"] == "not-yet"));
        let api = &engines[1];
        assert_ne!(api["defaults"]["implementer"], api["defaults"]["reviewer"]);
    }

    #[test]
    fn an_engine_choice_is_checked() {
        assert!(check_choice("claude-code", None, None).is_ok());
        assert!(check_choice(
            "claude-api",
            Some("claude-opus-5-5"),
            Some("claude-sonnet-5")
        )
        .is_ok());
        let same = check_choice(
            "claude-api",
            Some("claude-sonnet-5"),
            Some("claude-sonnet-5"),
        );
        assert!(same.unwrap_err().contains("different model"));
        assert!(check_choice("claude-api", Some("claude-opus-5-5"), None).is_err());
        assert!(check_choice("claude-api", Some("gpt-x"), Some("claude-sonnet-5")).is_err());
        assert!(check_choice("local", None, None)
            .unwrap_err()
            .contains("not available yet"));
        assert!(check_choice("openai", None, None).is_err());
    }

    #[test]
    fn the_token_is_found_only_once_it_is_complete() {
        let token = format!("sk-ant-oat01-{}", "x".repeat(60));
        let partial = format!("Your token:\n{}", &token[..30]);
        assert_eq!(find_token(&partial, false), None, "still arriving");
        let whole = format!("Your token:\n{token}\nStore it safely.");
        assert_eq!(find_token(&whole, false), Some(token.as_str()));
        let at_end = format!("Your token:\n{token}");
        assert_eq!(find_token(&at_end, false), None);
        assert_eq!(find_token(&at_end, true), Some(token.as_str()));
        assert_eq!(find_token("no token here", true), None);
    }

    #[test]
    fn every_credential_is_cut_from_what_is_shown() {
        let token = format!("sk-ant-oat01-{}", "y".repeat(60));
        let shown = redact(&format!("ok {token} and sk-ant-api03-zzzz and sk-ant-o"));
        assert!(!shown.contains("sk-ant-"), "{shown}");
        assert_eq!(shown.matches(KEPT).count(), 3);
        let lines = shown_lines(&format!("one\n\n{token}\n"));
        assert_eq!(lines, ["one", KEPT]);
    }

    #[test]
    fn terminal_codes_are_removed() {
        let raw = "\u{1b}[1;32mSigned\u{1b}[0m in\r\n\u{1b}]8;;https://x\u{7}link\u{1b}]8;;\u{7}\u{1b}[?25l";
        assert_eq!(strip_terminal_codes(raw), "Signed in\n\nlink");
    }

    #[test]
    fn the_scripts_run_only_what_they_show() {
        let install = install_script();
        assert!(install.contains(INSTALL_COMMAND));
        assert!(install.starts_with("#!/bin/zsh\n"));
        let sign_in = sign_in_script("/Users/me/it's/claude");
        assert!(sign_in.contains(r"'/Users/me/it'\''s/claude' setup-token"));
    }

    #[test]
    fn a_sign_in_with_a_stand_in_keeps_the_token_and_shows_none_of_it() {
        let dir = crate::testdir::TestDir::new("sign-in");
        // The Keychain service under test is the test process's own (see keychain::service).
        let token = format!("sk-ant-oat01-standin-{}", "q".repeat(48));
        let script = dir.path().join("claude");
        fs::write(
            &script,
            format!(
                "#!/bin/sh\n[ -t 0 ] || {{ echo 'not a terminal'; exit 3; }}\n\
                 printf '\\033[1mOpening your browser\\033[0m\\r\\n'\n\
                 printf 'Your token:\\r\\n{token}\\r\\nDone.\\r\\n'\n"
            ),
        )
        .unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o700)).unwrap();
        keychain::forget(Secret::SubscriptionToken);
        let sign_in = SignIn::default();
        sign_in.start(&script).unwrap();
        let deadline = Instant::now() + Duration::from_secs(10);
        while sign_in.view().phase == "running" && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(50));
        }
        let view = sign_in.view();
        assert_eq!(view.phase, "stored", "{view:?}");
        let shown = serde_json::to_string(&view).unwrap();
        assert!(!shown.contains("sk-ant-"), "{shown}");
        assert!(
            shown.contains("Opening your browser"),
            "it ran in a terminal: {shown}"
        );
        assert_eq!(keychain::read(Secret::SubscriptionToken).unwrap(), token);
        keychain::forget(Secret::SubscriptionToken);
    }
}
