"""What one writer has written to an append-only record, and the check that the path still holds it.

Each of the run's append-only records has one writer: the run-event log, the task ledger and the
approval queue's items. A writer that holds its file open would go on writing to it after anything
replaced the path, and every line from then on would land in a file no path names. A writer that
opens it for each write would append after whatever another writer added. So each writer keeps
what it knows of its file here: the file's identity (device and inode), the size it found when it
opened it, the size it has made it since, and a digest of what it has written since. Before every
write it holds the path to that, and refuses with :class:`RecordMovedError` when it does not hold.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from physgate.state.exceptions import RecordMovedError


def identity_of(path: Path) -> tuple[int, int] | None:
    """The device and inode the path names now, without following a final link, or ``None``."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    return st.st_dev, st.st_ino


class HeldFile:
    """One writer's account of the append-only file it writes."""

    def __init__(self, path: Path, fd: int | None = None) -> None:
        """Take the file as it is now: through ``fd`` if the writer holds it open, else by path.

        Raises:
            RecordMovedError: the path names something other than a regular file.
        """
        self.path = Path(path)
        st = os.fstat(fd) if fd is not None else os.lstat(self.path)
        if not stat.S_ISREG(st.st_mode):
            msg = "an append-only record is not a regular file"
            raise RecordMovedError(msg, path=str(self.path))
        self.identity: tuple[int, int] = (st.st_dev, st.st_ino)
        #: The size the file had when this writer took it: what was there before it wrote.
        self.opened: int = st.st_size
        #: The size this writer has made it: what it found, and everything it wrote since.
        self.size: int = st.st_size
        self._written = hashlib.sha256()

    def require_current(self) -> None:
        """Refuse unless the path names the file this writer holds, at the size it made it.

        Raises:
            RecordMovedError: the path names another file, or none, or the file's size moved.
        """
        try:
            st = os.lstat(self.path)
        except FileNotFoundError:
            st = None
        now = (st.st_dev, st.st_ino) if st is not None else None
        if now != self.identity or st is None or st.st_size != self.size:
            msg = "the record is no longer the file this writer holds, at the size it wrote"
            raise RecordMovedError(
                msg,
                path=str(self.path),
                held=f"{self.identity} at {self.size} bytes",
                now=f"{now} at {st.st_size if st is not None else 'no'} bytes",
            )

    def wrote(self, payload: bytes) -> None:
        """Account for ``payload``, which this writer has just appended in full."""
        self.size += len(payload)
        self._written.update(payload)

    def own_tail_holds(self) -> bool:
        """Whether the file holds, after what it held when taken, exactly what this writer wrote.

        Read afresh, by path, and held to the identity too: a file that is not the held one, or
        that is longer or shorter than what this writer made it, does not hold.
        """
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            return False
        try:
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino) != self.identity or st.st_size != self.size:
                return False
            os.lseek(fd, self.opened, os.SEEK_SET)
            digest = hashlib.sha256()
            left = self.size - self.opened
            while left > 0 and (chunk := os.read(fd, min(left, 1 << 20))):
                digest.update(chunk)
                left -= len(chunk)
            return left == 0 and digest.digest() == self._written.digest()
        finally:
            os.close(fd)
