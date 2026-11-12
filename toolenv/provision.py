"""Build the tool environment a run's role sessions compute and build with, offline from then on.

Run it outside every session, with the network, once per machine:

    python3 toolenv/provision.py --dest /abs/path/new-env [--cache /abs/path/cache]

Every download is held to a digest recorded before it was fetched: the interpreter by uv's own
table, each wheel by ``uv.lock``, Node by ``pins.json``, each npm package by the server's
``package-lock.json``, and each PlatformIO package by its registry's checksum at the pinned
version. Every file is copied into the destination, never linked to a cache: a file with a
second name outside the environment could be changed through that name, unseen by anything
that guards the environment's own paths. The result is one directory:

    python/             the uv-managed interpreter
    venv/               the libraries, installed from ``uv.lock``
    project/            the project file and lock it was built from
    platformio/         PlatformIO's package store (platform, toolchain, framework, library)
    node/               the pinned Node release
    platformio-server/  the PlatformIO tool server, installed from its npm lock
    servers/            this repository's own tool servers
    provisioned.json    what was built, and what the self-check measured

It ends by checking itself offline (the libraries import at their pins and compute, a firmware
fixture builds with every download refused, the PlatformIO server answers), and leaves every
file read-only. The harness measures the result before a run may use it; this script only
builds it. It runs on any Python 3.12 and imports nothing from the harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: The repository checkout this script lies in: the environment may never lie inside it.
REPO = HERE.parent

NODE_DIST = "https://nodejs.org/dist"
#: Where Node's release for each machine is named in ``pins.json``.
NODE_PLATFORMS = {
    ("Darwin", "arm64"): "darwin-arm64",
    ("Linux", "x86_64"): "linux-x64",
    ("Linux", "aarch64"): "linux-arm64",
}
#: The most a single download may hold.
MAX_DOWNLOAD_BYTES = 200 << 20
#: How long one provisioning step may take.
STEP_TIMEOUT_S = 1800
#: A proxy nothing listens on: the self-check's downloads all fail, so a build that needed
#: one fails too.
DEAD_PROXY = "http://127.0.0.1:9"

#: The firmware fixture the self-check builds: the Balboa library's motors and encoders.
FIXTURE_INI = """[env:balboa]
platform = platformio/atmelavr@5.3.0
board = a-star32U4
framework = arduino
"""
FIXTURE_MAIN = """#include <Arduino.h>
#include <Balboa32U4.h>
Balboa32U4Motors motors;
Balboa32U4Encoders encoders;
void setup() { Serial.begin(115200); }
void loop() {
  int16_t l = encoders.getCountsLeft();
  motors.setSpeeds(l > 100 ? -50 : 50, 50);
  Serial.println(l);
  delay(10);
}
"""
#: What the self-check asks the libraries: their versions, a margin and a MuJoCo step.
LIBRARY_CHECK = """
import importlib.metadata as m, json
import control, mujoco
G = control.tf([1], [1, 2, 1]); C = control.tf([4, 4], [1, 0])
gm, pm, _, _ = control.margin(C * G)
model = mujoco.MjModel.from_xml_string(
    '<mujoco><worldbody><body><joint type="hinge"/>'
    '<geom type="capsule" size=".05" fromto="0 0 0 0 0 1"/></body></worldbody></mujoco>')
data = mujoco.MjData(model)
for _ in range(100):
    mujoco.mj_step(model, data)
names = ("control", "numpy", "scipy", "mujoco", "platformio")
print(json.dumps({"versions": {n: m.version(n) for n in names},
                  "phase_margin_deg": float(pm), "time_s": float(data.time)}))
"""


class ProvisionError(Exception):
    """Provisioning stopped: the environment is not built, and the message says why."""


# ---- what is fetched, and from where ---------------------------------------------------------


def load_pins(toolenv: Path = HERE) -> dict[str, object]:
    """The pins file beside this script."""
    loaded = json.loads((toolenv / "pins.json").read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ProvisionError("pins.json is not an object")
    return loaded


def node_archive(pins: Mapping[str, object], system: str, machine: str) -> tuple[str, str]:
    """The pinned Node archive's file name and sha256 for a machine."""
    name = NODE_PLATFORMS.get((system, machine))
    node = pins.get("node")
    archives = node.get("archives") if isinstance(node, dict) else None
    archive = archives.get(name) if isinstance(archives, dict) and name else None
    if not isinstance(archive, dict):
        raise ProvisionError(f"no pinned Node release for {system} {machine}")
    return str(archive["file"]), str(archive["sha256"])


