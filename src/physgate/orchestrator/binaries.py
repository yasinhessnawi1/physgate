"""Which Claude Code binary a run executes: its digest and platform, against the ones known.

A version string names a release, not the bytes that run. Each platform has its own build, a
binary can be replaced under an unchanged version, and a machine's own copy can update itself.
So a run records the sha256 and the platform of the binary it executed, measured when it is
configured and again whenever it is driven, and refuses to continue on any other. A run whose
numbers may be reported also refuses a binary that is not one of the builds listed here for its
version: each listed digest was measured from the tarball whose sha512 the test rig's lockfile
pins (``tests/integration/hooks/claude_code_digests.py``), or from a copy whose digest a frozen
experiment's driver already checks, and each entry says which.
"""

from __future__ import annotations

import hashlib
import platform as _platform
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from physgate.orchestrator.exceptions import InvocationError, RunConfigError

#: The builds the harness runs sessions on, named as the npm platform packages name them.
Platform = Literal["darwin-arm64", "darwin-x64", "linux-arm64", "linux-x64"]

_Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ClaudeBinary(BaseModel):
    """The binary a run executed: its bytes' sha256 and the platform build it is."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    sha256: _Sha256
    platform: Platform


class KnownBinary(BaseModel):
    """One listed build of a pinned version, with where its digest was measured."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    sha256: _Sha256
    source: str


_FROM_A_DRIVER = (
    "the digest the R-PG-03 launch driver checks for this build (experiments/R-PG-03/common.py)"
)

#: The builds a reportable run may execute, by version and platform.
KNOWN_BINARIES: Mapping[tuple[str, Platform], KnownBinary] = {
    ("2.1.301", "darwin-arm64"): KnownBinary(
        sha256="1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99",
        source=_FROM_A_DRIVER,
    ),
    ("2.1.301", "linux-arm64"): KnownBinary(
        sha256="1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0",
        source=_FROM_A_DRIVER,
    ),
}


_PLATFORMS: Mapping[tuple[str, str], Platform] = {
    ("darwin", "arm64"): "darwin-arm64",
    ("darwin", "x64"): "darwin-x64",
    ("linux", "arm64"): "linux-arm64",
    ("linux", "x64"): "linux-x64",
}


def platform_here() -> Platform:
    """The platform build this machine runs.

    Raises:
        InvocationError: the machine is not one the harness runs sessions on.
    """
    machine = _platform.machine().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(machine)
    found = _PLATFORMS.get((sys.platform, arch or ""))
    if found is None:
        msg = f"no Claude Code build is used on this machine ({sys.platform}, {machine})"
        raise InvocationError(msg, platform=sys.platform, machine=machine)
    return found


def measure(binary: str) -> ClaudeBinary:
    """The sha256 of the file ``binary`` resolves to, and this machine's platform.

    Raises:
        InvocationError: the binary cannot be read.
    """
    path = Path(binary).resolve()
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        msg = "the Claude Code binary cannot be read to measure its digest"
        raise InvocationError(msg, binary=str(path), reason=type(exc).__name__) from None
    return ClaudeBinary(sha256=digest.hexdigest(), platform=platform_here())


def require_listed(version: str, binary: ClaudeBinary) -> None:
    """Refuse a binary that is not the listed build of ``version`` for its platform.

    Raises:
        RunConfigError: no build is listed for that version and platform, or the digest differs.
    """
    known = KNOWN_BINARIES.get((version, binary.platform))
    if known is None:
        msg = (
            f"no {binary.platform} build of Claude Code {version} is listed, so a run whose "
            "numbers may be reported cannot name the binary it ran"
        )
        raise RunConfigError(msg, version=version, platform=binary.platform)
    if known.sha256 != binary.sha256:
        msg = (
            f"the binary is not the listed {binary.platform} build of Claude Code {version}; "
            "a run whose numbers may be reported runs only that build"
        )
        raise RunConfigError(
            msg, version=version, platform=binary.platform, listed=known.sha256, found=binary.sha256
        )


def require_same(recorded: ClaudeBinary | None, now: ClaudeBinary) -> None:
    """Refuse to drive a run on a binary other than the one it recorded.

    A run recorded before the binary was recorded has nothing to hold it to, and is driven.

    Raises:
        RunConfigError: the digest or the platform differs from the recorded one.
    """
    if recorded is None or recorded == now:
        return
    changed = [
        name for name in ("sha256", "platform") if getattr(recorded, name) != getattr(now, name)
    ]
    msg = "the Claude Code binary differs from the one this run recorded"
    raise RunConfigError(
        msg,
        changed=",".join(changed),
        recorded=f"{recorded.platform} {recorded.sha256}",
        found=f"{now.platform} {now.sha256}",
    )
