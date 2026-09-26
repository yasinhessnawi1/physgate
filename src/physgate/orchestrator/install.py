"""The installation the hooks run from, and the facts about it a run records.

The hooks of a session run on the interpreter and package that generated them.
If the session's own user can write that installation, a session could plant
code that runs inside every hook. The real closure is an installation the
session's user cannot write at all, which needs a second OS user or root
ownership, a machine change that is not this package's to make. What is built
here is the fallback:

- a dedicated installation, **copied** rather than linked (the installer's cache
  links were measured to give most installed files a second name outside every
  protected root);
- made read-only after it is built;
- and the facts recorded per run: whether its owner is the session's user (then
  the same user can make it writable again), how many files still have a second
  link, whether the interpreter's standard library is writable, and what
  filesystem the session state lives on.

The run says what it could not provide, rather than implying it did.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.managed import SystemManagedFile, system_managed_facts

#: Filesystems whose renames and opens go over a network; the hook state
#: directory belongs on a local disk (the first hook's cost was measured there).
NETWORK_FILESYSTEMS = {"ceph", "nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs", "9p", "afpfs"}


class InstallFacts(BaseModel):
    """What a run records about the installation and the state directory it used."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: str
    interpreter: str
    owner_is_session_user: bool
    files_with_write_bits: int
    files_with_second_links: int
    stdlib: str
    stdlib_writable: bool
    state_filesystem: str
    state_on_local_disk: bool
    #: The system paths the managed-settings tier is read from, as they are now.
    system_managed: tuple[SystemManagedFile, ...] = ()


def prepare_install(dest: Path, project_root: Path) -> Path:
    """Build a copied installation of the project at ``dest`` and make it read-only.

    Returns the installation's ``physgate`` command.

    Raises:
        InvocationError: ``dest`` already exists, or the installer failed.
    """
    if dest.exists():
        msg = "an installation already exists there; a new one goes in a new directory"
        raise InvocationError(msg, path=str(dest))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/")}
    steps = [
        ["uv", "venv", "--quiet", "--python", sys.executable, str(dest)],
        [
            "uv",
            "pip",
            "install",
            "--quiet",
            "--python",
            str(dest / "bin" / "python"),
            "--link-mode",
            "copy",
            str(project_root),
        ],
    ]
    for argv in steps:
        done = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            msg = "building the hook installation failed"
            raise InvocationError(msg, command=" ".join(argv[:3]), stderr=done.stderr[-600:])
    for directory, dirs, files in os.walk(dest, topdown=False):
        for name in files + dirs:
            path = os.path.join(directory, name)
            if not os.path.islink(path):
                mode = os.lstat(path).st_mode
                os.chmod(path, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    os.chmod(dest, os.lstat(dest).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    return dest / "bin" / "physgate"


def filesystem_of(path: Path) -> tuple[str, bool]:
    """The filesystem ``path`` lives on, from the mount table, and whether it is local."""
    target = os.path.realpath(path)
    best, kind = "", "unknown"
    table = subprocess.run(["mount"], capture_output=True, text=True, check=False).stdout
    for line in table.splitlines():
        if " on " not in line:
            continue
        rest = line.split(" on ", 1)[1]
        if " type " in rest:  # Linux: "<dev> on <mount> type <fs> (<options>)"
            mount, fs = rest.split(" type ", 1)
            fs = fs.split(" ", 1)[0]
        else:  # macOS: "<dev> on <mount> (<fs>, <options>)"
            mount, _, options = rest.partition(" (")
            fs = options.split(",", 1)[0]
        inside = target == mount or target.startswith(mount.rstrip("/") + "/")
        if inside and len(mount) > len(best):
            best, kind = mount, fs
    return kind, kind not in NETWORK_FILESYSTEMS and kind != "unknown"


def install_facts(dest: Path, state_dir: Path) -> InstallFacts:
    """Record what ``dest`` and ``state_dir`` actually are on this machine."""
    writable = linked = 0
    for directory, _, files in os.walk(dest):
        for name in files:
            info = os.lstat(os.path.join(directory, name))
            if stat.S_ISLNK(info.st_mode):
                continue
            writable += bool(info.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
            linked += info.st_nlink > 1
    python = dest / "bin" / "python"
    if not python.exists():
        msg = "the hook installation has no interpreter; build it again in a new directory"
        raise InvocationError(msg, path=str(dest))
    base = subprocess.run(
        [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['stdlib'])"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    state_dir.mkdir(parents=True, exist_ok=True)
    fs, local = filesystem_of(state_dir)
    return InstallFacts(
        path=str(dest),
        interpreter=str(python),
        owner_is_session_user=os.lstat(dest).st_uid == os.getuid(),
        files_with_write_bits=writable,
        files_with_second_links=linked,
        stdlib=base,
        stdlib_writable=bool(base) and os.access(base, os.W_OK),
        state_filesystem=fs,
        state_on_local_disk=local,
        system_managed=system_managed_facts(),
    )