def sha256_of(path: Path) -> str:
    """The sha256 of a file's bytes."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def require_digest(path: Path, expected: str) -> None:
    """Refuse a download whose bytes are not the pinned ones."""
    found = sha256_of(path)
    if found != expected:
        raise ProvisionError(f"{path.name}: digest {found} is not the pinned {expected}")


def fetch(url: str, into: Path, work: Path) -> Path:
    """Download ``url`` into the new directory ``into``, bounded in size.

    ``curl`` fetches it, with the system's own certificate store; an interpreter's bundled one
    may be missing.
    """
    into.mkdir(parents=True, exist_ok=False)
    target = into / url.rsplit("/", 1)[-1]
    curl = shutil.which("curl", path="/usr/bin:/bin")
    if curl is None:
        raise ProvisionError("curl is not installed")
    argv = [curl, "-fsSL", "--proto", "=https", "--max-filesize", str(MAX_DOWNLOAD_BYTES)]
    run([*argv, "-o", str(target), url], base_environment(work))
    return target


def extract(archive: Path, into: Path) -> Path:
    """Unpack a release archive's one top directory into ``into``; return that directory.

    The standard library's ``data`` filter refuses a member that would land outside ``into``,
    an absolute or escaping link, and device files.
    """
    try:
        with tarfile.open(archive, "r:*") as tar:
            tops = {Path(member.name).parts[0] for member in tar.getmembers()}
            tar.extractall(into, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise ProvisionError(f"the archive {archive.name} was refused: {exc}") from None
    if len(tops) != 1:
        raise ProvisionError(f"the archive {archive.name} has no single top directory")
    return into / tops.pop()


# ---- distribution packages: the display libraries the CAD kernel links on Linux ---------------

PACKAGE_FILES = ""
DESIGN_LICENCES: dict[str, str] = {}


def system_packages(pins: Mapping[str, object], system: str, machine: str) -> list[dict[str, str]]:
    """Not built yet."""
    return []


def unpack_tree(archive: Path, into: Path) -> None:
    """Not built yet."""


def place_beside_kernel(
    dest: Path, packages: Sequence[Mapping[str, str]], beside: str
) -> list[str]:
    """Not built yet."""
    return []


def _package_tree(package: Path, work: Path) -> Path:
    return package


def _system_libraries(
    dest: Path, pins: Mapping[str, object], cache: Path, work: Path
) -> list[dict[str, str]]:
    return []


def _helpers(dest: Path) -> list[str]:
    return []


def mapped_outside(
    mapped: Sequence[str], packages: Sequence[Mapping[str, str]], dest: Path
) -> list[str]:
    """Not built yet."""
    return []


def _check_design(
    dest: Path, packages: Sequence[Mapping[str, str]], work: Path
) -> dict[str, object]:
    return {"part": {}, "load_case": {}}


# ---- the commands, and the settings they run with --------------------------------------------


def check_destination(dest: Path, repo: Path) -> Path:
    """Refuse a destination that is relative, holds anything, or overlaps the checkout."""
    if not dest.is_absolute():
        raise ProvisionError("the destination is named by an absolute path")
    real, checkout = Path(os.path.realpath(dest)), Path(os.path.realpath(repo))
    if real == checkout or checkout in real.parents or real in checkout.parents:
        raise ProvisionError("the environment may not lie in or around the harness checkout")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ProvisionError("the destination must be new or an empty directory")
    return dest


def base_environment(work: Path) -> dict[str, str]:
    """A minimal environment for every step: no inherited Python or package settings."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(work / "home"),
        "TMPDIR": str(work / "tmp"),
        "LANG": "C.UTF-8",
    }


def uv_environment(dest: Path, cache: Path, work: Path) -> dict[str, str]:
    """The settings uv runs with: copy every file, fetch the pinned interpreter on request only.

    The machine's own uv settings are not read, because uv finds them under the home and the
    configuration home, and it is given neither. uv's switch for ignoring configuration is not
    used: it drops the project's own settings too, its lock cooldown among them.
    """
    return {
        **base_environment(work),
        "UV_LINK_MODE": "copy",
        "UV_PYTHON_DOWNLOADS": "manual",
        "UV_PYTHON_PREFERENCE": "only-managed",
        "UV_PYTHON_INSTALL_DIR": str(dest / "python"),
        "UV_PYTHON_BIN_DIR": str(work / "bin"),
        "UV_PROJECT_ENVIRONMENT": str(dest / "venv"),
        "UV_CACHE_DIR": str(cache / "uv"),
    }


