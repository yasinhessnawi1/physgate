"""The enforcement code a hook measurement is about, named by its git tree hash.

A measurement of the hooks (an attempt corpus driven against a harness version) is evidence
about the code it ran: the hook package as it stood. The same harness version with changed
hook code is not what was measured, so a run records the tree hash of the hook package it
has, beside the one the measurement names, and claims the hooks held only when the two are
the same.

The hash is git's own tree id, computed from the files as they stand on disk, so a reader
checks a recorded value with ``git rev-parse <commit>:src/physgate/hooks`` and an
uncommitted change shows as a different tree. Byte-compiled files and the platform's folder
metadata are left out, as the repository's ignore rules leave them out.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import physgate

#: The enforcement code a hook measurement puts on trial: the hook package.
ENFORCEMENT_PACKAGE = Path(physgate.__file__).resolve().parent / "hooks"

#: What git never holds of a source tree here (the repository ignores them).
_IGNORED_NAMES = frozenset({"__pycache__", ".DS_Store"})
_IGNORED_SUFFIXES = (".pyc", ".pyo")


def _object(kind: bytes, body: bytes) -> bytes:
    return hashlib.sha1(kind + b" " + str(len(body)).encode() + b"\0" + body).digest()  # noqa: S324 - git's object id


def _tree(directory: Path) -> bytes | None:
    """The tree object id of ``directory``'s kept files, or ``None`` if it keeps none."""
    entries: list[tuple[bytes, bytes, bytes]] = []
    for child in directory.iterdir():
        name = child.name
        if name in _IGNORED_NAMES or name.endswith(_IGNORED_SUFFIXES):
            continue
        info = child.lstat()
        if stat.S_ISLNK(info.st_mode):
            mode, oid = b"120000", _object(b"blob", os.readlink(child).encode())
            key = name.encode()
        elif stat.S_ISDIR(info.st_mode):
            sub = _tree(child)
            if sub is None:  # git holds no empty directory
                continue
            mode, oid, key = b"40000", sub, name.encode() + b"/"
        else:
            mode = b"100755" if info.st_mode & stat.S_IXUSR else b"100644"
            oid, key = _object(b"blob", child.read_bytes()), name.encode()
        entries.append((key, mode + b" " + name.encode(), oid))
    if not entries:
        return None
    body = b"".join(head + b"\0" + oid for _, head, oid in sorted(entries))
    return _object(b"tree", body)


def tree_hash(directory: Path) -> str:
    """Git's tree id for ``directory`` as its files stand on disk, ignored files left out."""
    found = _tree(directory)
    return (found or _object(b"tree", b"")).hex()


def enforcement_tree() -> str:
    """The tree hash of the hook package this process runs with."""
    return tree_hash(ENFORCEMENT_PACKAGE)
