"""``physgate knowledge promote``: the library's only writer, and it is a human (ARCH-100).

Promotion has two guards, not one. ``require_interactive`` refuses to run unless
``stdin`` is a real terminal — it cannot be satisfied from inside an agent
session, a script, or a pipe, by design. The actual write (``_apply``) carries
no such check itself, so it can be tested directly and exhaustively without a
terminal; nothing in this module calls it without ``require_interactive``
having already run first, and the CLI is the one caller that matters.

A promoted candidate is written whole into its destination — a `kind:
"standards"` candidate replaces `knowledge/<domain>/standards.md` outright
(ARCH-101: one standards file per domain, and promoting a new draft is the
human's explicit act of replacing it); a `kind: "skill"` or `"antipattern"`
candidate creates `knowledge/<domain>/skill.md` if none exists yet, or is
appended to it if one already does, matching ARCH-100's own model of a skill
file accumulating from many episodes over time. Either way the candidate is
removed from `staging/` once promoted, so `staging/` always reflects exactly
what is still pending, and a candidate id cannot be promoted twice.

A `kind: "rubric"` candidate is staged under `knowledge/reviewers/staging/` and
replaces `knowledge/reviewers/<role>/rubric.md` whole, inside the tree only a
reviewer reads.

Every promotion appends one line to `knowledge/promotions.jsonl`: which
candidate, which kind and domain, which destination, who approved it, when,
and the sha256 of the destination as written. For a rubric that line is the
ledger event ARCH-062 asks for, and the digest is what every later reader holds
the file to: a rubric edited without a promotion no longer matches its line.
This is the record ARCH-100's own acceptance test reads: the library's content,
minus what this file's writes account for, is empty.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

from physgate.knowledge.exceptions import KnowledgeError
from physgate.knowledge.staging import RUBRIC_STAGING_ROOT, STAGING_ROOT, Candidate, Kind

#: Where the library lives, relative to a worktree root — the same convention
#: `loader.py` and `hooks/settings.py`'s knowledge-root discovery already use.
KNOWLEDGE_ROOT = Path("knowledge")

#: One line per promotion, appended, never rewritten.
PROMOTIONS_NAME = "promotions.jsonl"

STANDARDS_NAME = "standards.md"
SKILL_NAME = "skill.md"
RUBRIC_NAME = "rubric.md"
#: The tree beneath the library that only reviewers read.
REVIEWERS_NAME = "reviewers"


class PromotionError(KnowledgeError):
    """A promotion refused: not interactive, no name to approve it, or no such candidate."""


def require_interactive() -> None:
    """Refuse unless ``stdin`` is a real terminal.

    The only guard between an agent session and the library. Nothing in this
    module, and nothing calling it, may pass a flag that skips this check for
    a real promotion — a test calls it directly to prove it refuses, exactly
    as a real non-interactive run would.

    Raises:
        PromotionError: ``stdin`` is not a TTY.
    """
    if not sys.stdin.isatty():
        msg = (
            "promotion refuses to run non-interactively: it moves a candidate into the "
            "library only when a human is at a terminal to approve it"
        )
        raise PromotionError(msg)


def rubric_path(knowledge_root: Path, role: str) -> Path:
    """Where ``role``'s reviewer rubric lives under ``knowledge_root``."""
    return Path(knowledge_root) / REVIEWERS_NAME / role / RUBRIC_NAME


def _destination(domain: str, kind: Kind, root: Path) -> Path:
    if kind == "rubric":
        return rubric_path(root, domain)
    name = STANDARDS_NAME if kind == "standards" else SKILL_NAME
    return Path(root) / domain / name


