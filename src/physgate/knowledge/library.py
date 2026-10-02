"""The curated library, put into a run's target at decomposition (ARCH-020, ARCH-023, ARCH-050).

A role session reads its curated content in its own worktree, which branches
from the target repository's run branch: ``loader`` names that content relative
to the worktree, because that is where a session's Read tool operates and where
the hook layer protects it. The content itself lives in the checkout the
orchestrator runs from. Nothing used to carry it across, so every target either
held a copy someone had committed by hand, or failed the reading hook.

At decomposition the orchestrator now copies exactly the always-loaded set of
every planned role, byte for byte, from that checkout into the run branch, in the
same commit as the module specifications. What was copied is what the run's
sealed harness commit holds, since a reportable run starts only from a clean
checkout; the spec commit holds the bytes.

Refused rather than guessed:

- a planned role whose curated file is missing, a link, or empty in the library:
  ARCH-050's "before dispatch is possible", caught before any session runs;
- a target that already holds something else where a copied file goes: never
  overwritten, and never trusted, since only the promotion command puts content
  into the library;
- no source checkout at all: the package carries no curated content.

This module reads and writes files; ``loader`` stays pure path arithmetic.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from physgate.knowledge import loader
from physgate.knowledge.exceptions import KnowledgeError


class LibraryError(KnowledgeError):
    """The curated library cannot be put into a run's target."""


def read_library(library: Path | None, roles: Iterable[str]) -> dict[Path, bytes]:
    """Every always-loaded file of ``roles``, read from ``library``, by relative path.

    Raises:
        LibraryError: there is no library, or a role's file is missing, a link, not
            a regular file, or holds nothing but whitespace.
    """
    if library is None:
        msg = "there is no source checkout to take the curated library from"
        raise LibraryError(msg)
    contents: dict[Path, bytes] = {}
    for role in sorted(set(roles)):
        for relative in loader.always_loaded(role):
            source = library / relative
            if source.is_symlink() or not source.is_file():
                msg = "a planned role has no curated file in the library; it cannot be dispatched"
                raise LibraryError(msg, role=role, path=relative.as_posix())
            data = source.read_bytes()
            if not data.strip():
                msg = "a planned role's curated file is empty; it cannot be dispatched"
                raise LibraryError(msg, role=role, path=relative.as_posix())
            contents[relative] = data
    return contents


def put_into(worktree: Path, contents: Mapping[Path, bytes]) -> tuple[Path, ...]:
    """Write ``contents`` under ``worktree``, after checking that nothing there conflicts.

    A file already holding exactly the same bytes is left as it is. Nothing is
    written unless every file passes, so a refusal leaves the worktree untouched.

    Returns:
        Every relative path now holding its library bytes, sorted.

    Raises:
        LibraryError: something other than a directory sits on a file's path, or a
            file is already there with other bytes, or is a link.
    """
    for relative, data in contents.items():
        _require_no_conflict(worktree, relative, data)
    for relative, data in sorted(contents.items()):
        destination = worktree / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return tuple(sorted(contents))


def _require_no_conflict(worktree: Path, relative: Path, data: bytes) -> None:
    current = worktree
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            msg = "the target holds something other than a directory where the library goes"
            raise LibraryError(msg, path=current.relative_to(worktree).as_posix())
    destination = worktree / relative
    if destination.is_symlink() or (
        destination.exists() and (not destination.is_file() or destination.read_bytes() != data)
    ):
        msg = "the target already holds a different file where the curated library goes"
        raise LibraryError(msg, path=relative.as_posix())
