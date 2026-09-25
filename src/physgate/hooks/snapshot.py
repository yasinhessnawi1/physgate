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
import json
import os
import stat
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any

Signature = tuple[str, int, int, int, int, int, int, int]


class Entry:
    """One path in a protected tree as it stood."""

    __slots__ = ("digest", "link", "signature")

    def __init__(self, signature: Signature, digest: str | None, link: str | None) -> None:
        """The signature, a regular file's sha256, and a symlink's target."""
        self.signature = signature
        self.digest = digest
        self.link = link


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
    if stat.S_ISDIR(st.st_mode):
        yield from _below(root)


def _below(directory: str) -> Iterator[tuple[str, os.stat_result]]:
    # One listing that hands back each entry's joined path, then the same
    # ``lstat`` per entry as ever: the sentinel walks every protected tree at
    # every hook, so the path building happens in C rather than here.
    try:
        with os.scandir(directory) as listing:
            entries = sorted(listing, key=lambda entry: entry.name)
    except OSError:
        return
    for entry in entries:
        try:
            st = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        yield entry.path, st
        if stat.S_ISDIR(st.st_mode):
            yield from _below(entry.path)


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
    """Bytes of protected files, content-addressed, so a revert has them to hand.

    **One pack file per batch, not one file per blob.** The session's first hook
    keeps the bytes of every protected file, a few hundred of them, and a file
    each cost a create and a rename apiece: 587 ms median for that hook on the
    server, where the state directory sat on a network filesystem and a rename
    took 1.6 ms. Now a batch is one pack file, created exclusively under a name
    never used before and never rewritten, plus one index naming each digest's
    pack, offset and length, replaced whole. A pack the index does not name yet
    (a hook killed between the two writes) is never read.
    """

    INDEX = "index.json"

    def __init__(self, directory: str) -> None:
        """Keep blobs under ``directory``."""
        self.directory = directory
        os.makedirs(directory, exist_ok=True)
        self._index: dict[str, list[Any]] | None = None

    def _load(self) -> dict[str, list[Any]]:
        if self._index is None:
            path = os.path.join(self.directory, self.INDEX)
            if os.path.exists(path):
                with open(path) as handle:
                    self._index = json.loads(handle.read())
            else:
                self._index = {}
        return self._index

    def keep(self, path: str) -> str:
        """Store the bytes of ``path``; return their digest."""
        return self.keep_all([path])[path]

    def keep_all(self, paths: list[str]) -> dict[str, str]:
        """Store the bytes of every path in one pack; return each path's digest."""
        index = self._load()
        pack = f"pack-{os.urandom(12).hex()}"
        chunks: list[bytes] = []
        added: dict[str, list[Any]] = {}
        digests: dict[str, str] = {}
        offset = 0
        for path in paths:
            with open(path, "rb") as handle:
                data = handle.read()
            digest = hashlib.sha256(data).hexdigest()
            digests[path] = digest
            if digest in index or digest in added:
                continue
            added[digest] = [pack, offset, len(data)]
            chunks.append(data)
            offset += len(data)
        if added:
            fd = os.open(
                os.path.join(self.directory, pack), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            try:
                os.write(fd, b"".join(chunks))
            finally:
                os.close(fd)
            index.update(added)
            tmp = os.path.join(self.directory, f".{self.INDEX}.tmp")
            with open(tmp, "w") as handle:
                handle.write(json.dumps(index, sort_keys=True))
            os.replace(tmp, os.path.join(self.directory, self.INDEX))
        return digests

    def read(self, digest: str) -> bytes:
        """The bytes kept under ``digest``, checked against it."""
        pack, offset, length = self._load()[digest]
        with open(os.path.join(self.directory, pack), "rb") as source:
            source.seek(offset)
            data = source.read(length)
        if hashlib.sha256(data).hexdigest() != digest:
            msg = f"the kept bytes for {digest} do not match it"
            raise OSError(msg)
        return data

    def restore(self, path: str, digest: str, mode: int) -> None:
        """Replace ``path`` with the stored bytes, as a new file with ``mode``."""
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        tmp = os.path.join(parent, f".{os.path.basename(path)}.sentinel-restore")
        data = self.read(digest)
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)


def record(roots: list[str], blobs: BlobStore) -> dict[str, Entry]:
    """Everything under ``roots``, with the bytes of every regular file kept in one pack."""
    found: dict[str, tuple[Signature, str | None]] = {}
    for root in roots:
        for path, st in walk(root):
            sig = signature(st)
            found[path] = (sig, os.readlink(path) if sig[0] == "link" else None)
    digests = blobs.keep_all([p for p, (sig, _) in found.items() if sig[0] == "file"])
    return {path: Entry(sig, digests.get(path), link) for path, (sig, link) in found.items()}


def quarantine(path: str, directory: str) -> str:
    """Move ``path`` into ``directory`` under a name never used before; return it."""
    # Imported here: a quarantine is rare, and the module is not free to load on
    # every hook's hot path.
    import shutil

    os.makedirs(directory, exist_ok=True)
    n = 1
    while True:
        target = os.path.join(directory, f"{n:04d}-{os.path.basename(path)}")
        if not os.path.lexists(target):
            # A move, which copies and then removes when the quarantine is on
            # another volume from the protected tree.
            shutil.move(path, target)
            return target
        n += 1
