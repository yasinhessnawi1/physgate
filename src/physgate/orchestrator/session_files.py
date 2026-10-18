"""A session's own files, read and rewritten without following a link a session planted.

Every file here lives in a session's own directory, which the session's processes can write
while it runs: its captured stream, its records, its credential files. Each is reached
through its directory without following a link (``credentials.open_in_session``) and opened
without following one, so a link a session's process planted is never read or written
through, and nothing outside the session's own directory is touched.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from physgate.orchestrator.credentials import REDACTED_TEXT, open_in_session
from physgate.orchestrator.exceptions import InvocationError

#: What a secret found in a session's file is replaced with, as bytes.
REDACTED = REDACTED_TEXT.encode()


def read_session_file(path: Path) -> bytes:
    """The bytes of a session's own file, read without following a link (``b""`` if absent).

    The file is reached as :func:`open_in_session` reaches its directory, and opened without
    following a link: a link a session's process planted there is never read through.

    Raises:
        InvocationError: the file, or a directory on the way, is a link or not a regular file.
    """
    directory = open_in_session(path.parent)
    if directory is None:
        return b""
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except FileNotFoundError:
            return b""
        except OSError as exc:
            msg = "a session's file is a link or cannot be opened; it is not read through"
            raise InvocationError(msg, path=str(path), error=repr(exc)) from exc
    finally:
        os.close(directory)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            msg = "a session's file is not a regular file; it is not read"
            raise InvocationError(msg, path=str(path))
        chunks = []
        while chunk := os.read(fd, 1 << 20):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def redact(path: Path, secret: str | None) -> None:
    """Replace every occurrence of ``secret`` in the file at ``path``, a session's own file.

    The file is reached through its directory without following a link, and opened without
    following one (:func:`open_in_session`): a link planted at its name is never written
    through.

    Raises:
        InvocationError: the file, or a directory on the way, is a link.
    """
    if not secret:
        return
    directory = open_in_session(path.parent)
    if directory is None:
        return
    try:
        try:
            fd = os.open(path.name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory)
        except FileNotFoundError:
            return
        except OSError as exc:
            msg = "a session's file is a link or cannot be opened; it is not written through"
            raise InvocationError(msg, path=str(path), error=repr(exc)) from exc
    finally:
        os.close(directory)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            msg = "a session's file is not a regular file; it is not written"
            raise InvocationError(msg, path=str(path))
        chunks = []
        while chunk := os.read(fd, 1 << 20):
            chunks.append(chunk)
        data = b"".join(chunks)
        if secret.encode() in data:
            redacted = data.replace(secret.encode(), REDACTED)
            os.ftruncate(fd, 0)
            os.pwrite(fd, redacted, 0)
    finally:
        os.close(fd)
