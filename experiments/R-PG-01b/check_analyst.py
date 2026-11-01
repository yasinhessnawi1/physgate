"""R-PG-01b, CRITERIA.md §8: the analyst's clone holds nothing it may not read, before the tally.

Usage, inside the analyst's clone, before anything else of §8 runs::

    uv run --frozen python -I experiments/R-PG-01b/check_analyst.py

It confirms that:

- the working directory is the clone: the top of the git checkout this script sits in;
- the clone's commit holds none of the excluded paths: ``experiments/R-PG-01/RESULT.md``,
  anything under ``experiments/R-PG-02/``, and any results summary (``RESULTS*.md``);
- the clone holds, on disk, no file its commit does not track, its environment and caches aside
  (``.venv``, ``__pycache__`` and the tools' caches): so no results summary, private working
  file or other copy kept outside the repository has been put into it, and no excluded path;
- the clone has no branch or tag other than the run tag's: its only refs are
  ``refs/tags/r-pg-01b-run``, or none, as a ``--single-branch --no-tags`` clone of the tag
  leaves it; and ``HEAD`` is the run tag's commit when the tag is there.

It prints one JSON line of counts and facts and exits 0 only if every one holds. It reads no
file it checks for; it only asks git and the file system what is there.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

EXCLUDED_FILES = ("experiments/R-PG-01/RESULT.md",)
EXCLUDED_DIRS = ("experiments/R-PG-02/",)
#: What a clone may hold on disk beside its commit's files: git's own directory, the
#: environment ``uv`` builds, and the caches Python and the tools write.
ENVIRONMENT = (".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")


def _git(clone: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(clone), *args], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def excluded(path: str) -> bool:
    """Whether a path is one §8 excludes by name."""
    name = path.rsplit("/", 1)[-1]
    return (
        path in EXCLUDED_FILES
        or path.startswith(EXCLUDED_DIRS)
        or (name.startswith("RESULTS") and name.endswith(".md"))
    )


def check(clone: Path, cwd: Path) -> dict[str, Any]:
    """Every fact of §8's check, and whether all hold."""
    found: dict[str, Any] = {"clone": str(clone)}
    found["working_directory_is_the_clone"] = cwd.resolve() == clone.resolve()
    tracked = set(_git(clone, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
    on_disk = [
        p.relative_to(clone).as_posix()
        for p in clone.rglob("*")
        if (p.is_file() or p.is_symlink())
        and not set(p.relative_to(clone).parts) & set(ENVIRONMENT)
    ]
    found["excluded_in_the_commit"] = sum(excluded(p) for p in tracked)
    found["excluded_on_disk"] = sum(excluded(p) for p in on_disk)
    found["untracked_files_on_disk"] = sum(p not in tracked for p in on_disk)
    refs = [r for r in _git(clone, "for-each-ref", "--format=%(refname)").splitlines() if r]
    others = [r for r in refs if r != f"refs/tags/{C.RUN_TAG}"]
    found["refs"] = len(refs)
    found["other_branches_or_tags"] = len(others)
    head = _git(clone, "rev-parse", "HEAD")
    tag = _git(clone, "rev-parse", f"refs/tags/{C.RUN_TAG}^{{commit}}")
    found["head_is_the_run_tag"] = (head == tag) if tag else None
    found["holds"] = (
        found["working_directory_is_the_clone"]
        and found["excluded_in_the_commit"] == 0
        and found["excluded_on_disk"] == 0
        and found["untracked_files_on_disk"] == 0
        and not others
        and found["head_is_the_run_tag"] is not False
    )
    return found


def main() -> int:
    """Run the check on the clone this script sits in; exit 0 only if it holds."""
    clone = Path(__file__).resolve().parents[2]
    found = check(clone, Path(os.getcwd()))
    print(json.dumps(found, sort_keys=True))
    return 0 if found["holds"] else 1


if __name__ == "__main__":
    sys.exit(main())
