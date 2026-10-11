//! Starting and stopping `physgate ui`: the operator server, run from a checkout.
//!
//! The shell runs the checkout's own entry point (`.venv/bin/physgate`), not `uv run`,
//! so starting the app never syncs dependencies and never reaches the network. It
//! always binds `127.0.0.1` on a free port the system picks, so it never collides with
//! a server someone started by hand. The server announces itself with one JSON object
//! on standard output; the shell shows the page at that object's `url`, and only if it
//! is a loopback address. Everything the server writes to standard error, its request
//! log and its refusal included, goes to a log file the menu can open.

use std::fs::{self, File};
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use serde::Deserialize;
use tauri::Url;

use crate::config::Settings;

/// How long the server may take to announce its address before the start counts as failed.
const START_TIMEOUT: Duration = Duration::from_secs(90);

/// How long a stopping server gets to finish after an interrupt before it is killed.
const STOP_GRACE: Duration = Duration::from_secs(3);

/// The entry point inside a checkout.
pub fn entry_point(checkout: &Path) -> PathBuf {
    checkout.join(".venv/bin/physgate")
}

/// The arguments `physgate` is given: loopback, any free port, and the folders named.
pub fn arguments(settings: &Settings) -> Vec<String> {
    let mut args: Vec<String> = ["ui", "--bind", "127.0.0.1", "--port", "0"]
        .iter()
        .map(ToString::to_string)
        .collect();
    let flags = [
        ("--root", &settings.run_folders),
        ("--held-out", &settings.held_out),
        ("--answer-key", &settings.answer_keys),
    ];
    for (flag, paths) in flags {
        for path in paths {
            args.push(flag.to_string());
            args.push(path.display().to_string());
        }
    }
    args
}

/// What the server prints once it listens.
#[derive(Debug, Deserialize)]
struct Announcement {
    url: String,
}

/// The server's address, read from what it printed, if what it printed so far is complete.
///
/// Refuses anything but `http://127.0.0.1:<port>/`: the shell shows the page at this
/// address, so a server that announced another host would not be shown at all.
pub fn announced_url(printed: &str) -> Option<Result<Url, String>> {
    let announcement: Announcement = serde_json::from_str(printed).ok()?;
    Some(loopback_url(&announcement.url))
}

fn loopback_url(text: &str) -> Result<Url, String> {
    let url = Url::parse(text).map_err(|e| format!("the server announced {text:?}: {e}"))?;
    let loopback = url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port().is_some()
        && url.path() == "/";
    if loopback {
        Ok(url)
    } else {
        Err(format!(
            "the server announced {text:?}, which is not a loopback address"
        ))
    }
}

/// Why the server refused to start: the last JSON object in its log, as it wrote it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refusal {
    pub error: String,
    pub context: Vec<(String, String)>,
}

/// The refusal the server wrote last in its log, if there is one.
pub fn refusal_in(log: &str) -> Option<Refusal> {
    log.lines().rev().find_map(|line| {
        let value: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
        let object = value.as_object()?;
        let error = object.get("error")?.as_str()?.to_string();
        let context = object
            .iter()
            .filter(|(key, _)| key.as_str() != "error")
            .map(|(key, value)| {
                let text = value
                    .as_str()
                    .map_or_else(|| value.to_string(), ToString::to_string);
                (key.clone(), text)
            })
            .collect();
        Some(Refusal { error, context })
    })
}

/// The last `n` lines of a log, for a page that says the server stopped.
pub fn tail(log: &str, n: usize) -> String {
    let lines: Vec<&str> = log.lines().collect();
    lines[lines.len().saturating_sub(n)..].join("\n")
}

/// Why a start did not give an address.
#[derive(Debug)]
pub enum StartError {
    /// The checkout has no installed entry point.
    NoEntryPoint(PathBuf),
    /// The server exited before announcing itself: its refusal if it wrote one, and its log's end.
    Refused(Option<Refusal>, String),
    /// Something else went wrong: the program could not run, or it announced no usable address.
    Failed(String),
}

