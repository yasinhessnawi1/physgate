"""Where a review is read from: one standing root, and one directory per review beneath it.

**Why a root of its own.** A reviewer is shown paths, and a path can say what it is
looking at. The injected-error instrument refuses to show a reviewer any path holding
a word that would give the evaluation away, its own harness's name among them, so a
reviewer's files cannot live under a directory named after the harness. The standing
convention is ``~/review-scratch/``: persistent, outside every repository, and free of
every such word on both machines the project runs on. Other scratch stays where it
was. The root is checked when it is given, before any review is prepared, so a
rename that reintroduces a giveaway word is refused at the start, never mid-run.

**Why generated names beneath it.** A run id and a subtask id are chosen freely and
may hold any word. A review's directory is named by a generated id alone: the
instrument's ``r`` and twelve hex digits, or a session's uuid.

**The layout.** ``<root>/<id>/read/`` holds everything the reviewer may read, and is
the one directory its hooks allow it to read. ``<root>/<id>/session/`` holds the
session's own files (settings, hook state, configuration, scratch home, the stream
it writes), which it may not read. That directory names its run before anything in
it holds a credential, so the run's resume finds a review session left running,
stops it, and removes its credential, as it does a role session's.
"""

from __future__ import annotations

import re
from pathlib import Path

from physgate.evaluation.inject.corpus import telltales
from physgate.reviewers.exceptions import ReviewRootError

#: The standing root's name, under the user's home directory.
STANDING_ROOT_NAME = "review-scratch"
READ_DIRNAME = "read"
SESSION_DIRNAME = "session"
#: A generated review id: the instrument's, or a session's uuid.
REVIEW_ID = re.compile(
    r"^(r[0-9a-f]{12}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def standing_root(home: Path) -> Path:
    """The conventional review root under ``home``."""
    return Path(home) / STANDING_ROOT_NAME


def _inside_a_checkout(path: Path) -> Path | None:
    """The nearest directory at or above ``path`` that holds a ``.git``, if there is one."""
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def require_review_root(root: Path) -> Path:
    """Return ``root`` resolved, if reviews may be read from beneath it.

    Raises:
        ReviewRootError: its path holds a word that would tell a reviewer what is being
            measured, or it lies inside a git checkout, whose other files a reviewer
            must never be beside.
    """
    resolved = Path(root).expanduser().resolve()
    found = telltales(str(resolved))
    if found:
        msg = "the review root's path holds a word that would tell a reviewer what it reads"
        raise ReviewRootError(msg, root=str(resolved), found=",".join(found))
    checkout = _inside_a_checkout(resolved)
    if checkout is not None:
        msg = "the review root lies inside a git checkout"
        raise ReviewRootError(msg, root=str(resolved), checkout=str(checkout))
    return resolved


def review_dir(root: Path, review_id: str) -> Path:
    """The directory of one review under an already checked ``root``.

    Raises:
        ReviewRootError: ``review_id`` is not a generated id.
    """
    if not REVIEW_ID.fullmatch(review_id):
        msg = "a review is named by a generated id alone"
        raise ReviewRootError(msg, review_id=review_id)
    return Path(root) / review_id
