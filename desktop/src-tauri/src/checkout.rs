//! The checkouts the shell can serve from, and the build stamp it watches in each.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

/// A checkout the menu offers: its folder and what to call it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Worktree {
    pub path: PathBuf,
    pub label: String,
}

/// Whether `path` looks like a physgate checkout.
pub fn is_checkout(path: &Path) -> bool {
    path.join("pyproject.toml").is_file() && path.join("ui").is_dir()
}

/// Every worktree of the repository `checkout` belongs to, with `checkout` itself always first
/// if git cannot list them.
pub fn worktrees(checkout: &Path) -> Vec<Worktree> {
    let listed = Command::new("git")
        .arg("-C")
        .arg(checkout)
        .args(["worktree", "list", "--porcelain"])
        .output()
        .ok()
        .filter(|out| out.status.success())
        .map(|out| parse_porcelain(&String::from_utf8_lossy(&out.stdout)))
        .unwrap_or_default();
    let mut found: Vec<Worktree> = listed
        .into_iter()
        .filter(|w| is_checkout(&w.path))
        .collect();
    if !found.iter().any(|w| w.path == checkout) {
        found.insert(
            0,
            Worktree {
                path: checkout.to_path_buf(),
                label: name_of(checkout),
            },
        );
    }
    found
}

/// The worktrees in `git worktree list --porcelain` output, bare repositories left out.
pub fn parse_porcelain(text: &str) -> Vec<Worktree> {
    let mut found = Vec::new();
    for block in text.split("\n\n") {
        let mut path = None;
        let mut branch = None;
        let mut bare = false;
        for line in block.lines() {
            if let Some(rest) = line.strip_prefix("worktree ") {
                path = Some(PathBuf::from(rest));
            } else if let Some(rest) = line.strip_prefix("branch ") {
                branch = Some(rest.trim_start_matches("refs/heads/").to_string());
            } else if line == "detached" {
                branch = Some("detached".to_string());
            } else if line == "bare" {
                bare = true;
            }
        }
        if let (Some(path), false) = (path, bare) {
            let label = match branch {
                Some(branch) => format!("{} — {branch}", name_of(&path)),
                None => name_of(&path),
            };
            found.push(Worktree { path, label });
        }
    }
    found
}

fn name_of(path: &Path) -> String {
    path.file_name().map_or_else(
        || path.display().to_string(),
        |n| n.to_string_lossy().into_owned(),
    )
}

/// The UI build's stamp in `checkout`: written last by `scripts/build-ui.sh`, so a change in
/// it means a finished build. `None` while there is no build, or while a build is under way.
pub fn build_stamp(checkout: &Path) -> Option<String> {
    fs::read_to_string(checkout.join("ui/dist/.physgate-build.json")).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn worktrees_are_read_from_porcelain_output() {
        let text = "worktree /dev/physgate\nHEAD 68b4d56\nbranch refs/heads/master\n\n\
                    worktree /dev/physgate-graph-run-views\nHEAD 597a505\nbranch refs/heads/feat/graph-run-views\n\n\
                    worktree /dev/physgate-old\nHEAD 1111111\ndetached\n\n\
                    worktree /srv/bare.git\nbare\n";
        let found = parse_porcelain(text);
        let labels: Vec<&str> = found.iter().map(|w| w.label.as_str()).collect();
        assert_eq!(
            labels,
            [
                "physgate — master",
                "physgate-graph-run-views — feat/graph-run-views",
                "physgate-old — detached"
            ]
        );
        assert_eq!(
            found[1].path,
            PathBuf::from("/dev/physgate-graph-run-views")
        );
    }

    #[test]
    fn a_folder_that_is_not_a_repository_is_still_offered() {
        let dir = crate::testdir::TestDir::new("not-a-repo");
        let found = worktrees(dir.path());
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].path, dir.path());
    }
}
