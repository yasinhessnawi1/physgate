//! Stopping the server when the app is told to stop by a signal.
//!
//! A quit from the menu ends the event loop, which stops the server. A signal (`kill`, a
//! logout, Ctrl-C in a terminal) would end the process without that, leaving `physgate ui`
//! serving. So the stopping signals are caught: the handler only sets a flag (all a signal
//! handler may safely do), and a thread that watches the flag stops the server and exits.
//! `kill -9` cannot be caught; the pid file covers it at the next start.

use std::sync::atomic::{AtomicBool, Ordering};

static REQUESTED: AtomicBool = AtomicBool::new(false);

/// The signals that ask a process to stop and can be caught.
pub const STOPPING: [libc::c_int; 3] = [libc::SIGTERM, libc::SIGINT, libc::SIGHUP];

extern "C" fn on_signal(_: libc::c_int) {
    REQUESTED.store(true, Ordering::SeqCst);
}

/// Catch the stopping signals from now on.
pub fn install() {
    for signal in STOPPING {
        // SAFETY: the handler only stores to an atomic, which is async-signal-safe.
        unsafe {
            libc::signal(signal, on_signal as libc::sighandler_t);
        }
    }
}

/// Whether a stopping signal has arrived.
pub fn requested() -> bool {
    REQUESTED.load(Ordering::SeqCst)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Run in a child copy of the test binary (see below), never in the shared test process:
    /// if the handler were not installed, the signal would end whatever process raises it.
    #[test]
    #[ignore = "run only in a child process, by the test below"]
    fn child_catches_a_stopping_signal() {
        install();
        for signal in STOPPING {
            // SAFETY: raising a signal this process now catches.
            unsafe {
                libc::raise(signal);
            }
        }
        assert!(
            requested(),
            "the signal was caught and the process is still here"
        );
    }

    #[test]
    fn a_stopping_signal_is_caught_and_noted_rather_than_ending_the_process() {
        let out = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--ignored",
                "--exact",
                "signals::tests::child_catches_a_stopping_signal",
                "--test-threads=1",
            ])
            .output()
            .unwrap();
        let said = String::from_utf8_lossy(&out.stdout);
        assert!(
            out.status.success() && said.contains("1 passed"),
            "the child did not survive its own signals: {:?}\n{said}",
            out.status
        );
    }
}
