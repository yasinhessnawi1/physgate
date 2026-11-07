"""The engine catalogue: the engines the desktop app's engine step offers, read once at start.

The file is the checkout's own ``desktop/onboarding/engines.json``, the one the desktop shell
compiles into itself. The server reads it once, when the command starts and before it listens,
and keeps the bytes' parse, digest and length in memory; the route that serves it reads nothing
at request time. So no request may read in the checkout, and the guard's request-time rule
needs no slot for it. The UI is served only from a source checkout, so the file is always where
the server can look for it.

**The read is held to fixed checks, and a failed check never stops the server.** A malformed
catalogue must not take the operator UI down for one file: the result is then ``refused``, with
a sentence, and only the screen's engine section shows the error. The checks, in order:

1. The path is built from fixed parts and judged by the allowlist's own refusal test, the one
   every request's reads are held to: a path that reaches the held-out tier or an answer key,
   or lies in an evaluation corpus, is refused before anything is opened.
2. It is reached by a walk of descriptors from the checkout: the checkout's own directory, held
   to the identity it had when the read began, then each folder below it opened relative to the
   last and never through a link, then the file itself, never through a link and without
   waiting (a pipe planted at the path would otherwise hang the start). No swap of a name above
   the file can redirect the read.
3. What was opened must be a regular file with one name on disk (a second name could be a
   refused file's), no larger than ``MAX_BYTES``, and the very file the path was judged as.
4. The bytes are strict UTF-8 and strict JSON: a repeated key, ``NaN`` and the infinities are
   refused, since the standard parser accepts all three, and the top level is an object holding
   an ``engines`` list. Nothing else of its shape is checked here: the screen's guard reads each
   field it draws on its own.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from physgate.ui.exceptions import UIError
from physgate.ui.paths import Allowlist, _open_child, _open_root

#: Where the catalogue lies in the checkout, as the answer names it: relative, never absolute.
CATALOGUE_FILE = "desktop/onboarding/engines.json"

#: The folders walked below the checkout, and the file's own name.
_FOLDERS = ("desktop", "onboarding")
_NAME = "engines.json"

#: The largest catalogue read, in bytes. Today's file is 2,243.
MAX_BYTES = 64 * 1024

#: The most of a repeated key a refusal shows: a key may be nearly as long as the file.
SHOWN_KEY = 40

State = Literal["read", "absent", "refused"]


@dataclass(frozen=True)
class EngineCatalogue:
    """What the start-time read found: the parse with its digest and length, or why not.

    ``read`` carries ``sha256``, ``length`` and ``value``; ``refused`` carries ``reason``;
    ``absent`` carries nothing. Any other combination is refused when the record is made.
    """

    state: State
    sha256: str | None = None
    length: int | None = None
    value: object = None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Refuse a record whose fields do not fit its state.

        Raises:
            UIError: the fields present are not the ones the state carries.
        """
        read = self.sha256 is not None and self.length is not None and self.value is not None
        fits = {
            "read": read and self.reason is None,
            "absent": not read and self.value is None and self.reason is None,
            "refused": self.sha256 is None
            and self.length is None
            and self.value is None
            and self.reason is not None,
        }
        if not fits.get(self.state, False):
            msg = "an engine catalogue record's fields do not fit its state"
            raise UIError(msg, state=str(self.state))


#: The catalogue of a server that has none: no checkout, or no file in it.
ABSENT = EngineCatalogue(state="absent")


class _RefusedError(UIError):
    """The catalogue fails one of the checks; the message is the sentence the route sends."""


def _refused(reason: str) -> EngineCatalogue:
    return EngineCatalogue(state="refused", reason=reason)


def _no_repeated_key(pairs: list[tuple[str, object]]) -> dict[str, object]:
    found: dict[str, object] = {}
    for key, value in pairs:
        if key in found:
            msg = f"it repeats the key {key!r}"
            raise _RefusedError(msg)
        found[key] = value
    return found


def _no_constant(name: str) -> object:
    msg = "it holds NaN or an infinity"
    raise _RefusedError(msg)


@contextmanager
def _closing(fd: int) -> Iterator[int]:
    try:
        yield fd
    finally:
        os.close(fd)


