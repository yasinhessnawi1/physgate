//! The update channel: a folder on this machine, served on loopback only while a check runs.
//!
//! The build script writes a signed bundle and a `latest.json` that names it into the
//! folder. The updater only fetches over HTTP, so for the length of one check the shell
//! serves that folder itself, on `127.0.0.1` and a port the system picks, and answers
//! exactly two requests: `GET /latest.json`, and `GET` of the bundle the manifest names.
//! Nothing else in the folder, and nothing outside it, can be asked for.
//!
//! The bundle's own address in the manifest is rewritten to this port, since the build
//! script cannot know it. The signature is left as written: the updater checks it against
//! the public key built into the app, and refuses a bundle it does not match.

use std::fs;
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::Duration;

use tauri::Url;

/// The manifest's name in the folder and in the request.
pub const MANIFEST: &str = "latest.json";

/// An open channel. Dropping it stops the listener.
pub struct Channel {
    port: u16,
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}

impl Channel {
    /// Serve `folder`, if it holds a manifest. `Ok(None)` when nothing has been published.
    pub fn open(folder: &Path) -> io::Result<Option<Self>> {
        let manifest_path = folder.join(MANIFEST);
        let text = match fs::read_to_string(&manifest_path) {
            Ok(text) => text,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(e),
        };
        let listener = TcpListener::bind(SocketAddr::from((Ipv4Addr::LOCALHOST, 0)))?;
        let port = listener.local_addr()?.port();
        let (manifest, bundle) = rewrite(&text, port)?;
        let bundle = bundle.map(|name| (name.clone(), folder.join(name)));
        listener.set_nonblocking(true)?;
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = Arc::clone(&stop);
        let worker = thread::spawn(move || {
            while !stopping.load(Ordering::Relaxed) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        let _ = answer(stream, manifest.as_bytes(), bundle.as_ref());
                    }
                    Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(20));
                    }
                    Err(_) => thread::sleep(Duration::from_millis(20)),
                }
            }
        });
        Ok(Some(Self {
            port,
            stop,
            worker: Some(worker),
        }))
    }

    /// The manifest's address, for the updater.
    pub fn manifest_url(&self) -> Url {
        Url::parse(&format!("http://127.0.0.1:{}/{MANIFEST}", self.port))
            .expect("a loopback address parses")
    }
}

impl Drop for Channel {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

/// The manifest with every platform's `url` pointed at this port, and the one bundle it names.
///
/// A `url` that is not a plain file name is left as it is and nothing is served for it,
/// so a manifest cannot make the channel serve a path outside its folder.
fn rewrite(text: &str, port: u16) -> io::Result<(String, Option<String>)> {
    let mut manifest: serde_json::Value =
        serde_json::from_str(text).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    let mut bundle = None;
    if let Some(platforms) = manifest
        .get_mut("platforms")
        .and_then(serde_json::Value::as_object_mut)
    {
        for entry in platforms.values_mut() {
            let Some(name) = entry.get("url").and_then(serde_json::Value::as_str) else {
                continue;
            };
            let name = name.rsplit('/').next().unwrap_or(name).to_string();
            if !plain_file_name(&name) {
                continue;
            }
            entry["url"] = serde_json::Value::String(format!("http://127.0.0.1:{port}/{name}"));
            bundle = Some(name);
        }
    }
    let text = serde_json::to_string(&manifest).map_err(io::Error::other)?;
    Ok((text, bundle))
}

fn plain_file_name(name: &str) -> bool {
    !name.is_empty()
        && name != MANIFEST
        && !name.starts_with('.')
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "._-".contains(c))
}

/// Answer one request: the manifest, the bundle, or a refusal.
fn answer(
    mut stream: TcpStream,
    manifest: &[u8],
    bundle: Option<&(String, PathBuf)>,
) -> io::Result<()> {
    stream.set_nonblocking(false)?;
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    let head = read_head(&mut stream)?;
    let mut words = head.lines().next().unwrap_or("").split(' ');
    let (method, target) = (words.next().unwrap_or(""), words.next().unwrap_or(""));
    if method != "GET" {
        return respond(
            &mut stream,
            "405 Method Not Allowed",
            "text/plain",
            b"GET only\n",
        );
    }
    if target == format!("/{MANIFEST}") {
        return respond(&mut stream, "200 OK", "application/json", manifest);
    }
    if let Some((name, path)) = bundle {
        if target == format!("/{name}") {
            let bytes = fs::read(path)?;
            return respond(&mut stream, "200 OK", "application/octet-stream", &bytes);
        }
    }
    respond(
        &mut stream,
        "404 Not Found",
        "text/plain",
        b"not in the channel\n",
    )
}

fn read_head(stream: &mut TcpStream) -> io::Result<String> {
    let mut head = Vec::new();
    let mut byte = [0u8; 1];
    while !head.ends_with(b"\r\n\r\n") && head.len() < 8192 {
        if stream.read(&mut byte)? == 0 {
            break;
        }
        head.push(byte[0]);
    }
    Ok(String::from_utf8_lossy(&head).into_owned())
}