/// A running server, stopped when dropped.
///
/// While it runs, its pid and program are in a pid file. If the app is killed outright
/// (Force Quit, `kill -9`, a crash), the next start reads that file and stops the server it
/// left, so no `physgate ui` keeps serving after the app is gone.
pub struct Server {
    child: Child,
    url: Url,
    pid_file: PathBuf,
}

impl Server {
    /// Start `physgate ui` for `settings`, writing its standard error to `log` and its pid
    /// to `pid_file`.
    pub fn start(settings: &Settings, log: &Path, pid_file: &Path) -> Result<Self, StartError> {
        let program = entry_point(&settings.checkout);
        if !program.is_file() {
            return Err(StartError::NoEntryPoint(program));
        }
        if let Some(parent) = log.parent() {
            fs::create_dir_all(parent).map_err(|e| StartError::Failed(e.to_string()))?;
        }
        let errors = File::create(log).map_err(|e| StartError::Failed(e.to_string()))?;
        let mut child = Command::new(&program)
            .args(arguments(settings))
            .current_dir(&settings.checkout)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(errors)
            .spawn()
            .map_err(|e| StartError::Failed(format!("{} could not run: {e}", program.display())))?;
        let _ = fs::write(pid_file, format!("{}\n{}\n", child.id(), program.display()));
        let given_up = |child: &mut Child| {
            stop_child(child);
            let _ = fs::remove_file(pid_file);
        };
        let stdout = child.stdout.take().expect("standard output is piped");
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || read_announcement(stdout, &sender));
        let started = Instant::now();
        loop {
            match receiver.recv_timeout(Duration::from_millis(100)) {
                Ok(Ok(url)) => {
                    return Ok(Self {
                        child,
                        url,
                        pid_file: pid_file.to_path_buf(),
                    })
                }
                Ok(Err(reason)) => {
                    given_up(&mut child);
                    return Err(StartError::Failed(reason));
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                // Standard output closed without an address: wait for the exit below.
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    thread::sleep(Duration::from_millis(100));
                }
            }
            if let Ok(Some(_)) = child.try_wait() {
                given_up(&mut child);
                let text = fs::read_to_string(log).unwrap_or_default();
                return Err(StartError::Refused(refusal_in(&text), tail(&text, 20)));
            }
            if started.elapsed() > START_TIMEOUT {
                given_up(&mut child);
                return Err(StartError::Failed(format!(
                    "the server did not announce an address within {} seconds",
                    START_TIMEOUT.as_secs()
                )));
            }
        }
    }

    pub fn url(&self) -> &Url {
        &self.url
    }

    /// Whether the server is still running.
    pub fn running(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        stop_child(&mut self.child);
        let _ = fs::remove_file(&self.pid_file);
    }
}

/// Stop a server an earlier run of the app left behind, if `pid_file` names one. Returns its
/// pid if one was stopped.
///
/// It is stopped only if that pid is still a `physgate ui` of the program the file names,
/// read from the process table, so a pid the system has since given to anything else is
/// left alone. The file is removed either way.
pub fn reap(pid_file: &Path) -> Option<i32> {
    let text = fs::read_to_string(pid_file).ok()?;
    let _ = fs::remove_file(pid_file);
    let mut lines = text.lines();
    let pid: i32 = lines.next()?.trim().parse().ok().filter(|p| *p > 1)?;
    let program = lines.next()?.trim().to_string();
    let command = Command::new("/bin/ps")
        .args(["-o", "command=", "-p", &pid.to_string()])
        .output()
        .ok()
        .filter(|out| out.status.success())
        .map(|out| String::from_utf8_lossy(&out.stdout).into_owned())?;
    let ours = !program.is_empty()
        && command.contains(&program)
        && command.split_whitespace().any(|word| word == "ui");
    if !ours {
        return None;
    }
    let alive = || {
        // SAFETY: signal 0 only asks whether the process exists.
        unsafe { libc::kill(pid, 0) == 0 }
    };
    // SAFETY: a pid checked above to be a `physgate ui` of the recorded program.
    unsafe {
        libc::kill(pid, libc::SIGINT);
    }
    let deadline = Instant::now() + STOP_GRACE;
    while alive() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(50));
    }
    if alive() {
        // SAFETY: as above.
        unsafe {
            libc::kill(pid, libc::SIGKILL);
        }
    }
    Some(pid)
}