def npm_ci_argv(npm: Path, cache: Path) -> list[str]:
    """Install the server exactly as locked, running no package's scripts.

    Optional packages are left out: the only one is a serial-port binding, and a session's
    tools never open a serial port.
    """
    return [
        str(npm),
        "ci",
        "--ignore-scripts",
        "--omit=optional",
        "--omit=dev",
        "--no-audit",
        "--no-fund",
        "--no-update-notifier",
        f"--cache={cache / 'npm'}",
    ]


def pio_install_argvs(pio: Path, pins: Mapping[str, object]) -> list[list[str]]:
    """One install per pinned package, none pulling a dependency of its own choosing."""
    store = pins["platformio"]
    if not isinstance(store, dict):
        raise ProvisionError("pins.json names no PlatformIO store")
    head = [str(pio), "pkg", "install", "-g", "--skip-dependencies"]
    argvs = [[*head, "-p", str(store["platform"])]]
    argvs += [[*head, "-t", str(tool)] for tool in store["tools"]]
    argvs += [[*head, "-l", str(library)] for library in store["libraries"]]
    return argvs


def pio_environment(core: Path, work: Path, *, offline: bool) -> dict[str, str]:
    """PlatformIO's settings: its own core directory, telemetry and update checks off."""
    env = {
        **base_environment(work),
        "PLATFORMIO_CORE_DIR": str(core),
        "PLATFORMIO_SETTING_ENABLE_TELEMETRY": "no",
        "PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL": "36500",
        "PLATFORMIO_SETTING_CHECK_PRUNE_SYSTEM_THRESHOLD": "0",
        "PLATFORMIO_NO_ANSI": "true",
        "PLATFORMIO_DISABLE_PROGRESSBAR": "true",
    }
    if offline:
        env |= {"HTTP_PROXY": DEAD_PROXY, "HTTPS_PROXY": DEAD_PROXY, "ALL_PROXY": DEAD_PROXY}
    return env


def run(argv: Sequence[str], env: Mapping[str, str], *, cwd: Path | None = None) -> str:
    """Run one step; stop provisioning, with its output's tail, if it fails."""
    done = subprocess.run(  # noqa: S603
        list(argv),
        env=dict(env),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=STEP_TIMEOUT_S,
        check=False,
    )
    if done.returncode != 0:
        tail = (done.stdout + done.stderr)[-2000:]
        raise ProvisionError(f"{Path(argv[0]).name} {' '.join(argv[1:3])} failed:\n{tail}")
    return done.stdout


# ---- what the result must be ------------------------------------------------------------------


def _walk(root: Path) -> list[Path]:
    found: list[Path] = []
    for directory, dirs, files in os.walk(root):
        found += [Path(directory, name) for name in (*dirs, *files)]
    return found


def require_one_name_each(root: Path) -> None:
    """Refuse a regular file with a second name anywhere: a cache link, an archive hard link."""
    for path in _walk(root):
        found = path.lstat()
        if stat.S_ISREG(found.st_mode) and found.st_nlink > 1:
            raise ProvisionError(f"{path} has a second name ({found.st_nlink} links)")


def require_links_inside(root: Path) -> None:
    """Refuse a symbolic link that leads outside the environment, or nowhere."""
    real_root = Path(os.path.realpath(root))
    for path in _walk(root):
        if path.is_symlink():
            target = Path(os.path.realpath(path))
            if not (target == real_root or real_root in target.parents) or not target.exists():
                raise ProvisionError(f"{path} leads outside the environment, to {target}")


def make_read_only(root: Path) -> None:
    """Take every write bit off every file and directory; keep execute bits as they are."""
    for path in [*_walk(root), root]:
        if not path.is_symlink():
            path.chmod(stat.S_IMODE(path.lstat().st_mode) & ~0o222)


# ---- the build --------------------------------------------------------------------------------


def _python(dest: Path, version: str, env: Mapping[str, str], uv: str) -> Path:
    try:
        run([uv, "python", "install", version], env)
    except ProvisionError as exc:
        raise ProvisionError(
            f"the pinned interpreter {version} cannot be installed: {exc}"
        ) from None
    found = Path(run([uv, "python", "find", version], env).strip())
    if dest / "python" not in found.parents:
        raise ProvisionError(f"uv found an interpreter outside the environment: {found}")
    return found


