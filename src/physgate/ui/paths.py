"""Which files the operator UI may read: an allowlist of roots, and what it never reads.

The server reaches a file only through :meth:`Allowlist.resolve`, and nothing a
request carries is ever a filesystem path: runs are addressed by the position of
their root and the name of their directory, sessions by their id. The paths that
do arrive here come from the server itself or from a run's own records, and a
record can be forged, so each is held to three tests in a fixed order:

1. **Resolve first.** The path is made real (``os.path.realpath``) before
   anything is checked, so a symlink inside an allowed root that points out of
   it, or a ``..`` that climbs out, is judged by where it lands and not by how it
   is spelt. Checking first and resolving afterwards would pass exactly those.
2. **The allowlist.** The real path must lie beneath a root named on the command
   line, by device and inode: the root's own (device, inode), recorded at start,
   must be one of the directories above the path. That follows a case variant
   on a volume that folds case and refuses one on a volume that does not, and it
   cannot be satisfied by a string that merely starts with the root's name. A
   permit must never be wider than the filesystem says, so no case folding here.
3. **The refused set.** The held-out tier, the evaluation corpora that carry
   their answers, and the harness checkout's own ``corpora`` directory are
   refused by the very test the file-tool hook refuses by (case folded, every
   spelling, and by inode), which errs toward refusing. Any path with a
   ``corpora`` component is refused as well, and so is any file named like a
   credential (a session's login file or its key files while it runs) or like
   the environment file, and any file with a second name on disk, since a hard
   link can give a refused file a name inside an allowed root.

At start, a root that contains a refused path or lies inside one refuses to
start, so the two sets can never overlap.

What this cannot close: the moment between a check and the reader's own open. A
same-user process that swaps a checked file for a link in that window is the
same-user limit the hook layer already records; nothing here pretends otherwise.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from physgate.hooks.paths import reaches
from physgate.orchestrator.credentials import KEY_FILE, KEY_HELPER, LOGIN_FILE
from physgate.ui.exceptions import PathRefusedError, StartupRefusedError

#: File names never read, wherever they sit: a running session's credential files
#: (inside the run directory while it runs) and the environment file.
SECRET_NAMES = frozenset(name.casefold() for name in (LOGIN_FILE, KEY_FILE, KEY_HELPER, ".env"))

#: A directory of this name holds evaluation corpora, which carry their answers.
CORPUS_DIR = "corpora"


def _has_nul(text: str) -> bool:
    return "\x00" in text


def _ancestor_ids(real: str) -> Iterator[tuple[int, int]]:
    """(device, inode) of the nearest existing directory at or above ``real``, and upwards."""
    current = real
    while not os.path.exists(current) and current != os.path.dirname(current):
        current = os.path.dirname(current)
    while True:
        try:
            st = os.stat(current)
        except OSError:
            return
        yield st.st_dev, st.st_ino
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def _has_corpus_component(path: str) -> bool:
    return any(part.casefold() == CORPUS_DIR for part in Path(path).parts)


@dataclass(frozen=True)
class Root:
    """One allowed root: its real path and the (device, inode) it had at start."""

    path: Path
    ids: tuple[int, int]


@dataclass(frozen=True)
class Allowlist:
    """The roots the server may read beneath, and the paths it never reads."""

    roots: tuple[Root, ...]
    refused: tuple[str, ...]

    @classmethod
    def build(
        cls,
        roots: Sequence[str],
        *,
        held_out: Sequence[str],
        answer_keys: Sequence[str],
        harness: Path | None,
    ) -> Allowlist:
        """Check the command line's paths and build the allowlist, or refuse to start.

        Held-out paths and answer keys are taken the way the hooks take them:
        explicit and absolute. The harness checkout's ``corpora`` is always refused.

        Raises:
            StartupRefusedError: no root; a root missing, not a directory, or holding a
                NUL; a refused path not absolute; or a root that contains a refused
                path or lies inside one.
        """
        if not roots:
            msg = "name at least one root to read"
            raise StartupRefusedError(msg)
        refused: list[str] = []
        for given in (*held_out, *answer_keys):
            if _has_nul(given) or not os.path.isabs(given):
                msg = "a held-out path or answer key is taken as an explicit absolute path"
                raise StartupRefusedError(msg, path=given)
            refused.append(os.path.normpath(given))
        if harness is not None:
            refused.append(str(harness / CORPUS_DIR))
        built: list[Root] = []
        for given in roots:
            if _has_nul(given):
                msg = "a root holding a NUL byte names no directory"
                raise StartupRefusedError(msg, root=repr(given))
            real = os.path.realpath(os.path.abspath(given))
            if not os.path.isdir(real):
                msg = "a root must be an existing directory"
                raise StartupRefusedError(msg, root=given)
            if _has_corpus_component(real):
                msg = "a root may not lie inside an evaluation corpus"
                raise StartupRefusedError(msg, root=given)
            for path in refused:
                if reaches(real, path) or reaches(path, real):
                    msg = (
                        "a root overlaps a path nothing may read: it contains it or lies inside it"
                    )
                    raise StartupRefusedError(msg, root=given, refused=path)
            st = os.stat(real)
            built.append(Root(path=Path(real), ids=(st.st_dev, st.st_ino)))
        return cls(roots=tuple(built), refused=tuple(refused))

    def resolve(self, path: Path | str) -> Path:
        """The real path of ``path`` if the server may read it; otherwise refuse.

        Resolves first, then checks the allowlist, then the refused set. A path
        that does not exist yet is judged by its nearest existing ancestor and
        returned; whether it is there is the reader's question.

        Raises:
            PathRefusedError: the path holds a NUL byte, is relative, lies outside
                every root, reaches a refused path, names a credential, or is a
                file with more than one name on disk.
        """
        text = os.fspath(path)
        if _has_nul(text):
            msg = "a path holding a NUL byte names no file"
            raise PathRefusedError(msg, path=repr(text))
        if not os.path.isabs(text):
            msg = "a relative path is refused: nothing here resolves it against a directory"
            raise PathRefusedError(msg, path=text)
        real = os.path.realpath(text)
        ids = set(_ancestor_ids(real))
        if not any(root.ids in ids for root in self.roots):
            msg = "the path is outside every root the server was given"
            raise PathRefusedError(msg, path=text)
        for refused in self.refused:
            if reaches(real, refused) or reaches(text, refused):
                msg = "the path reaches a path nothing may read"
                raise PathRefusedError(msg, path=text)
        if _has_corpus_component(real) or _has_corpus_component(text):
            msg = "the path lies inside an evaluation corpus"
            raise PathRefusedError(msg, path=text)
        if os.path.basename(real).casefold() in SECRET_NAMES:
            msg = "the path names a credential or environment file"
            raise PathRefusedError(msg, path=text)
        try:
            st = os.stat(real)
        except OSError:
            return Path(real)
        if os.path.isfile(real) and st.st_nlink > 1:
            msg = "the file has more than one name on disk, so its other name may be refused"
            raise PathRefusedError(msg, path=text)
        return Path(real)
