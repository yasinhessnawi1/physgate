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

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.managed import SystemManagedFile, system_managed_facts

#: Every file the build put in the installation, by path and sha256: the
#: interpreter's links, the ``bin`` scripts every hook runs through, ``pyvenv.cfg``,
#: ``site-packages``, compiled caches included. Written when the installation is
#: built, inside it, so it is as read-only and as protected as what it describes,
#: and held against the installation at every use.
MANIFEST_NAME = "physgate-install-manifest.json"

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
            # Built fresh from the source every time. uv keys its cache of a local
            # project on its project file, not its source, so a cached build can be
            # an earlier version of the hook layer (found when a new installer option
            # was missing from the installation).
            "--no-cache",
            str(project_root),
        ],
    ]
    for argv in steps:
        done = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            msg = "building the hook installation failed"
            raise InvocationError(msg, command=" ".join(argv[:3]), stderr=done.stderr[-600:])
    _require_package_is_source(dest, project_root)
    manifest = install_manifest(dest)
    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=1, sort_keys=True))
    for directory, dirs, files in os.walk(dest, topdown=False):
        for name in files + dirs:
            path = os.path.join(directory, name)
            if not os.path.islink(path):
                mode = os.lstat(path).st_mode
                os.chmod(path, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    os.chmod(dest, os.lstat(dest).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    return dest / "bin" / "physgate"


def install_manifest(dest: Path) -> dict[str, str]:
    """Every file of an installation, by path relative to it: its sha256.

    The manifest itself is left out. A symbolic link is recorded by its target.
    Compiled caches are recorded like any other file: a read-only installation
    never gains one by running, and one planted there runs in place of its source.
    """
    entries: dict[str, str] = {}
    for path in sorted(Path(dest).rglob("*")):
        rel = path.relative_to(dest)
        if rel.as_posix() == MANIFEST_NAME:
            continue
        if path.is_symlink():
            entries[rel.as_posix()] = "link:" + os.readlink(path)
        elif path.is_file():
            entries[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def _require_package_is_source(dest: Path, project_root: Path) -> None:
    source = Path(project_root) / "src" / "physgate"
    found = sorted(Path(dest).glob("lib/python*/site-packages/physgate"))
    if len(found) != 1:
        msg = "the installation holds no single copy of the package"
        raise InvocationError(msg, path=str(dest))
    stale = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        copy = found[0] / path.relative_to(source)
        if not copy.is_file() or copy.read_bytes() != path.read_bytes():
            stale.append(str(path.relative_to(source)))
    # A file the source does not have is drift too: a module planted in the
    # installed gate would pass a comparison that only reads the source's files.
    for path in sorted(found[0].rglob("*")):
        rel = path.relative_to(found[0])
        if path.is_file() and "__pycache__" not in rel.parts and not (source / rel).is_file():
            stale.append(f"{rel.as_posix()} (not in the source)")
    if stale:
        msg = "the installation is not the source as it is now; build a new one"
        raise InvocationError(msg, path=str(dest), differs=", ".join(stale[:5]))


def require_current(dest: Path, project_root: Path) -> None:
    """Refuse an installation that is not the source's build, file for file.

    The hooks a session runs under are this copy, not the source, so two things
    are held, whenever an installation is built or reused:

    - its copy of the package is the project's source as it is now, with no file
      the source lacks (a build from a cache keyed on the project file, or an
      installation left from an earlier source, would run other hook code);
    - every file of the installation is what its own build produced, recorded
      in a manifest when it was built: the ``bin`` scripts every hook is run
      through, ``pyvenv.cfg``, which decides what the interpreter imports from
      outside the installation, and ``site-packages``, where Python's startup
      executes the lines of every ``.pth`` file and imports ``sitecustomize``
      and ``usercustomize`` before any hook or check loads, even in isolated
      mode.

    Raises:
        InvocationError: the package is not the source, the manifest is missing,
            or a file was added, removed or changed since the build.
    """
    _require_package_is_source(dest, project_root)
    manifest_path = Path(dest) / MANIFEST_NAME
    try:
        built: dict[str, str] = json.loads(manifest_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        msg = "the installation has no manifest of what its build produced; build a new one"
        raise InvocationError(msg, path=str(dest)) from None
    now = install_manifest(dest)
    added = sorted(set(now) - set(built))
    removed = sorted(set(built) - set(now))
    changed = sorted(k for k in set(now) & set(built) if now[k] != built[k])
    if added or removed or changed:
        msg = "the installation is not what its build produced; build a new one"
        raise InvocationError(
            msg,
            path=str(dest),
            added=", ".join(added[:5]),
            removed=", ".join(removed[:5]),
            changed=", ".join(changed[:5]),
        )


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