def _platformio(dest: Path, pins: Mapping[str, object], work: Path) -> None:
    core = dest / "platformio"
    env = pio_environment(core, work, offline=False)
    for argv in pio_install_argvs(dest / "venv" / "bin" / "pio", pins):
        run(argv, env)
    shutil.rmtree(core / ".cache", ignore_errors=True)


def _node(dest: Path, pins: Mapping[str, object], cache: Path, work: Path) -> str:
    file, digest = node_archive(pins, platform.system(), platform.machine())
    node = pins["node"]
    assert isinstance(node, dict)
    kept = cache / "node" / str(node["version"]) / file
    if not kept.exists():
        # Fetched apart and checked before it is kept, so the cache only ever holds an
        # archive that matched its pin; one that no longer does is refused below.
        downloads = Path(tempfile.mkdtemp(prefix="node-", dir=work))
        fetched = fetch(f"{NODE_DIST}/v{node['version']}/{file}", downloads / "archive", work)
        require_digest(fetched, digest)
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(fetched, kept)
    require_digest(kept, digest)
    unpack = dest / ".node-unpack"
    unpack.mkdir()
    extract(kept, unpack).rename(dest / "node")
    unpack.rmdir()
    return digest


def _server(dest: Path, cache: Path, work: Path) -> None:
    server = dest / "platformio-server"
    server.mkdir()
    for name in ("package.json", "package-lock.json", "policy.yaml"):
        shutil.copyfile(HERE / "platformio-server" / name, server / name)
    env = {
        **base_environment(work),
        "PATH": f"{dest / 'node' / 'bin'}:/usr/bin:/bin",
        "npm_config_update_notifier": "false",
    }
    run(npm_ci_argv(dest / "node" / "bin" / "npm", cache), env, cwd=server)


def _own_servers(dest: Path) -> list[str]:
    (dest / "servers").mkdir()
    copied = []
    source = HERE / "servers"
    for path in sorted(source.glob("*.py")) if source.is_dir() else []:
        shutil.copyfile(path, dest / "servers" / path.name)
        copied.append(path.name)
    return copied


