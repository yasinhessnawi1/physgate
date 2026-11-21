"""The digest tool hashes a pinned binary only from the exact tarball its rig's lockfile names.

Runs offline, on fixture archives: a tarball whose sha512 is the pinned one gives the binary's
sha256; one changed by a single byte, a lockfile pinning by a weaker hash, a platform the
lockfile does not pin and an archive with no binary in it are each refused. Both rigs' real
lockfiles are read too, so a rig that stops pinning a platform the harness runs on is caught.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

import claude_code_digests as digests
import pytest

RIGS = sorted(p for p in Path(__file__).parent.glob("claude-code*") if p.is_dir())


def _tarball(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _integrity(data: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def test_the_pinned_tarball_gives_its_binary_s_sha256() -> None:
    binary = b"\x7fELF a stand-in for the binary"
    tarball = _tarball({"package/claude": binary, "package/package.json": b"{}"})
    assert digests.binary_sha256(tarball, _integrity(tarball)) == hashlib.sha256(binary).hexdigest()


def test_a_tarball_one_byte_off_the_pinned_one_is_refused() -> None:
    tarball = _tarball({"package/claude": b"binary"})
    changed = tarball[:-1] + bytes([tarball[-1] ^ 1])
    with pytest.raises(digests.DigestError, match="not the one the lockfile pins"):
        digests.binary_sha256(changed, _integrity(tarball))


def test_an_archive_without_the_binary_is_refused() -> None:
    tarball = _tarball({"package/README.md": b"no binary here"})
    with pytest.raises(digests.DigestError, match="holds no package/claude"):
        digests.binary_sha256(tarball, _integrity(tarball))


def test_a_lockfile_pinning_by_a_weaker_hash_is_refused() -> None:
    lockfile = {
        "packages": {
            "node_modules/@anthropic-ai/claude-code-linux-x64": {
                "version": "9.9.9",
                "resolved": "https://registry.npmjs.org/x.tgz",
                "integrity": "sha1-AAAA",
            }
        }
    }
    with pytest.raises(digests.DigestError, match="not sha512"):
        digests.pinned(lockfile, "linux-x64")


def test_a_platform_the_lockfile_does_not_pin_is_refused() -> None:
    with pytest.raises(digests.DigestError, match="pins no"):
        digests.pinned({"packages": {}}, "linux-x64")


def test_a_tarball_outside_the_registry_is_never_fetched() -> None:
    with pytest.raises(digests.DigestError, match="outside the npm registry"):
        digests._fetch("https://example.invalid/claude.tgz")


@pytest.mark.parametrize("rig", RIGS, ids=[r.name for r in RIGS])
def test_every_rig_pins_each_platform_the_harness_runs_on_by_sha512(rig: Path) -> None:
    assert len(RIGS) >= 2, "one rig per pinned version is expected"
    lockfile = json.loads((rig / "package-lock.json").read_text())
    wanted = json.loads((rig / "package.json").read_text())["dependencies"][
        "@anthropic-ai/claude-code"
    ]
    for platform in digests.PLATFORMS:
        version, resolved, integrity = digests.pinned(lockfile, platform)
        assert version == wanted, (platform, version)
        assert resolved.startswith("https://registry.npmjs.org/"), resolved
        assert integrity.startswith("sha512-"), integrity
