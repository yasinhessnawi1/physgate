"""Reading a file a session's process could have reached: the one way the harness reads one.

A session may leave anything at a name the harness reads after it: a link (at the name or on
the way to it), a directory, a named pipe, a file grown without bound, a second name for a file
elsewhere. Every such read goes through :func:`open_beneath`: the walk starts at a directory
the harness made and names each component below it, so no component is followed as a path;
each directory is opened without following a link (and, where the caller holds what it made,
checked to be that very directory), the file itself without following a link and without
waiting for a writer, and it is judged from the descriptor it was opened as: a regular file,
with no other name. :func:`read_beneath` then reads it under a size bound.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

#: Why a file was not read: it is not there, it is not the file itself (a link, a directory, a
#: pipe, a file with another name), it is larger than the bound, or a directory on the way is
#: not the one the harness made.
Refusal = Literal["absent", "not_a_file", "too_large", "moved"]

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC


class FileRefused(Exception):  # noqa: N818 - a refusal, not an error of the harness's own
    """A file beneath a session's place that is not read, and why (:data:`Refusal`)."""

    def __init__(self, kind: Refusal, detail: str = "", *, directory: bool = False) -> None:
        """Refused for ``kind``; ``detail`` says what the filesystem said, never a path.

        ``directory`` is true where a directory on the way was refused, not the file itself.
        """
        super().__init__(kind if not detail else f"{kind}: {detail}")
        self.kind: Refusal = kind
        self.directory = directory


def _plain(name: str) -> str:
    if not name or name in {".", ".."} or "/" in name or "\0" in name:
        msg = f"{name!r} is not one plain component of a path"
        raise ValueError(msg)
    return name


def open_beneath(
    anchor: Path,
    names: Sequence[str],
    *,
    write: bool = False,
    identity: Sequence[tuple[int, int] | None] = (),
) -> int:
    """A descriptor on the file ``anchor/names[0]/.../names[-1]``, judged before it is returned.

    ``anchor`` is the harness's own directory and is opened as named; every name below it is
    one plain component, opened without following a link. ``identity`` gives, in order, the
    device and inode the anchor and each directory below it must have (``None`` skips one).
    The file is opened without waiting on a named pipe; it must be a regular file with one link.

    Raises:
        FileRefused: the file or a directory on the way is absent, is not what it must be,
            or is not the directory the harness made.
        ValueError: a name is not one plain component.
    """
    *directories, last = [_plain(n) for n in names]
    if len(identity) > len(directories) + 1:
        msg = "more identities than directories on the way"
        raise ValueError(msg)
    held: list[int] = []
    try:
        try:
            held.append(os.open(anchor, _DIRECTORY))
            for name in directories:
                held.append(os.open(name, _DIRECTORY | os.O_NOFOLLOW, dir_fd=held[-1]))
        except FileNotFoundError:
            raise FileRefused("absent") from None
        except OSError as exc:
            # A link (ELOOP) or a file (ENOTDIR) where a directory must be.
            raise FileRefused("not_a_file", exc.strerror or "", directory=True) from None
        for fd, want in zip(held, identity, strict=False):
            info = os.fstat(fd)
            if want is not None and (info.st_dev, info.st_ino) != want:
                raise FileRefused("moved", directory=True)
        mode = (os.O_RDWR if write else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            fd = os.open(last, mode | os.O_CLOEXEC, dir_fd=held[-1])
        except FileNotFoundError:
            raise FileRefused("absent") from None
        except OSError as exc:
            # A link (ELOOP), a directory opened to write (EISDIR), or nothing that opens.
            raise FileRefused("not_a_file", exc.strerror or "") from None
    finally:
        for each in held:
            os.close(each)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise FileRefused("not_a_file", "not a regular file")
        # A second name for the file: a session that can make a hard link to a file outside
        # its place (link(2) asks for no read of the file it names) would hand the harness
        # that file's bytes under a name in its own place. Measured with the real binary, the
        # macOS layer refuses a link to a withheld file; the Linux layer is not shown to, and
        # without the OS layer nothing stops a session's shell. So a file with another link
        # is never taken as the session's own.
        if info.st_nlink != 1:
            raise FileRefused("not_a_file", "the file has another link")
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_beneath(
    anchor: Path,
    names: Sequence[str],
    *,
    limit: int,
    identity: Sequence[tuple[int, int] | None] = (),
) -> bytes:
    """The bytes of the file :func:`open_beneath` opens, read once and no more than ``limit``.

    Raises:
        FileRefused: as :func:`open_beneath`, or ``too_large``: the file is larger than ``limit``
            when judged or when read.
    """
    fd = open_beneath(anchor, names, identity=identity)
    try:
        return read_bounded(fd, limit)
    finally:
        os.close(fd)


def read_bounded(fd: int, limit: int) -> bytes:
    """Everything ``fd`` holds from its start, refused if more than ``limit`` bytes.

    Raises:
        FileRefused: ``too_large``.
    """
    if os.fstat(fd).st_size > limit:
        raise FileRefused("too_large")
    chunks: list[bytes] = []
    size = 0
    while size <= limit and (chunk := os.pread(fd, min(1 << 20, limit + 1 - size), size)):
        chunks.append(chunk)
        size += len(chunk)
    if size > limit:
        raise FileRefused("too_large")
    return b"".join(chunks)
