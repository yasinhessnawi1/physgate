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

**The window between a check and an open.** :meth:`Allowlist.resolve` judges a path
and returns it; a reader then opens it by name. A same-user process that swaps a
checked file, or a directory above it, for a link in that moment would have the
reader open the link's target. For the read routes this stays a known window: they
reuse the package's readers, which open by name, and the guard holds each open to
the same rule. For anything that writes it is closed: :meth:`Allowlist.open_directory`
opens a directory by walking down to it from the root, one component at a time,
never through a link, and checks that what it reached is the directory that was
judged. Whatever happens to the names afterwards, the descriptor it returns is that
directory, and every file the caller then opens relative to it is beneath it.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import physgate
from physgate.hooks.paths import reaches
from physgate.orchestrator.credentials import KEY_FILE, KEY_HELPER, LOGIN_FILE
from physgate.ui.exceptions import PathRefusedError, StartupRefusedError

#: File names never read, wherever they sit: a running session's credential files
#: (inside the run directory while it runs) and the environment file.
SECRET_NAMES = frozenset(name.casefold() for name in (LOGIN_FILE, KEY_FILE, KEY_HELPER, ".env"))

#: A directory of this name holds evaluation corpora, which carry their answers.
CORPUS_DIR = "corpora"

#: Files a request may open besides the roots: the interpreter's own (a module imported late)
#: and this package's (its recorded price sheets). Nothing in a run directory is among them.
INTERPRETER_PATHS = tuple(
    sorted(
        {
            os.path.realpath(p)
            for p in (
                sys.prefix,
                sys.base_prefix,
                sys.exec_prefix,
                sys.base_exec_prefix,
                os.path.dirname(physgate.__file__),
            )
        }
    )
)


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


#: How the walk opens each directory below the root: read-only, a directory, and never
#: through a link. A component swapped for a link after the path was judged fails here.
WALK_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

#: How the walk opens the root itself. A root is taken as the operator gave it and made
#: real at start, so its own name is followed; the descriptor is then held to the
#: (device, inode) the root had at start instead.
ROOT_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC


def _open_root(path: Path) -> int:
    """Open a root's directory. Its own function so a test can act just before it."""
    return os.open(path, ROOT_FLAGS)


def _open_child(parent: int, name: str) -> int:
    """Open the directory ``name`` beneath ``parent``, refusing a link. A test seam as well."""
    return os.open(name, WALK_FLAGS, dir_fd=parent)


