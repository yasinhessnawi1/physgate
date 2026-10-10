//! Where the window may go, decided before every navigation the webview starts.
//!
//! Two kinds of page are allowed, and nothing else:
//!
//! - **The running server's origin**: scheme, host and port compared whole, as the URL
//!   standard serialises them, never as a prefix. The origin is the one the shell's own
//!   child announced on its standard output and that passed the loopback check; a page
//!   cannot set it.
//! - **The app's own page**, and only at the exact address the shell itself just sent the
//!   window to. The shell issues a one-use ticket for that address before navigating; a
//!   navigation the page starts (a link, a script, a redirect) has no ticket, so a served
//!   page can never dress itself up as the app's own status page by writing its own text
//!   into that page's address.
//!
//! Everything else is refused, and the window stays where it is.

use std::sync::{Mutex, MutexGuard, PoisonError};

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

impl Gate {
    /// Trust the origin of `url`, the address the shell's own server announced; `None` trusts none.
    pub fn serve(&self, url: Option<&Url>) {
        *locked(&self.origin) = url.map(|u| u.origin().ascii_serialization());
    }

    /// The trusted origin, if a server is running.
    pub fn origin(&self) -> Option<String> {
        locked(&self.origin).clone()
    }

    /// Allow the window to go to the app's own page at exactly `url`, once.
    pub fn issue(&self, url: &Url) {
        let mut tickets = locked(&self.tickets);
        if tickets.len() == MOST_TICKETS {
            tickets.remove(0);
        }
        tickets.push(url.as_str().to_string());
    }

    /// Decide one navigation. A ticket that matches is used up.
    pub fn decide(&self, url: &Url) -> Decision {
        if url.scheme() == "tauri" {
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
            "http://127.0.0.1:520110/",
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
            let Ok(parsed) = Url::parse(refused) else {
                continue; // a string that is not even a URL never reaches the gate
            };
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
        let gate = serving(52011);
        let page = url("tauri://localhost/index.html#%7B%22title%22%3A%22No%20run%20folders%22%7D");
        // A served page writing its own text into the app's page: no ticket, refused.
        assert_eq!(gate.decide(&page), Decision::Refused);
        gate.issue(&page);
        let spoof = url("tauri://localhost/index.html#%7B%22title%22%3A%22Run%20this%22%7D");
        assert_eq!(gate.decide(&spoof), Decision::Refused, "another fragment");
        assert_eq!(
            gate.decide(&url("tauri://localhost/onboarding.html")),
            Decision::Refused,
            "another page"
        );
        assert_eq!(gate.decide(&page), Decision::OwnPage);
        assert_eq!(
            gate.decide(&page),
            Decision::Refused,
            "the ticket is used once"
        );
    }

    #[test]
    fn pending_tickets_are_each_used_once_and_only_the_newest_eight_are_kept() {
        let gate = Gate::default();
        let pages: Vec<Url> = (0..10)
            .map(|i| url(&format!("tauri://localhost/index.html#{i}")))
            .collect();
        for page in &pages {
            gate.issue(page);
        }
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
}
