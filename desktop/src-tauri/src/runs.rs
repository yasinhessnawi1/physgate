//! The default run root: the folder the app serves without being asked.
//!
//! On every start with no run folder set, the app serves `~/physgate-runs`, making it on
//! the first start, readable by its owner only. A folder already there is used as it is.
//! A link there is refused, never followed or replaced: the app serves only a real folder
//! it can vouch for, and whatever the link points at is left alone.
//! `PHYSGATE_DESKTOP_RUNS_ROOT` names another place, for a trial run.

use std::fs::{self, DirBuilder};
use std::io;
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};

use crate::config::{home, Settings};

/// What [`ensure`] found.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Root {
    /// The folder was made now.
    Created,
    /// A folder was already there, and is used as it is.
    Existing,
}

pub fn default_root() -> PathBuf {
    std::env::var_os("PHYSGATE_DESKTOP_RUNS_ROOT")
        .map_or_else(|| home().join("physgate-runs"), PathBuf::from)
}

/// Serve `root` when no run folder is set. Returns whether the settings changed.
pub fn with_default(settings: &mut Settings, root: &Path) -> bool {
    if settings.run_folders.is_empty() {
        settings.run_folders.push(root.to_path_buf());
        return true;
    }
    false
}

/// Make `root` (owner-only) if nothing is there; use it if it is a folder; refuse a link or
/// anything else.
pub fn ensure(root: &Path) -> Result<Root, String> {
    match fs::symlink_metadata(root) {
        Ok(meta) => check(root, &meta).map(|()| Root::Existing),
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            DirBuilder::new()
                .mode(0o700)
                .create(root)
                .map_err(|e| format!("{} could not be made: {e}", shown(root)))?;
            fs::set_permissions(root, fs::Permissions::from_mode(0o700))
                .map_err(|e| format!("{} could not be made private: {e}", shown(root)))?;
            // Looked at again, so something put there in the meantime is caught too.
            let meta = fs::symlink_metadata(root).map_err(|e| e.to_string())?;
            check(root, &meta).map(|()| Root::Created)
        }
        Err(e) => Err(format!("{} could not be read: {e}", shown(root))),
    }
}

fn check(root: &Path, meta: &fs::Metadata) -> Result<(), String> {
    if meta.file_type().is_symlink() {
        return Err(format!(
            "{} is a link. The app serves only a real folder there, so it does not use this one",
            shown(root)
        ));
    }
    if !meta.is_dir() {
        return Err(format!("{} is not a folder", shown(root)));
    }
    Ok(())
}

/// Whether any of `folders` holds anything but hidden files: a run, or runs.
pub fn has_runs(folders: &[PathBuf]) -> bool {
    folders.iter().any(|folder| {
        fs::read_dir(folder).is_ok_and(|entries| {
            entries
                .flatten()
                .any(|e| !e.file_name().to_string_lossy().starts_with('.'))
        })
    })
}

/// A path as a person reads it: the home folder as `~`.
pub fn shown(path: &Path) -> String {
    match path.strip_prefix(home()) {
        Ok(rest) => format!("~/{}", rest.display()),
        Err(_) => path.display().to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server;
    use crate::testdir::TestDir;
    use std::os::unix::fs::symlink;

    fn mode(path: &Path) -> u32 {
        fs::metadata(path).unwrap().permissions().mode() & 0o777
    }

    #[test]
    fn the_first_start_makes_the_root_owner_only_and_serves_it() {
        let dir = TestDir::new("root-first");
        let root = dir.path().join("physgate-runs");
        let mut settings = Settings::default();
        assert!(settings.run_folders.is_empty());
        assert!(with_default(&mut settings, &root));
        assert_eq!(ensure(&root), Ok(Root::Created));
        assert!(root.is_dir());
        assert_eq!(mode(&root), 0o700);
        let args = server::arguments(&settings);
        let at = args
            .iter()
            .position(|a| a == "--root")
            .expect("the root is served");
        assert_eq!(args[at + 1], root.display().to_string());
    }

    #[test]
    fn an_existing_root_is_used_as_it_is() {
        let dir = TestDir::new("root-existing");
        let root = dir.path().join("physgate-runs");
        fs::create_dir(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o750)).unwrap();
        fs::create_dir(root.join("run-one")).unwrap();
        assert_eq!(ensure(&root), Ok(Root::Existing));
        assert_eq!(mode(&root), 0o750, "not made again, not changed");
        assert!(root.join("run-one").is_dir(), "its runs are kept");
        // A start with folders already set adds nothing.
        let mut settings = Settings {
            run_folders: vec![PathBuf::from("/elsewhere")],
            ..Settings::default()
        };
        assert!(!with_default(&mut settings, &root));
        assert_eq!(settings.run_folders, [PathBuf::from("/elsewhere")]);
    }

    #[test]
    fn a_root_that_is_a_link_is_refused_and_what_it_points_at_is_left_alone() {
        let dir = TestDir::new("root-link");
        let target = dir.path().join("somewhere");
        fs::create_dir(&target).unwrap();
        let root = dir.path().join("physgate-runs");
        symlink(&target, &root).unwrap();
        let refused = ensure(&root).unwrap_err();
        assert!(refused.contains("is a link"), "{refused}");
        assert_eq!(
            fs::read_dir(&target).unwrap().count(),
            0,
            "nothing made through it"
        );
        assert!(
            fs::symlink_metadata(&root)
                .unwrap()
                .file_type()
                .is_symlink(),
            "not replaced"
        );

        // A link to nothing is refused too, and nothing is made where it points.
        let dangling = dir.path().join("physgate-runs-dangling");
        let nowhere = dir.path().join("nowhere");
        symlink(&nowhere, &dangling).unwrap();
        assert!(ensure(&dangling).unwrap_err().contains("is a link"));
        assert!(!nowhere.exists());
    }

    #[test]
    fn a_file_at_the_root_is_refused() {
        let dir = TestDir::new("root-file");
        let root = dir.path().join("physgate-runs");
        fs::write(&root, "not a folder").unwrap();
        assert!(ensure(&root).unwrap_err().contains("is not a folder"));
    }

    #[test]
    fn runs_are_seen_only_when_a_folder_holds_something() {
        let dir = TestDir::new("root-runs");
        let root = dir.path().join("physgate-runs");
        fs::create_dir(&root).unwrap();
        let folders = vec![root.clone(), dir.path().join("missing")];
        assert!(!has_runs(&folders), "empty");
        fs::write(root.join(".DS_Store"), "").unwrap();
        assert!(!has_runs(&folders), "hidden files are not runs");
        fs::create_dir(root.join("run-one")).unwrap();
        assert!(has_runs(&folders));
    }

    #[test]
    fn the_home_folder_is_shown_as_a_tilde() {
        assert_eq!(shown(&home().join("physgate-runs")), "~/physgate-runs");
        assert_eq!(shown(Path::new("/srv/runs")), "/srv/runs");
    }
}
