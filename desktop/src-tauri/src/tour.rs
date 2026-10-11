//! A click-through of the served UI inside the app's own webview, for checking the shell.
//!
//! Started only when the app is launched with `PHYSGATE_DESKTOP_TOUR` naming a file. It
//! clicks every in-app link it can reach and every button on each view, counts any
//! Content-Security-Policy violation the webview reports (from the first byte of each page
//! load on), lists any request to another origin, and counts the server's refusals in its
//! log. The findings are written to the named file. A browser test cannot do this, since
//! the point is what the app's webview sends, not what a test browser sends.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use tauri::WebviewWindow;

static TAKEN: AtomicBool = AtomicBool::new(false);

/// Run in every page before its own scripts, so a violation during load is counted too.
pub const WATCH_SCRIPT: &str = r"
window.__physgateTour = window.__physgateTour || { csp: [] };
document.addEventListener('securitypolicyviolation', (e) => {
  window.__physgateTour.csp.push(e.violatedDirective + ' ' + e.blockedURI);
});
";

/// The links on the page now, as hrefs.
const LINKS: &str = r##"JSON.stringify([...document.querySelectorAll('a[href^="#"]')].map((a) => a.getAttribute('href')))"##;

/// How many enabled buttons the view has.
const BUTTONS: &str =
    "JSON.stringify(document.querySelectorAll('main button:not([disabled])').length)";

/// What the page has seen so far: violations, requests, and where it is.
const FINDINGS: &str = r"JSON.stringify((() => {
  const resources = performance.getEntriesByType('resource').map((e) => e.name);
  return {
    origin: location.origin,
    csp: (window.__physgateTour || { csp: null }).csp,
    resources: resources.length,
    outbound: resources.filter((n) => !n.startsWith(location.origin)),
  };
})())";

/// The most views visited, and the most buttons pressed on one view.
const MOST_VIEWS: usize = 150;
const MOST_BUTTONS: usize = 8;

/// Take the tour once, on the first page the server serves, and write the findings to `out`.
///
/// Each step is one evaluation, and the waiting is done here rather than in the page: a
/// window that is hidden or on a sleeping display has its page timers slowed to a crawl,
/// and a tour that waited on them would never finish.
pub fn take(window: WebviewWindow, out: PathBuf, server_log: PathBuf) {
    if TAKEN.swap(true, Ordering::SeqCst) {
        return;
    }
    thread::spawn(move || {
        thread::sleep(Duration::from_secs(3));
        let mut seen: BTreeSet<String> = BTreeSet::new();
        let mut queue: VecDeque<String> = VecDeque::new();
        let mut visited = Vec::new();
        let mut pressed = 0usize;
        enqueue(&window, &mut seen, &mut queue);
        while let Some(href) = queue.pop_front() {
            if visited.len() >= MOST_VIEWS {
                break;
            }
            let quoted = serde_json::to_string(&href).unwrap_or_default();
            let link = ask(
                &window,
                &format!(
                    "JSON.stringify((() => {{ const h = {quoted}; \
                     const a = [...document.querySelectorAll('a[href^=\"#\"]')].find((x) => x.getAttribute('href') === h); \
                     if (a) {{ a.click(); return true; }} location.hash = h.slice(1); return false; }})())"
                ),
            );
            thread::sleep(Duration::from_millis(900));
            let buttons = ask(&window, BUTTONS)
                .and_then(|v| v.as_u64())
                .and_then(|n| usize::try_from(n).ok())
                .unwrap_or(0);
            for i in 0..buttons.min(MOST_BUTTONS) {
                let _ = window.eval(format!(
                    "(() => {{ const b = document.querySelectorAll('main button:not([disabled])')[{i}]; if (b) b.click(); \
                     if (document.querySelector('dialog[open]')) document.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Escape', bubbles: true }})); }})()"
                ));
                pressed += 1;
                thread::sleep(Duration::from_millis(250));
            }
            let alerts = ask(
                &window,
                "JSON.stringify(document.querySelectorAll('[role=\"alert\"]').length)",
            );
            visited.push(serde_json::json!({ "hash": href, "link": link, "alerts": alerts }));
            enqueue(&window, &mut seen, &mut queue);
            write(
                &out,
                &server_log,
                &visited,
                pressed,
                ask(&window, FINDINGS).as_ref(),
                false,
            );
        }
        write(
            &out,
            &server_log,
            &visited,
            pressed,
            ask(&window, FINDINGS).as_ref(),
            true,
        );
    });
}