def _identity(fd: int) -> tuple[int, int]:
    st = os.fstat(fd)
    return st.st_dev, st.st_ino


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

    def readable(self, path: str) -> bool:
        """Whether a request may open or list ``path``: the guard's rule for every such call.

        The refusals come first and hold everywhere: a path that reaches the held-out tier or
        an answer key, lies in a corpus, or names a credential is refused even beneath the
        interpreter's own files, so the exception below can never be wider than the refusals.
        A relative path is refused: the call that names it may resolve it against a directory
        handle the audit event does not carry, so the working directory would be the wrong
        thing to judge it by. Then the interpreter's and this package's own files are readable
        (a late import, the recorded price sheets), and anything else only if the allowlist
        resolves it (beneath a root, links followed). This holds a handler that forgot to call
        :meth:`resolve` to the same rule at the call itself.
        """
        if _has_nul(path) or not os.path.isabs(path):
            return False
        try:
            real = os.path.realpath(path)
            refused = self._refusal(path, real) is not None
        except OSError:
            # The path changed while it was being judged (a component removed between two
            # steps of resolving it). Judged as refused, never passed on as an error.
            return False
        if refused:
            return False
        if any(real == base or real.startswith(base + os.sep) for base in INTERPRETER_PATHS):
            return True
        try:
            self.resolve(path)
        except PathRefusedError:
            return False
        return True

    def _refusal(self, text: str, real: str) -> str | None:
        """Why ``text`` (really ``real``) may never be read, wherever it lies, or ``None``."""
        for refused in self.refused:
            if reaches(real, refused) or reaches(text, refused):
                return "the path reaches a path nothing may read"
        if _has_corpus_component(real) or _has_corpus_component(text):
            return "the path lies inside an evaluation corpus"
        if os.path.basename(real).casefold() in SECRET_NAMES:
            return "the path names a credential or environment file"
        return None

    def resolve(self, path: Path | str) -> Path:
        """The real path of ``path`` if the server may read it; otherwise refuse.

        Resolves first, then checks the allowlist, then the refused set. A path
        that does not exist yet is judged by its nearest existing ancestor and
        returned; whether it is there is the reader's question.

        Raises:
            PathRefusedError: the path holds a NUL byte, is relative, lies outside
                every root, reaches a refused path, names a credential, is a file
                with more than one name on disk, or changed while it was judged.
        """
        text = os.fspath(path)
        if _has_nul(text):
            msg = "a path holding a NUL byte names no file"
            raise PathRefusedError(msg, path=repr(text))
        if not os.path.isabs(text):
            msg = "a relative path is refused: nothing here resolves it against a directory"
            raise PathRefusedError(msg, path=text)
        try:
            return self._judge(text)
        except OSError as exc:
            # Resolving a path whose components are being removed or swapped can raise from
            # inside the standard library's own resolution. That is a judgement that could not
            # finish, so it is a refusal, never a raw error past this boundary.
            msg = "the path changed while it was being judged, so it is refused"
            raise PathRefusedError(msg, path=text, reason=os.strerror(exc.errno or 0)) from None

    def _judge(self, text: str) -> Path:
        """:meth:`resolve`'s checks on an absolute path free of NUL bytes."""
        real = os.path.realpath(text)
        ids = set(_ancestor_ids(real))
        if not any(root.ids in ids for root in self.roots):
            msg = "the path is outside every root the server was given"
            raise PathRefusedError(msg, path=text)
        refusal = self._refusal(text, real)
        if refusal is not None:
            raise PathRefusedError(refusal, path=text)
        try:
            st = os.stat(real)
        except OSError:
            return Path(real)
        if os.path.isfile(real) and st.st_nlink > 1:
            msg = "the file has more than one name on disk, so its other name may be refused"
            raise PathRefusedError(msg, path=text)
        return Path(real)

    def open_directory(self, path: Path | str) -> int:
        """A descriptor of the directory at ``path``, reached so that no swap can redirect it.

        In order: the path is judged by :meth:`resolve`; the real path it returns must then be
        a directory and not a link (``lstat``), and its (device, inode) is what was approved.
        The walk opens the root the path lies beneath and holds it to the (device, inode) the
        root had at start, then opens each component below it relative to the last, never
        through a link. The directory it reaches must be the one approved. So a component
        swapped for a link after the judgement fails at its own step, the root replaced by
        another directory fails at the root, and the directory itself replaced by another real
        directory fails at the end. The caller owns the descriptor and closes it.

        Raises:
            PathRefusedError: the path is refused by :meth:`resolve`, is not a real directory,
                or the walk does not reach the directory that was approved.
        """
        real = self.resolve(path)
        try:
            st: os.stat_result | None = os.lstat(real)
        except OSError:
            st = None
        if st is None or not stat.S_ISDIR(st.st_mode):
            msg = "the path is not a real directory, so nothing is opened beneath it"
            raise PathRefusedError(msg, path=str(real))
        approved = (st.st_dev, st.st_ino)
        root, below = self._beneath(real)
        fd = _open_root(root.path)
        try:
            if _identity(fd) != root.ids:
                msg = "the root is no longer the directory the server started with"
                raise PathRefusedError(msg, path=str(real), root=str(root.path))
            for name in below:
                try:
                    child = _open_child(fd, name)
                except OSError as exc:
                    msg = "a directory on the way is now a link, or is gone"
                    raise PathRefusedError(
                        msg, path=str(real), component=name, reason=os.strerror(exc.errno or 0)
                    ) from None
                os.close(fd)
                fd = child
            if _identity(fd) != approved:
                msg = "the walk reached a different directory from the one that was approved"
                raise PathRefusedError(msg, path=str(real))
        except BaseException:
            os.close(fd)
            raise
        return fd

    @contextmanager
    def opened_directory(self, path: Path | str) -> Iterator[int]:
        """:meth:`open_directory`, its descriptor closed when the block ends."""
        fd = self.open_directory(path)
        try:
            yield fd
        finally:
            os.close(fd)

    def _beneath(self, real: Path) -> tuple[Root, tuple[str, ...]]:
        """The nearest root at or above ``real``, by (device, inode), and the names below it.

        Raises:
            PathRefusedError: no directory at or above ``real`` is a root any longer.
        """
        parts = real.parts
        for depth in range(len(parts), 0, -1):
            try:
                st = os.stat(Path(*parts[:depth]))
            except OSError:
                continue
            for root in self.roots:
                if root.ids == (st.st_dev, st.st_ino):
                    return root, tuple(parts[depth:])
        msg = "the path is outside every root the server was given"
        raise PathRefusedError(msg, path=str(real))