#: A candidate id as staging writes it: a plain identifier, never a path.
_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _find(
    candidate_id: str, staging_root: Path, rubric_staging_root: Path
) -> tuple[Kind, Candidate, Path] | None:
    """The staged candidate ``candidate_id``, looked for only where its kind is staged.

    A rubric is looked for only under the rubric staging directory, inside the tree
    only reviewers read, and every other kind only under the general one, which a
    session may write. So a rubric written where a session may write is never
    found, and a candidate is promoted as the kind it says it is, never as the
    kind of the directory it was moved into.

    Raises:
        PromotionError: the id is not a plain id; the staged file is a link; or the
            candidate's own kind is not its directory's.
    """
    if not _CANDIDATE_ID.fullmatch(candidate_id):
        msg = "a candidate is named by a plain id, as staging wrote it"
        raise PromotionError(msg, candidate_id=candidate_id)
    places: tuple[tuple[Kind, Path], ...] = (
        ("standards", Path(staging_root)),
        ("skill", Path(staging_root)),
        ("antipattern", Path(staging_root)),
        ("rubric", Path(rubric_staging_root)),
    )
    for kind, root in places:
        path = root / kind / f"{candidate_id}.json"
        if path.is_symlink():
            msg = "a staged candidate is a link, so what it holds is somewhere else"
            raise PromotionError(msg, candidate_id=candidate_id, path=str(path))
        if path.is_file():
            candidate = Candidate.model_validate_json(_read_no_follow(path).decode("utf-8"))
            if candidate.kind != kind:
                msg = "a candidate's own kind is not the kind of the directory it is staged in"
                raise PromotionError(
                    msg, candidate_id=candidate_id, kind=candidate.kind, directory=kind
                )
            return kind, candidate, path
    return None


_NO_FOLLOW = os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _link_refused(path: Path) -> PromotionError:
    msg = "a path a promotion reads or writes is a link, so it would reach somewhere else"
    return PromotionError(msg, path=str(path))


def _read_no_follow(path: Path) -> bytes:
    """``path``'s bytes, read through a descriptor that refuses to follow a link.

    The check and the read are one system call, so nothing can be swapped in
    between them.

    Raises:
        PromotionError: ``path`` is a link, or not a regular file.
    """
    try:
        fd = os.open(path, os.O_RDONLY | _NO_FOLLOW)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _link_refused(path) from None
        raise
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            msg = "a staged candidate is not a regular file"
            raise PromotionError(msg, path=str(path))
        return handle.read()


def _open_dir(root: Path, parts: tuple[str, ...]) -> int:
    """A descriptor of ``root``/``parts``, each component opened without following a link.

    Missing directories are made, each beside the descriptor of its parent.

    Raises:
        PromotionError: a component is a link.
    """
    # The library root is the caller's, and trusted; everything beneath it is not.
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    try:
        for part in parts:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, dir_fd=fd)
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | _NO_FOLLOW, dir_fd=fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise _link_refused(root.joinpath(*parts)) from None
                raise
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def _replace(destination: Path, knowledge_root: Path, data: bytes) -> None:
    """Make ``destination`` hold exactly ``data``, never writing through a link.

    Written to a new file beside it, opened by descriptor, then renamed over it: a
    rename replaces a link at the destination rather than following it, and every
    directory on the way is held open by descriptor, so none can be swapped.

    Raises:
        PromotionError: a directory between the library and the destination is a link.
    """
    root = Path(knowledge_root)
    parts = destination.parent.relative_to(root).parts
    dir_fd = _open_dir(root, parts)
    temporary = f".{destination.name}.{os.getpid()}.promoting"
    try:
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NO_FOLLOW, 0o644, dir_fd=dir_fd
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    finally:
        os.close(dir_fd)