/// Add the page's links not seen before to the queue.
fn enqueue(window: &WebviewWindow, seen: &mut BTreeSet<String>, queue: &mut VecDeque<String>) {
    let Some(serde_json::Value::Array(links)) = ask(window, LINKS) else {
        return;
    };
    for link in links.iter().filter_map(serde_json::Value::as_str) {
        if seen.insert(link.to_string()) {
            queue.push_back(link.to_string());
        }
    }
}

/// Evaluate `js` (which returns a JSON string) in the page and read the answer.
fn ask(window: &WebviewWindow, js: &str) -> Option<serde_json::Value> {
    let (sender, receiver) = mpsc::channel();
    window
        .eval_with_callback(js, move |result| {
            let _ = sender.send(result);
        })
        .ok()?;
    let result = receiver.recv_timeout(Duration::from_secs(10)).ok()?;
    Some(page_value(&result))
}

/// Write the findings so far; `done` says whether the tour finished.
fn write(
    out: &PathBuf,
    server_log: &PathBuf,
    visited: &[serde_json::Value],
    pressed: usize,
    page: Option<&serde_json::Value>,
    done: bool,
) {
    let log = fs::read_to_string(server_log).unwrap_or_default();
    let report = serde_json::json!({
        "done": done,
        "views_visited": visited.len(),
        "buttons_pressed": pressed,
        "page": page,
        "visited": visited,
        "server": statuses(&log),
    });
    let partial = out.with_extension("partial");
    if fs::write(
        &partial,
        serde_json::to_string_pretty(&report).unwrap_or_default(),
    )
    .is_ok()
    {
        let _ = fs::rename(partial, out);
    }
}

/// What the page returned: the webview hands back either the string itself or its JSON
/// encoding, so both are read.
fn page_value(result: &str) -> serde_json::Value {
    let inner = serde_json::from_str::<String>(result).unwrap_or_else(|_| result.to_string());
    serde_json::from_str(&inner).unwrap_or(serde_json::Value::Null)
}

/// The server's request log, counted by status, with every refusal listed.
fn statuses(log: &str) -> serde_json::Value {
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut refused = Vec::new();
    let mut requests = 0;
    for line in log.lines() {
        // `127.0.0.1 - - [date] "GET /path HTTP/1.1" 200 -`
        let Some(after) = line.rsplit_once("\" ").map(|(_, after)| after) else {
            continue;
        };
        let Some(code) = after.split_whitespace().next() else {
            continue;
        };
        if code.len() == 3 && code.chars().all(|c| c.is_ascii_digit()) {
            requests += 1;
            *counts.entry(code.to_string()).or_default() += 1;
            if code == "403" {
                refused.push(line.to_string());
            }
        }
    }
    serde_json::json!({ "requests": requests, "by_status": counts, "refused_403": refused })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_page_result_is_read_in_either_encoding() {
        assert_eq!(page_value(r#"{"done":true}"#)["done"], true);
        assert_eq!(page_value(r#""{\"done\":true}""#)["done"], true);
        assert!(page_value("null").is_null());
    }

    #[test]
    fn the_request_log_is_counted_by_status() {
        let log = "{\"url\": \"x\"}\n\
            127.0.0.1 - - [10/Oct/2026 20:00:00] \"GET / HTTP/1.1\" 200 -\n\
            127.0.0.1 - - [10/Oct/2026 20:00:01] \"GET /api/runs HTTP/1.1\" 200 -\n\
            127.0.0.1 - - [10/Oct/2026 20:00:02] \"GET /api/x HTTP/1.1\" 403 -\n";
        let counted = statuses(log);
        assert_eq!(counted["requests"], 3);
        assert_eq!(counted["by_status"]["200"], 2);
        assert_eq!(counted["refused_403"].as_array().unwrap().len(), 1);
    }
}