fn respond(stream: &mut TcpStream, status: &str, kind: &str, body: &[u8]) -> io::Result<()> {
    write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: {kind}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )?;
    stream.write_all(body)?;
    stream.flush()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testdir::TestDir;
    use std::sync::Mutex;

    /// The socket tests run one at a time: a port one test frees can be handed straight to
    /// another test's socket, which would make the closed-channel test fail for nothing.
    static SOCKETS: Mutex<()> = Mutex::new(());

    fn one_at_a_time() -> std::sync::MutexGuard<'static, ()> {
        SOCKETS
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn get(port: u16, request: &str) -> (String, Vec<u8>) {
        let mut stream = TcpStream::connect(("127.0.0.1", port)).unwrap();
        stream.write_all(request.as_bytes()).unwrap();
        let mut reply = Vec::new();
        stream.read_to_end(&mut reply).unwrap();
        let split = reply.windows(4).position(|w| w == b"\r\n\r\n").unwrap();
        let head = String::from_utf8_lossy(&reply[..split]).into_owned();
        (head, reply[split + 4..].to_vec())
    }

    fn published(dir: &Path, url: &str) {
        fs::write(dir.join("physgate-0.1.2.app.tar.gz"), b"bundle bytes").unwrap();
        fs::write(dir.join("secret.txt"), b"never served").unwrap();
        let manifest = serde_json::json!({
            "version": "0.1.2",
            "platforms": {"darwin-aarch64": {"signature": "sig", "url": url}}
        });
        fs::write(dir.join(MANIFEST), manifest.to_string()).unwrap();
    }

    #[test]
    fn nothing_published_opens_nothing() {
        let dir = TestDir::new("channel-empty");
        assert!(Channel::open(dir.path()).unwrap().is_none());
    }

    #[test]
    fn the_manifest_and_its_bundle_are_served_on_loopback_and_nothing_else() {
        let _sockets = one_at_a_time();
        let dir = TestDir::new("channel-serve");
        published(dir.path(), "physgate-0.1.2.app.tar.gz");
        let channel = Channel::open(dir.path()).unwrap().unwrap();
        let url = channel.manifest_url();
        assert_eq!(url.host_str(), Some("127.0.0.1"));
        let port = url.port().unwrap();

        let (head, body) = get(port, "GET /latest.json HTTP/1.1\r\nHost: x\r\n\r\n");
        assert!(head.starts_with("HTTP/1.1 200"), "{head}");
        let manifest: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(
            manifest["platforms"]["darwin-aarch64"]["url"],
            format!("http://127.0.0.1:{port}/physgate-0.1.2.app.tar.gz")
        );
        assert_eq!(manifest["platforms"]["darwin-aarch64"]["signature"], "sig");

        let (head, body) = get(port, "GET /physgate-0.1.2.app.tar.gz HTTP/1.1\r\n\r\n");
        assert!(head.starts_with("HTTP/1.1 200"));
        assert_eq!(body, b"bundle bytes");

        for target in ["/secret.txt", "/../secret.txt", "/", "/%2E%2E/secret.txt"] {
            let (head, _) = get(port, &format!("GET {target} HTTP/1.1\r\n\r\n"));
            assert!(head.starts_with("HTTP/1.1 404"), "{target}: {head}");
        }
        let (head, _) = get(port, "POST /latest.json HTTP/1.1\r\n\r\n");
        assert!(head.starts_with("HTTP/1.1 405"));
    }

    #[test]
    fn a_manifest_naming_a_path_outside_the_folder_serves_no_bundle() {
        let _sockets = one_at_a_time();
        let dir = TestDir::new("channel-escape");
        published(dir.path(), "../../etc/.hidden");
        let channel = Channel::open(dir.path()).unwrap().unwrap();
        let port = channel.manifest_url().port().unwrap();
        let (head, _) = get(port, "GET /.hidden HTTP/1.1\r\n\r\n");
        assert!(head.starts_with("HTTP/1.1 404"));
    }

    #[test]
    fn a_closed_channel_stops_listening() {
        let _sockets = one_at_a_time();
        let dir = TestDir::new("channel-close");
        published(dir.path(), "physgate-0.1.2.app.tar.gz");
        let channel = Channel::open(dir.path()).unwrap().unwrap();
        let port = channel.manifest_url().port().unwrap();
        drop(channel);
        // The port is free again: the listener went with the channel. A process another test
        // forks at that moment can hold a copy of the socket until it runs its program, so
        // the port gets a moment to come free rather than none.
        let mut rebound = TcpListener::bind(("127.0.0.1", port));
        for _ in 0..50 {
            if rebound.is_ok() {
                break;
            }
            thread::sleep(Duration::from_millis(20));
            rebound = TcpListener::bind(("127.0.0.1", port));
        }
        assert!(rebound.is_ok(), "{rebound:?}");
    }
}
