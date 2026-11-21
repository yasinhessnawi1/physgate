"""The sha256 of each pinned Claude Code platform binary, from the tarball its lockfile pins.

A rig's lockfile pins every platform package of one Claude Code version by its tarball's address
and sha512. This reads the lockfile, fetches the platform packages the harness runs on, refuses a
tarball whose sha512 is not the one the lockfile pins, and prints the sha256 of the binary inside
it as one JSON line per platform. Nothing is installed and nothing is run: the binary is hashed
from the archive's bytes. The orchestrator's table of known binaries cites these lines, so a
binary placed on a machine by any route can be checked against the one the lockfile names.

    python tests/integration/hooks/claude_code_digests.py tests/integration/hooks/claude-code
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from collections.abc import Mapping
from pathlib import Path

#: The platforms the harness runs sessions on: the development machine, CI and the server.
PLATFORMS = ("darwin-arm64", "linux-x64", "linux-arm64")
_PACKAGE = "@anthropic-ai/claude-code"
#: Where the binary sits inside a platform package's tarball.
_MEMBER = "package/claude"


class DigestError(Exception):
    """A lockfile or a tarball that cannot be trusted to name the binary."""


def pinned(lockfile: Mapping[str, object], platform: str) -> tuple[str, str, str]:
    """The version, tarball address and sha512 the lockfile pins for one platform package.

    Raises:
        DigestError: the lockfile has no such package, or pins it by anything but sha512.
    """
    packages = lockfile.get("packages")
    entry = (
        packages.get(f"node_modules/{_PACKAGE}-{platform}") if isinstance(packages, dict) else None
    )
    if not isinstance(entry, dict):
        msg = f"the lockfile pins no {_PACKAGE}-{platform}"
        raise DigestError(msg)
    version, resolved, integrity = (entry.get(k) for k in ("version", "resolved", "integrity"))
    if not (isinstance(version, str) and isinstance(resolved, str) and isinstance(integrity, str)):
        msg = f"the lockfile's {platform} entry lacks a version, an address or an integrity"
        raise DigestError(msg)
    if not integrity.startswith("sha512-"):
        msg = f"the lockfile pins {platform} by {integrity.split('-', 1)[0]}, not sha512"
        raise DigestError(msg)
    return version, resolved, integrity


def binary_sha256(tarball: bytes, integrity: str) -> str:
    """The sha256 of the binary in ``tarball``, once its sha512 is the pinned one.

    Raises:
        DigestError: the tarball is not the pinned one, or holds no binary.
    """
    found = "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode()
    if found != integrity:
        msg = "the tarball's sha512 is not the one the lockfile pins"
        raise DigestError(msg)
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        try:
            member = archive.getmember(_MEMBER)
        except KeyError:
            msg = f"the tarball holds no {_MEMBER}"
            raise DigestError(msg) from None
        handle = archive.extractfile(member) if member.isfile() else None
        if handle is None:
            msg = f"{_MEMBER} in the tarball is not a regular file"
            raise DigestError(msg)
        return hashlib.sha256(handle.read()).hexdigest()


def _fetch(address: str) -> bytes:
    if not address.startswith("https://registry.npmjs.org/"):
        msg = f"the lockfile names a tarball outside the npm registry: {address}"
        raise DigestError(msg)
    with urllib.request.urlopen(address, timeout=300) as response:  # noqa: S310 - https, checked above
        data: bytes = response.read()
    return data


def main(argv: list[str]) -> int:
    """Print one JSON line per platform for the rig directory named in ``argv``."""
    if len(argv) != 1:
        print("usage: claude_code_digests.py <rig directory>", file=sys.stderr)
        return 64
    lockfile = json.loads((Path(argv[0]) / "package-lock.json").read_text())
    for platform in PLATFORMS:
        version, address, integrity = pinned(lockfile, platform)
        line = {
            "version": version,
            "platform": platform,
            "sha256": binary_sha256(_fetch(address), integrity),
            "tarball": address,
            "tarball_sha512": "verified against the lockfile",
        }
        print(json.dumps(line, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