def _existing(destination: Path, knowledge_root: Path) -> bytes | None:
    """What ``destination`` holds now, read without following a link; ``None`` if nothing."""
    root = Path(knowledge_root)
    dir_fd = _open_dir(root, destination.parent.relative_to(root).parts)
    try:
        fd = os.open(destination.name, os.O_RDONLY | _NO_FOLLOW, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _link_refused(destination) from None
        raise
    finally:
        os.close(dir_fd)
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def _append_record(promotions_path: Path, line: str) -> None:
    """Append ``line`` to the promotion record, refusing a record that is a link."""
    promotions_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(promotions_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _NO_FOLLOW, 0o644)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _link_refused(promotions_path) from None
        raise
    with os.fdopen(fd, "a", encoding="utf-8") as log:
        log.write(line)
        log.flush()
        os.fsync(log.fileno())


def _refuse_links(destination: Path, knowledge_root: Path) -> None:
    """Refuse a destination that is, or sits beneath, a link inside the library.

    Raises:
        PromotionError: the write would be redirected somewhere else.
    """
    root = Path(knowledge_root)
    current = destination
    while True:
        if current.is_symlink():
            msg = "a promotion's destination is a link, so the write would land elsewhere"
            raise PromotionError(msg, destination=str(destination), link=str(current))
        if current == root or current.parent == current:
            return
        current = current.parent


def _apply(
    candidate_id: str,
    *,
    by: str,
    staging_root: Path,
    knowledge_root: Path,
    promotions_path: Path,
    rubric_staging_root: Path = RUBRIC_STAGING_ROOT,
) -> Path:
    """Write the candidate into the library, log the promotion, remove it from staging.

    Carries no interactivity check of its own — ``require_interactive`` is the
    caller's job, always run first for a real promotion.

    Raises:
        PromotionError: ``by`` is empty; no candidate with ``candidate_id`` is
            staged where its kind is staged; the id, the staged file or the
            destination is refused (:func:`_find`, :func:`_refuse_links`).
    """
    if not by.strip():
        msg = "promotion needs the name of the human approving it"
        raise PromotionError(msg, candidate_id=candidate_id)
    found = _find(candidate_id, Path(staging_root), Path(rubric_staging_root))
    if found is None:
        msg = "no staged candidate has this id"
        raise PromotionError(msg, candidate_id=candidate_id)
    kind, candidate, candidate_path = found
    destination = _destination(candidate.domain, kind, knowledge_root)
    # An early, readable refusal; what makes the write safe is that it goes through
    # descriptors opened without following links, at the moment of writing.
    _refuse_links(destination, Path(knowledge_root))
    text = (candidate.content.rstrip() + "\n").encode("utf-8")
    before = None if kind in ("standards", "rubric") else _existing(destination, knowledge_root)
    data = text if before is None else before + b"\n---\n\n" + text
    _replace(destination, Path(knowledge_root), data)
    event = {
        "candidate_id": candidate.candidate_id,
        "kind": kind,
        "domain": candidate.domain,
        "episode_id": candidate.episode_id,
        "destination": str(destination),
        "promoted_by": by,
        "promoted": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # The digest of the bytes written, never of a later read of the path.
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    _append_record(Path(promotions_path), json.dumps(event, sort_keys=True) + "\n")
    candidate_path.unlink()
    return destination


def promote(
    candidate_id: str,
    *,
    by: str,
    staging_root: Path = STAGING_ROOT,
    knowledge_root: Path = KNOWLEDGE_ROOT,
    promotions_path: Path | None = None,
    rubric_staging_root: Path = RUBRIC_STAGING_ROOT,
) -> Path:
    """Refuse unless interactive, then move one staged candidate into the library.

    The one function the real CLI calls. Everything it does beyond the
    interactivity check is `_apply`, tested directly and without a terminal.

    Raises:
        PromotionError: ``stdin`` is not a TTY, ``by`` is empty, or no
            candidate with ``candidate_id`` is staged.
    """
    require_interactive()
    resolved_promotions = (
        Path(promotions_path)
        if promotions_path is not None
        else Path(knowledge_root) / PROMOTIONS_NAME
    )
    return _apply(
        candidate_id,
        by=by,
        staging_root=staging_root,
        knowledge_root=knowledge_root,
        promotions_path=resolved_promotions,
        rubric_staging_root=rubric_staging_root,
    )


def promotions(
    promotions_path: Path = KNOWLEDGE_ROOT / PROMOTIONS_NAME,
) -> tuple[dict[str, str], ...]:
    """Every promotion recorded so far, oldest first; an empty tuple if none yet."""
    path = Path(promotions_path)
    if not path.is_file():
        return ()
    return tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
