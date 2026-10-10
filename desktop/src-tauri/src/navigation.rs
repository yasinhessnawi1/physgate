//! Where the window may go, decided before every navigation the webview starts.
//!
//! Two kinds of page are allowed, and nothing else:
//!
//! - **The running server's origin**: scheme, host and port compared whole, as the URL
//!   standard serialises them, never as a prefix. The origin is the one the shell's own
//!   child announced on its standard output and that passed the loopback check; a page
//!   cannot set it.
//! - **The app's own page**, and only at the exact address the shell itself just sent the
//!   window to. The shell issues a one-use ticket for that address before navigating, and
//!   the address carries an unguessable one-use value (`?t=…`) that only the shell knows.
//!   A navigation a page starts (a link, a script, a redirect, a frame) cannot name it, so
//!   a served page can never show the app's own pages, in the window or in a frame.
//!   Tickets are honoured only while no server is trusted (the shell stops the server
//!   before it shows one of its own pages), and trusting a server clears them all. The
//!   one exception is the window's very first load, which has a single ticket for exactly
//!   `tauri://localhost`, used up by that load and gone once a server is trusted.
//!
//! Everything else is refused, and the window stays where it is.

use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard, PoisonError};
use std::time::{SystemTime, UNIX_EPOCH};

use tauri::Url;

/// What the gate decided about one navigation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Decision {
    /// The app's own page, at the address the shell sent it to.
    OwnPage,
    /// A page of the running server.
    Served,
    /// Anything else.
    Refused,
}

#[derive(Debug, Default)]
pub struct Gate {
    origin: Mutex<Option<String>>,
    /// Addresses of the app's own page the shell has sent the window to and the webview has
    /// not yet asked about. A few may be pending at once (a start-up page, then a status).
    tickets: Mutex<Vec<String>>,
}

/// The most tickets pending at once; the oldest goes first.
const MOST_TICKETS: usize = 8;

fn locked<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

/// The window's first address, as the webview reports it.
pub const FIRST_LOAD: &str = "tauri://localhost";

/// 128 bits no page can predict: from the process's randomly keyed hasher, a counter and
/// the clock.
fn unguessable() -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let mut parts = [0u64; 2];
    for part in &mut parts {
        let mut hasher = RandomState::new().build_hasher();
        hasher.write_u64(COUNTER.fetch_add(1, Ordering::Relaxed));
        hasher.write_u128(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_or(0, |d| d.as_nanos()),
        );
        *part = hasher.finish();
    }
    format!("{:016x}{:016x}", parts[0], parts[1])
}

impl Gate {
    /// Trust the origin of `url`, the address the shell's own server announced; `None` trusts
    /// none. Trusting a server clears every pending ticket: none outlives the app's own page.
    pub fn serve(&self, url: Option<&Url>) {
        *locked(&self.origin) = url.map(|u| u.origin().ascii_serialization());
        if url.is_some() {
            locked(&self.tickets).clear();
        }
    }

    /// The single ticket for the window's first load.
    pub fn first_load(&self) {
        let first = Url::parse(FIRST_LOAD).expect("the first address parses");
        locked(&self.tickets).push(first.as_str().to_string());
    }

    /// The trusted origin, if a server is running.
    pub fn origin(&self) -> Option<String> {
        locked(&self.origin).clone()
    }

    /// Allow the window to go to the app's own page at `url` once: returns the address to send
    /// it to, which is `url` with a one-use value only the shell knows.
    pub fn issue(&self, url: &Url) -> Url {
        let mut ticketed = url.clone();
        ticketed.set_query(Some(&format!("t={}", unguessable())));
        let mut tickets = locked(&self.tickets);
        if tickets.len() == MOST_TICKETS {
            tickets.remove(0);
        }
        tickets.push(ticketed.as_str().to_string());
        ticketed
    }