def _check_libraries(dest: Path, pins: Mapping[str, object], work: Path) -> dict[str, object]:
    env = {**base_environment(work), "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(work / "mpl")}
    out = run([str(dest / "venv" / "bin" / "python"), "-I", "-c", LIBRARY_CHECK], env)
    found = json.loads(out)
    project = (dest / "project" / "pyproject.toml").read_text(encoding="utf-8")
    for name, version in found["versions"].items():
        if f'"{name}=={version}"' not in project:
            raise ProvisionError(f"{name} {version} is not the pinned version")
    return dict(found)


def _check_build(dest: Path, work: Path) -> dict[str, int]:
    core = work / "pio-core"
    core.mkdir()
    # The store is read-only, and PlatformIO takes lock files beside each store, so the
    # build's core directory is its own and links into the store.
    for name in ("platforms", "packages", "lib"):
        (core / name).symlink_to(dest / "platformio" / name)
    sketch = work / "sketch"
    (sketch / "src").mkdir(parents=True)
    (sketch / "platformio.ini").write_text(FIXTURE_INI, encoding="utf-8")
    (sketch / "src" / "main.cpp").write_text(FIXTURE_MAIN, encoding="utf-8")
    env = pio_environment(core, work, offline=True) | {
        "PLATFORMIO_BUILD_DIR": str(work / "build"),
        "PLATFORMIO_WORKSPACE_DIR": str(work / "workspace"),
        "PLATFORMIO_CACHE_DIR": str(work / "pio-cache"),
    }
    out = run([str(dest / "venv" / "bin" / "pio"), "run"], env, cwd=sketch)
    sizes: dict[str, int] = {}
    for line in out.splitlines():
        for label in ("RAM", "Flash"):
            if line.startswith(f"{label}:") and "used " in line:
                sizes[f"{label.lower()}_used_bytes"] = int(line.split("used ")[1].split()[0])
    if len(sizes) != 2 or (sketch / ".pio").exists():
        raise ProvisionError("the offline firmware build gave no size, or built into the module")
    return sizes


def _check_server(dest: Path, work: Path) -> str:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "provision", "version": "0"},
        },
    }
    env = {
        **base_environment(work),
        "PIO_MCP_POLICY_FILE": str(dest / "platformio-server" / "policy.yaml"),
        "PIO_MCP_DISABLE_DASHBOARD": "1",
        "PIO_MCP_NO_BROWSER": "1",
        "PIO_MCP_DATA_DIR": str(work / "pio-mcp"),
    }
    cli = dest / "platformio-server" / "node_modules" / "platformio-mcp" / "build" / "cli.js"
    with subprocess.Popen(  # noqa: S603
        [str(dest / "node" / "bin" / "node"), str(cli)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
    ) as server:
        assert server.stdin is not None and server.stdout is not None
        server.stdin.write(json.dumps(request) + "\n")
        server.stdin.flush()
        answer = json.loads(server.stdout.readline())
        server.stdin.close()
        server.wait(timeout=30)
    version = str(answer.get("result", {}).get("serverInfo", {}).get("version", ""))
    if version != "3.1.0":
        raise ProvisionError(f"the PlatformIO server answered as version {version!r}")
    return version


def provision(
    dest: Path, cache: Path, pins: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Build the environment at ``dest``, check it, and leave it read-only.

    ``pins`` defaults to ``pins.json`` beside this script; a test names others.
    """
    check_destination(dest, REPO)
    uv = shutil.which("uv")
    if uv is None:
        raise ProvisionError("uv is not on PATH")
    pins = load_pins() if pins is None else pins
    dest.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    try:
        return _build(dest, cache, uv, pins)
    except BaseException:
        # A half-built environment is never left for a run to find.
        _remove(dest)
        raise


def _remove(root: Path) -> None:
    for path in [root, *_walk(root)]:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
    shutil.rmtree(root, ignore_errors=True)


def _build(dest: Path, cache: Path, uv: str, pins: Mapping[str, object]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="provision-") as scratch:
        work = Path(scratch)
        for name in ("home", "tmp", "bin"):
            (work / name).mkdir()
        env = uv_environment(dest, cache, work)
        # The step whose download is checked against this repository's own pin goes first,
        # so a wrong pin stops provisioning before anything else is fetched.
        node_digest = _node(dest, pins, cache, work)
        python = _python(dest, str(pins["python"]), env, uv)
        (dest / "project").mkdir()
        for name in ("pyproject.toml", "uv.lock"):
            shutil.copyfile(HERE / name, dest / "project" / name)
        run(
            [uv, "sync", "--frozen", "--no-install-project", "--compile-bytecode",
             "--project", str(dest / "project"), "--python", str(python)],
            env,
        )  # fmt: skip
        # The interpreter's own library is compiled as well, so no first import writes a
        # cache file into the environment after it was measured.
        # Its standard library only: the installation also carries Tcl's own files, one of
        # them a Python file that does not compile (measured on Linux).
        stdlib = run(
            [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('stdlib'))"], env
        )
        run([str(python), "-I", "-m", "compileall", "-q", "-j0", stdlib.strip()], env)
        _platformio(dest, pins, work)
        _server(dest, cache, work)
        servers = _own_servers(dest)
        require_one_name_each(dest)
        require_links_inside(dest)
        make_read_only(dest)
        dest.chmod(0o755)  # until provisioned.json is written
        record: dict[str, object] = {
            "pins": pins,
            "uv": run([uv, "--version"], env).strip(),
            "machine": f"{platform.system()} {platform.machine()}",
            "python": str(python.relative_to(dest)),
            "node_archive_sha256": node_digest,
            "own_servers": servers,
            "locks_sha256": {
                name: sha256_of(HERE / name)
                for name in ("pyproject.toml", "uv.lock", "pins.json",
                             "platformio-server/package-lock.json")
            },
            "self_check": {
                "libraries": _check_libraries(dest, pins, work),
                "firmware": _check_build(dest, work),
                "platformio_server": _check_server(dest, work),
            },
        }  # fmt: skip
    written = dest / "provisioned.json"
    written.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    make_read_only(dest)
    return record


def main(argv: Sequence[str] | None = None) -> int:
    """Command line: ``--dest`` the new environment, ``--cache`` where downloads are kept."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--cache", type=Path, help="kept between runs; a fresh one by default")
    args = parser.parse_args(argv)
    try:
        if args.cache is None:
            with tempfile.TemporaryDirectory(prefix="provision-cache-") as cache:
                record = provision(args.dest, Path(cache))
        else:
            record = provision(args.dest, args.cache)
    except ProvisionError as exc:
        print(f"provisioning stopped: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(record["self_check"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