def _read_file(folder: int, identity: tuple[int, int]) -> bytes:
    """The catalogue's bytes, opened beneath ``folder`` and held to the checks of step 3.

    At most one byte more than ``MAX_BYTES`` is read, so a file is judged too large by what was
    read from it, whatever its size said before the read and however it grew since.

    Raises:
        _RefusedError: a link, not a regular file, a second name, not the file judged, or too
            large.
        OSError: the open or the read failed otherwise (no such file among them).
    """
    try:
        fd = os.open(
            _NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=folder
        )
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            msg = "it is a link"
            raise _RefusedError(msg) from None
        raise
    with _closing(fd):
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            msg = "it is not a regular file"
            raise _RefusedError(msg)
        if st.st_nlink != 1:
            msg = "it has a second name on disk"
            raise _RefusedError(msg)
        if (st.st_dev, st.st_ino) != identity:
            msg = "it changed while it was being read"
            raise _RefusedError(msg)
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_BYTES:
            chunk = os.read(fd, MAX_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    data = b"".join(chunks)
    if len(data) > MAX_BYTES:
        msg = "it is larger than 64 KiB"
        raise _RefusedError(msg)
    return data


def _walk(harness: Path, identity: tuple[int, int]) -> bytes:
    """Open the checkout, then each folder below it, then the file: step 2.

    Raises:
        _RefusedError: the checkout is not the directory the read began with, a folder on the
            way is a link or not a folder, or the file fails a check.
        OSError: a folder or the file is not there, or the read failed otherwise.
    """
    with _closing(_open_root(harness)) as root:
        st = os.fstat(root)
        if (st.st_dev, st.st_ino) != identity:
            msg = "the checkout changed while it was being read"
            raise _RefusedError(msg)
        folder = root
        opened: list[int] = []
        try:
            for name in _FOLDERS:
                try:
                    folder = _open_child(folder, name)
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                        msg = "a folder on the way to it is a link or not a folder"
                        raise _RefusedError(msg) from None
                    raise
                opened.append(folder)
            judged = os.lstat(harness / CATALOGUE_FILE)
            return _read_file(folder, (judged.st_dev, judged.st_ino))
        finally:
            for fd in opened:
                os.close(fd)


def _parse(data: bytes) -> object:
    """The bytes as strict JSON, an object holding an ``engines`` list: step 4.

    Raises:
        _RefusedError: not UTF-8, not JSON, a repeated key, NaN or an infinity, nested too
            deeply, not an object, or no ``engines`` list.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        msg = "it is not UTF-8"
        raise _RefusedError(msg) from None
    try:
        value = json.loads(text, object_pairs_hook=_no_repeated_key, parse_constant=_no_constant)
    except json.JSONDecodeError as exc:
        msg = f"it is not JSON: line {exc.lineno} column {exc.colno}"
        raise _RefusedError(msg) from None
    except RecursionError:
        msg = "it is nested too deeply to read"
        raise _RefusedError(msg) from None
    if not isinstance(value, dict):
        msg = "its top level is not an object"
        raise _RefusedError(msg)
    if not isinstance(value.get("engines"), list):
        msg = "it lists no engines"
        raise _RefusedError(msg)
    return value


def load(harness: Path | None, refused: Allowlist) -> EngineCatalogue:
    """The checkout's engine catalogue, read once, or why it is absent or refused.

    Called by the command after the allowlist is built and before the server listens. It never
    raises for anything the file holds or how it lies on disk: a refusal is a result.

    Args:
        harness: the source checkout the server runs from, or ``None`` with none.
        refused: the allowlist whose refusal test the path is held to.
    """
    if harness is None:
        return ABSENT
    path = harness / CATALOGUE_FILE
    text = os.fspath(path)
    try:
        reason = refused._refusal(text, os.path.realpath(text))
        if reason is not None:
            return _refused(f"it lies where nothing may be read: {reason}")
        start = os.stat(harness)
        data = _walk(harness, (start.st_dev, start.st_ino))
        value = _parse(data)
    except _RefusedError as exc:
        return _refused(str(exc))
    except FileNotFoundError:
        return ABSENT
    except OSError as exc:
        return _refused(f"it could not be read: {os.strerror(exc.errno or 0)}")
    return EngineCatalogue(
        state="read", sha256=hashlib.sha256(data).hexdigest(), length=len(data), value=value
    )