    /// Decide one navigation. A ticket that matches is used up.
    pub fn decide(&self, url: &Url) -> Decision {
        if url.scheme() == "tauri" {
            if locked(&self.origin).is_some() {
                // While a server is trusted the window shows its page; the app's own pages
                // are reached only after the shell stops it.
                return Decision::Refused;
            }
            let mut tickets = locked(&self.tickets);
            if let Some(i) = tickets.iter().position(|t| t == url.as_str()) {
                tickets.remove(i);
                return Decision::OwnPage;
            }
            return Decision::Refused;
        }
        let served = locked(&self.origin)
            .as_deref()
            .is_some_and(|origin| url.origin().ascii_serialization() == origin);
        if served {
            Decision::Served
        } else {
            Decision::Refused
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(text: &str) -> Url {
        Url::parse(text).unwrap()
    }

    fn serving(port: u16) -> Gate {
        let gate = Gate::default();
        gate.serve(Some(&url(&format!("http://127.0.0.1:{port}/"))));
        gate
    }

    #[test]
    fn only_the_running_servers_exact_origin_is_served() {
        let gate = serving(52011);
        for allowed in [
            "http://127.0.0.1:52011/",
            "http://127.0.0.1:52011/#/runs/run-on",
            "http://127.0.0.1:52011/api/runs?x=1",
        ] {
            assert_eq!(gate.decide(&url(allowed)), Decision::Served, "{allowed}");
        }
        for refused in [
            "http://127.0.0.1:52012/",
            "http://127.0.0.1:5201/",
            // Begins with the trusted origin's text: only a whole comparison refuses these.
            "http://127.0.0.1:52011@evil.example/",
            "http://127.0.0.1:52011@127.0.0.1:52012/",
            "http://localhost:52011/",
            "https://127.0.0.1:52011/",
            "http://127.0.0.1.evil.example:52011/",
            "http://evil.example/http://127.0.0.1:52011/",
            "http://user@127.0.0.1.evil.example:52011/",
            "https://example.com/",
            "file:///etc/passwd",
            "about:blank",
            "data:text/html,<p>x</p>",
        ] {
            // Every case must parse, or it would never reach the gate and prove nothing.
            let parsed = Url::parse(refused).expect(refused);
            assert_eq!(gate.decide(&parsed), Decision::Refused, "{refused}");
        }
    }

    #[test]
    fn with_no_server_running_nothing_is_served() {
        let gate = Gate::default();
        assert_eq!(
            gate.decide(&url("http://127.0.0.1:52011/")),
            Decision::Refused
        );
        let gate = serving(52011);
        gate.serve(None);
        assert_eq!(
            gate.decide(&url("http://127.0.0.1:52011/")),
            Decision::Refused
        );
    }

    #[test]
    fn the_apps_own_page_needs_the_shells_ticket_for_that_exact_address() {
        let gate = Gate::default();
        let page = url("tauri://localhost/index.html#%7B%22title%22%3A%22No%20runs%22%7D");
        // A page writing its own text into the app's page: no ticket, refused.
        assert_eq!(gate.decide(&page), Decision::Refused);
        let ticketed = gate.issue(&page);
        assert_ne!(ticketed, page, "the address carries the one-use value");
        assert_eq!(ticketed.fragment(), page.fragment());
        // Without the value, or with another fragment or page, it is refused.
        assert_eq!(gate.decide(&page), Decision::Refused, "the bare address");
        let mut spoof = ticketed.clone();
        spoof.set_fragment(Some("%7B%22title%22%3A%22Run%20this%22%7D"));
        assert_eq!(gate.decide(&spoof), Decision::Refused, "another fragment");
        let mut other = ticketed.clone();
        other.set_path("/onboarding.html");
        assert_eq!(gate.decide(&other), Decision::Refused, "another page");
        assert_eq!(gate.decide(&ticketed), Decision::OwnPage);
        assert_eq!(gate.decide(&ticketed), Decision::Refused, "used once");
    }

    #[test]
    fn every_ticketed_address_is_different() {
        let gate = Gate::default();
        let page = url("tauri://localhost/onboarding.html#engine");
        let first = gate.issue(&page);
        let second = gate.issue(&page);
        assert_ne!(first, second);
        assert_eq!(first.query().unwrap().len(), "t=".len() + 32);
    }

    #[test]
    fn there_is_one_first_load_ticket_for_exactly_the_first_address() {
        let gate = Gate::default();
        gate.first_load();
        for other in ["tauri://localhost/", "tauri://localhost/index.html"] {
            assert_eq!(gate.decide(&url(other)), Decision::Refused, "{other}");
        }
        assert_eq!(gate.decide(&url(FIRST_LOAD)), Decision::OwnPage);
        assert_eq!(
            gate.decide(&url(FIRST_LOAD)),
            Decision::Refused,
            "used once"
        );
    }

    #[test]
    fn no_ticket_outlives_the_start_and_none_is_honoured_while_a_server_is_trusted() {
        let gate = Gate::default();
        gate.first_load();
        let page = url("tauri://localhost/index.html#starting");
        let ticketed = gate.issue(&page);
        gate.serve(Some(&url("http://127.0.0.1:52011/")));
        assert_eq!(gate.decide(&url(FIRST_LOAD)), Decision::Refused, "cleared");
        assert_eq!(gate.decide(&ticketed), Decision::Refused, "cleared");
        // A ticket issued while a server is trusted is not honoured either.
        let late = gate.issue(&page);
        assert_eq!(gate.decide(&late), Decision::Refused);
        gate.serve(None);
        assert_eq!(
            gate.decide(&late),
            Decision::OwnPage,
            "once the server is stopped"
        );
    }

    #[test]
    fn pending_tickets_are_each_used_once_and_only_the_newest_eight_are_kept() {
        let gate = Gate::default();
        let pages: Vec<Url> = (0..10)
            .map(|i| gate.issue(&url(&format!("tauri://localhost/index.html#{i}"))))
            .collect();
        assert_eq!(
            gate.decide(&pages[0]),
            Decision::Refused,
            "dropped as the oldest"
        );
        assert_eq!(
            gate.decide(&pages[1]),
            Decision::Refused,
            "dropped as the oldest"
        );
        for page in &pages[2..] {
            assert_eq!(gate.decide(page), Decision::OwnPage);
            assert_eq!(gate.decide(page), Decision::Refused);
        }
    }

    #[test]
    fn the_apps_own_pages_may_not_be_framed() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let csp = config["app"]["security"]["csp"].as_str().unwrap();
        assert!(csp.contains("frame-ancestors 'none'"), "{csp}");
    }
}