/// Read standard output until it holds a complete announcement, then keep draining it.
fn read_announcement(stdout: impl Read, sender: &mpsc::Sender<Result<Url, String>>) {
    let mut reader = BufReader::new(stdout);
    let mut printed = String::new();
    let mut announced = false;
    let mut line = String::new();
    while matches!(reader.read_line(&mut line), Ok(n) if n > 0) {
        if !announced {
            printed.push_str(&line);
            if let Some(result) = announced_url(&printed) {
                announced = true;
                let _ = sender.send(result);
            }
        }
        line.clear();
    }
}

/// Interrupt the server the way Ctrl-C would, so it closes its socket; kill it if it lingers.
fn stop_child(child: &mut Child) {
    if !matches!(child.try_wait(), Ok(None)) {
        return;
    }
    if let Ok(pid) = i32::try_from(child.id()) {
        // SAFETY: `kill` with a pid this process spawned and has not yet reaped.
        unsafe {
            libc::kill(pid, libc::SIGINT);
        }
    }
    let deadline = Instant::now() + STOP_GRACE;
    while Instant::now() < deadline {
        if !matches!(child.try_wait(), Ok(None)) {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn the_server_is_always_asked_for_loopback_and_a_free_port() {
        let settings = Settings {
            run_folders: vec![PathBuf::from("/runs/a"), PathBuf::from("/runs b")],
            held_out: vec![PathBuf::from("/held")],
            answer_keys: vec![PathBuf::from("/keys")],
            ..Settings::default()
        };
        assert_eq!(
            arguments(&settings),
            [
                "ui",
                "--bind",
                "127.0.0.1",
                "--port",
                "0",
                "--root",
                "/runs/a",
                "--root",
                "/runs b",
                "--held-out",
                "/held",
                "--answer-key",
                "/keys"
            ]
        );
    }

    #[test]
    fn the_announcement_is_read_once_it_is_complete() {
        let printed = "{\n \"refused\": [],\n \"roots\": [\"/r\"],\n";
        assert!(announced_url(printed).is_none(), "not complete yet");
        let printed = format!("{printed} \"url\": \"http://127.0.0.1:52011/\"\n}}\n");
        let url = announced_url(&printed).unwrap().unwrap();
        assert_eq!(url.as_str(), "http://127.0.0.1:52011/");
    }

    #[test]
    fn an_announced_address_off_loopback_is_refused() {
        for url in [
            "http://0.0.0.0:8765/",
            "http://localhost:8765/",
            "http://192.168.1.2:8765/",
            "https://127.0.0.1:8765/",
            "http://127.0.0.1/",
            "http://127.0.0.1:8765/elsewhere",
            "http://[::1]:8765/",
        ] {
            let printed = format!("{{\"url\": \"{url}\"}}");
            assert!(announced_url(&printed).unwrap().is_err(), "{url} accepted");
        }
    }

    #[test]
    fn the_refusal_is_the_last_json_object_in_the_log() {
        let log = "Traceback? no\n\
            {\"error\": \"an older one\"}\n\
            {\"error\": \"the UI build is stale; build it with scripts/build-ui.sh\", \"ui\": \"/c/ui\"}\n";
        let refusal = refusal_in(log).unwrap();
        assert!(refusal.error.contains("scripts/build-ui.sh"));
        assert_eq!(
            refusal.context,
            vec![("ui".to_string(), "/c/ui".to_string())]
        );
        assert!(refusal_in("127.0.0.1 - - \"GET / HTTP/1.1\" 200 -\n").is_none());
    }

    #[test]
    fn the_tail_keeps_the_last_lines() {
        assert_eq!(tail("a\nb\nc\n", 2), "b\nc");
        assert_eq!(tail("a\n", 5), "a");
    }

    fn stand_in_server(dir: &Path) -> PathBuf {
        let bin = dir.join("checkout/.venv/bin");
        fs::create_dir_all(&bin).unwrap();
        let program = bin.join("physgate");
        fs::write(
            &program,
            "#!/bin/sh\nprintf '{\"url\": \"http://127.0.0.1:5555/\"}\\n'\nwhile :; do sleep 1; done\n",
        )
        .unwrap();
        fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).unwrap();
        program
    }

    fn alive(pid: i32) -> bool {
        // SAFETY: signal 0 only asks whether the process exists.
        unsafe { libc::kill(pid, 0) == 0 }
    }

    #[test]
    fn a_running_server_has_a_pid_file_that_goes_with_it() {
        let dir = crate::testdir::TestDir::new("pid-file");
        stand_in_server(dir.path());
        let settings = Settings {
            checkout: dir.path().join("checkout"),
            run_folders: vec![dir.path().to_path_buf()],
            ..Settings::default()
        };
        let pid_file = dir.path().join("server.pid");
        let server = Server::start(&settings, &dir.path().join("server.log"), &pid_file).unwrap();
        let text = fs::read_to_string(&pid_file).unwrap();
        let pid: i32 = text.lines().next().unwrap().parse().unwrap();
        assert!(text.contains(".venv/bin/physgate"));
        assert!(alive(pid));
        drop(server);
        assert!(!pid_file.exists(), "removed when the server stops");
    }

    #[test]
    fn a_server_left_by_a_killed_app_is_stopped_at_the_next_start() {
        let dir = crate::testdir::TestDir::new("reap");
        let program = stand_in_server(dir.path());
        // The server as a killed app would leave it: running, with only the pid file to find it.
        let mut left = Command::new(&program)
            .args(["ui", "--bind", "127.0.0.1"])
            .stdout(Stdio::null())
            .spawn()
            .unwrap();
        let pid = i32::try_from(left.id()).unwrap();
        let pid_file = dir.path().join("server.pid");
        fs::write(&pid_file, format!("{pid}\n{}\n", program.display())).unwrap();
        thread::sleep(Duration::from_millis(200));
        assert_eq!(reap(&pid_file), Some(pid));
        let deadline = Instant::now() + Duration::from_secs(5);
        while matches!(left.try_wait(), Ok(None)) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(50));
        }
        assert!(
            left.try_wait().unwrap().is_some(),
            "the left-over server was stopped"
        );
        assert!(!pid_file.exists());
    }

    #[test]
    fn a_pid_now_held_by_something_else_is_left_alone() {
        let dir = crate::testdir::TestDir::new("reap-other");
        let program = stand_in_server(dir.path());
        let mut other = Command::new("/bin/sleep").arg("30").spawn().unwrap();
        let pid = i32::try_from(other.id()).unwrap();
        let pid_file = dir.path().join("server.pid");
        fs::write(&pid_file, format!("{pid}\n{}\n", program.display())).unwrap();
        assert_eq!(reap(&pid_file), None);
        assert!(alive(pid), "not ours, not stopped");
        assert!(!pid_file.exists());
        let _ = other.kill();
        let _ = other.wait();
        fs::write(&pid_file, "not a pid\n").unwrap();
        assert_eq!(reap(&pid_file), None);
        assert_eq!(reap(&dir.path().join("absent.pid")), None);
    }

    #[test]
    fn a_checkout_without_an_environment_is_named() {
        let settings = Settings {
            checkout: PathBuf::from("/nowhere/at/all"),
            run_folders: vec![PathBuf::from("/runs")],
            ..Settings::default()
        };
        let log = std::env::temp_dir().join("physgate-desktop-test-unused.log");
        match Server::start(&settings, &log, &log.with_extension("pid")) {
            Err(StartError::NoEntryPoint(path)) => {
                assert_eq!(path, PathBuf::from("/nowhere/at/all/.venv/bin/physgate"));
            }
            _ => panic!("expected the missing entry point to be named"),
        }
    }
}
