//! One app per data folder: a second launch hands over to the first and quits.
//!
//! The first instance listens on a Unix socket; a later one connects, asks it to come
//! forward, and exits before it starts or stops anything. The socket is named after the data
//! folder's identity (device and inode), so two spellings of one folder are one instance and
//! the installed app and a trial build (different folders) never meet. It lives in the
//! per-user temporary folder macOS gives each account (owner-only), not in the shared `/tmp`,
//! so no other account can create it first. A socket left by a killed instance answers no
//! one, and is replaced.

use std::fs;
use std::hash::{DefaultHasher, Hash, Hasher};
use std::io::{self, BufRead, BufReader, Write};
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::thread;

/// What claiming the folder found.
pub enum Claim {
    /// No other instance: this one listens for later launches.
    First(UnixListener),
    /// Another instance has the folder and was asked to come forward.
    HandedOver,
}

/// The per-user temporary folder (`_CS_DARWIN_USER_TEMP_DIR`), owner-only by the system.
fn user_temp_dir() -> Option<PathBuf> {
    let mut buffer = vec![0u8; 1024];
    // SAFETY: confstr writes at most `buffer.len()` bytes, NUL included.
    let length = unsafe {
        libc::confstr(
            libc::_CS_DARWIN_USER_TEMP_DIR,
            buffer.as_mut_ptr().cast(),
            buffer.len(),
        )
    };
    if length == 0 || length > buffer.len() {
        return None;
    }
    buffer.truncate(length - 1);
    String::from_utf8(buffer).ok().map(PathBuf::from)
}

/// The socket for the data folder `root`, which must exist.
pub fn socket_path(root: &Path) -> io::Result<PathBuf> {
    let meta = fs::metadata(root)?;
    let mut hasher = DefaultHasher::new();
    (meta.dev(), meta.ino()).hash(&mut hasher);
    let dir = user_temp_dir().ok_or_else(|| io::Error::other("no per-user temporary folder"))?;
    Ok(dir.join(format!("physgate-{:016x}.sock", hasher.finish())))
}

/// Claim the folder whose socket is `socket`: hand over to an instance already there, or
/// become the one that listens.
pub fn claim(socket: &Path) -> io::Result<Claim> {
    if let Ok(mut stream) = UnixStream::connect(socket) {
        let _ = stream.write_all(b"show\n");
        return Ok(Claim::HandedOver);
    }
    // Nothing answers: no file, or one left by an instance that was killed.
    let _ = fs::remove_file(socket);
    let listener = UnixListener::bind(socket)?;
    fs::set_permissions(socket, fs::Permissions::from_mode(0o600))?;
    Ok(Claim::First(listener))
}

/// Call `show` each time a later launch hands over.
pub fn listen(listener: UnixListener, show: impl Fn() + Send + 'static) {
    thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            let mut line = String::new();
            let _ = BufReader::new(stream).read_line(&mut line);
            if line.trim() == "show" {
                show();
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testdir::TestDir;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::time::{Duration, Instant};

    #[test]
    fn the_socket_is_in_an_owner_only_folder_and_named_by_the_folders_identity() {
        let dir = TestDir::new("instance-path");
        let root = dir.path().join("Home");
        fs::create_dir(&root).unwrap();
        let socket = socket_path(&root).unwrap();
        let parent = socket.parent().unwrap();
        assert!(!parent.starts_with("/tmp") && !parent.starts_with("/private/tmp"));
        let meta = fs::metadata(parent).unwrap();
        assert_eq!(meta.permissions().mode() & 0o077, 0, "{}", parent.display());
        // SAFETY: getuid has no preconditions.
        assert_eq!(meta.uid(), unsafe { libc::getuid() });
        // Another spelling of the same folder is the same instance; another folder is not.
        assert_eq!(socket_path(&dir.path().join("HOME")).unwrap(), socket);
        let other = dir.path().join("Other");
        fs::create_dir(&other).unwrap();
        assert_ne!(socket_path(&other).unwrap(), socket);
    }

    #[test]
    fn a_second_claim_hands_over_and_the_first_is_asked_to_come_forward() {
        let dir = TestDir::new("instance-claim");
        let socket = dir.path().join("t.sock");
        let Claim::First(listener) = claim(&socket).unwrap() else {
            panic!("the first claim must listen");
        };
        let shown = Arc::new(AtomicBool::new(false));
        let flag = Arc::clone(&shown);
        listen(listener, move || flag.store(true, Ordering::SeqCst));
        assert!(matches!(claim(&socket).unwrap(), Claim::HandedOver));
        let deadline = Instant::now() + Duration::from_secs(5);
        while !shown.load(Ordering::SeqCst) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(20));
        }
        assert!(
            shown.load(Ordering::SeqCst),
            "the first instance came forward"
        );
        assert_eq!(
            fs::metadata(&socket).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }

    #[test]
    fn a_socket_left_by_a_killed_instance_is_replaced() {
        let dir = TestDir::new("instance-stale");
        let socket = dir.path().join("t.sock");
        // A socket file nobody listens on, as a killed instance leaves it.
        drop(UnixListener::bind(&socket).unwrap());
        assert!(socket.exists());
        // A process another test forks at that moment can hold a copy of the closed listener
        // until it runs its program, so the socket gets a moment to go quiet.
        let deadline = Instant::now() + Duration::from_secs(2);
        let mut claimed = claim(&socket).unwrap();
        while matches!(claimed, Claim::HandedOver) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(20));
            claimed = claim(&socket).unwrap();
        }
        assert!(matches!(claimed, Claim::First(_)));
    }
}
