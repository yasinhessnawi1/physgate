"""What the sentinel records about a protected tree, and how it puts one back.

**Detection is by stat signature, not by content.** Measured against eleven
attacks on a protected file, a signature of (type, mode, device, inode, size,
modification time, change time, link count), taken with ``lstat`` over a walk
that never follows a link, caught all eleven: a write followed by restoring the
modification time (the change time moves, and a user cannot set it), a hard
link made elsewhere (the link count and change time move), a file or a
directory swapped for a symlink, a mode change. A content hash that followed
links missed four of them. Content is hashed only when a signature has moved,
to tell a real change from a touch.

**A file is put back by replacing it, never by writing into it.** Measured:
writing the old bytes back into a file keeps a hard link to it alive, so the
alias that was used to change it can change it again; replacing the file gives
it a new inode and breaks the alias.

**Nothing is deleted.** Something new inside a protected tree, or something of
the wrong type where a file was, is moved into the session's quarantine under a
name that is never reused, so what an agent planted is kept as evidence.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

Signature = tuple[str, int, int, int, int, int, int, int]


@dataclass(frozen=True)
class Entry:
    """One path in a protected tree as it stood."""

    signature: Signature
    digest: str | None  # sha256 of a regular file's bytes
    link: str | None  # a symlink's target


def signature(st: os.stat_result) -> Signature:
    """The stat signature of an ``lstat`` result."""
    kind = (
        "link"
        if stat.S_ISLNK(st.st_mode)
        else "dir"
        if stat.S_ISDIR(st.st_mode)
        else "file"
        if stat.S_ISREG(st.st_mode)
        else "other"
    )
    return (
        kind,
        stat.S_IMODE(st.st_mode),
        st.st_dev,
        st.st_ino,
        st.st_size,
        st.st_mtime_ns,
        st.st_ctime_ns,
        st.st_nlink,
    )


def walk(root: str) -> Iterator[tuple[str, os.stat_result]]:
    """``root`` and everything beneath it, by ``lstat``, never following a link."""
    try:
        st = os.lstat(root)
    except FileNotFoundError:
        return
    yield root, st
    if not stat.S_ISDIR(st.st_mode):
        return
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return
    for name in names:
        yield from walk(os.path.join(root, name))


def signatures(roots: list[str]) -> dict[str, Signature]:
    """The signature of every path under ``roots``."""
    return {path: signature(st) for root in roots for path, st in walk(root)}


def file_digest(path: str) -> str:
    """The sha256 of a file's bytes, read without following a final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        h = hashlib.sha256()
        while chunk := os.read(fd, 1 << 20):
            h.update(chunk)
        return h.hexdigest()
    finally:
        os.close(fd)


class BlobStore:
    """Bytes of protected files, content-addressed, so a revert has them to hand."""

    def __init__(self, directory: Path) -> None:
        """Keep blobs under ``directory``."""
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def keep(self, path: str) -> str:
        """Store the bytes of ``path``; return their digest."""
        data = Path(path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        blob = self.directory / digest
        if not blob.exists():
            tmp = self.directory / f".{digest}.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, blob)
        return digest

    def restore(self, path: str, digest: str, mode: int) -> None:
        """Replace ``path`` with the stored bytes, as a new file with ``mode``."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".{target.name}.sentinel-restore"
        tmp.write_bytes((self.directory / digest).read_bytes())
        os.chmod(tmp, mode)
        os.replace(tmp, target)


def record(roots: list[str], blobs: BlobStore) -> dict[str, Entry]:
    """Everything under ``roots``, with the bytes of each regular file kept."""
    out = {}
    for root in roots:
        for path, st in walk(root):
            sig = signature(st)
            digest = blobs.keep(path) if sig[0] == "file" else None
            link = os.readlink(path) if sig[0] == "link" else None
            out[path] = Entry(sig, digest, link)
    return out


def quarantine(path: str, directory: Path) -> str:
    """Move ``path`` into ``directory`` under a name never used before; return it."""
    directory.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        target = directory / f"{n:04d}-{os.path.basename(path)}"
        if not os.path.lexists(target):
            # A move, which copies and then removes when the quarantine is on
            # another volume from the protected tree.
            shutil.move(path, target)
            return str(target)
        n += 1
