"""Build the tool environment a run's role sessions compute and build with, offline from then on.

Run it outside every session, with the network, once per machine:

    python3 toolenv/provision.py --dest /abs/path/new-env [--cache /abs/path/cache]

Every download is held to a digest recorded before it was fetched: the interpreter by uv's own
table, each wheel by ``uv.lock``, Node by ``pins.json``, each npm package by the server's or the
simulator's ``package-lock.json``, and each PlatformIO package by its registry's checksum at the
pinned version. Every file is copied into the destination, never linked to a cache: a file with a
second name outside the environment could be changed through that name, unseen by anything
that guards the environment's own paths. The result is one directory:

    python/             the uv-managed interpreter
    venv/               the libraries, installed from ``uv.lock``
    project/            the project file and lock it was built from
    platformio/         PlatformIO's package store (platform, toolchain, framework, library)
    node/               the pinned Node release
    platformio-server/  the PlatformIO tool server, installed from its npm lock
    avrsim/             the AVR simulator rig (``avrsim``), on avr8js installed from its npm lock
    servers/            this repository's own tool servers
    provisioned.json    what was built, and what the self-check measured

It ends by checking itself offline (the libraries import at their pins and compute, a firmware
fixture builds with every download refused, the PlatformIO server answers, and two firmware
fixtures run on the simulator to their known answers), and leaves every file read-only. The
harness measures the result before a run may use it; this script only builds it. It runs on any
Python 3.12 and imports nothing from the harness.
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
#: The simulator's timing fixture: a 100 Hz update paced by millis(), reading the inertial
#: sensor's WHO_AM_I over the bus, writing and reading back CTRL2_G, and printing the encoders'
#: counts on USART1 every quarter second.
TIMING_MAIN = """#include <Arduino.h>
#include <Wire.h>
#include <Balboa32U4.h>
Balboa32U4Encoders encoders;
static uint8_t whoami;
static uint8_t ctrl2g;
static uint16_t updates;
static uint8_t readRegister(uint8_t reg) {
  Wire.beginTransmission(0x6B);
  Wire.write(reg);
  Wire.endTransmission();
  Wire.requestFrom((uint8_t)0x6B, (uint8_t)1);
  return Wire.available() ? Wire.read() : 0;
}
extern "C" __attribute__((noinline, used)) void update() {
  whoami = readRegister(0x0F);
  updates++;
  if (updates % 25 == 0) {
    Serial1.print(F("W:"));
    Serial1.print(whoami, HEX);
    Serial1.print(F(" G:"));
    Serial1.print(ctrl2g, HEX);
    Serial1.print(F(" L:"));
    Serial1.print(encoders.getCountsLeft());
    Serial1.print(F(" R:"));
    Serial1.println(encoders.getCountsRight());
  }
}
void setup() {
  Serial1.begin(115200);
  Wire.begin();
  Wire.beginTransmission(0x6B);
  Wire.write(0x11);
  Wire.write(0x58);
  Wire.endTransmission();
  ctrl2g = readRegister(0x11);
  encoders.init();
}
void loop() {
  static uint32_t next = 0;
  uint32_t now = millis();
  if ((int32_t)(now - next) >= 0) {
    next += 10;
    update();
  }
}
"""
#: One second of board time for each fixture. The timing fixture's wheels turn for the first
#: half second only (+5 and -2.5 motor revolutions a second, 12 counts each), so the counts it
#: prints after that are known exactly: +30 and -15.
BALBOA_SCENARIO = {"avrsim_scenario": 1, "duration_s": 1.0}
TIMING_SCENARIO = {
    "avrsim_scenario": 1,
    "duration_s": 1.0,
    "encoders": {
        "left_rev_s": [[0, 5], [0.5, 5], [0.5001, 0]],
        "right_rev_s": [[0, -2.5], [0.5, -2.5], [0.5001, 0]],
    },
    "probes": [{"symbol": "update", "period_s": 0.01}],
}
#: How far a measured period may lie from the nominal one.
PERIOD_TOLERANCE = 0.01

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


# ---- the AVR simulator ------------------------------------------------------------------------

#: The simulator's directory beside this script, and what is copied from it.
AVRSIM = "avrsim"
_AVRSIM_FILES = ("package.json", "package-lock.json", "bin/avrsim")


def avrsim_files(toolenv: Path = HERE) -> list[str]:
    """The simulator's files, relative to its directory: package, lock, launcher, sources."""
    sources = sorted(path.name for path in (toolenv / AVRSIM / "src").glob("*.js"))
    return [*_AVRSIM_FILES, *(f"src/{name}" for name in sources)]


def built_from(toolenv: Path = HERE) -> list[str]:
    """Every file of this directory the environment is built from, as provisioned.json names it."""
    own = [
        "pyproject.toml",
        "uv.lock",
        "pins.json",
        SESSION_FILE,
        "platformio-server/package-lock.json",
    ]
    return [*own, *(f"{AVRSIM}/{name}" for name in avrsim_files(toolenv))]


def copy_avrsim(dest: Path) -> None:
    """Copy the simulator's package, lock, launcher and sources in; the launcher executable."""
    for name in avrsim_files():
        target = dest / AVRSIM / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / AVRSIM / name, target)
        target.chmod(0o755 if name.startswith("bin/") else 0o644)


def _within(found: object, nominal: float) -> bool:
    return isinstance(found, int | float) and abs(found - nominal) <= PERIOD_TOLERANCE * nominal


def _dig(summary: Mapping[str, object], *path: str) -> object:
    found: object = summary
    for key in path:
        found = found.get(key) if isinstance(found, dict) else None
    return found


def avrsim_answers(balboa: Mapping[str, object], timing: Mapping[str, object]) -> dict[str, object]:
    """The fixtures' known answers from the two runs' summaries; stop if any is not the known one.

    The motors fixture drives Timer1 as ``Balboa32U4Motors`` does: OC1A at 20 kHz (800 cycles of
    16 MHz) with ICR1 at 400. The timing fixture reads WHO_AM_I (0x69) and CTRL2_G back (0x58),
    counts the encoders' injected edges (+30 and -15) and enters its update every 10 ms.
    """
    period = _dig(balboa, "pwm", "PB5", "period_cycles", "mean")
    if not _within(period, 800):
        raise ProvisionError(f"the simulator's OC1A period is {period!r}, not 800 cycles (20 kHz)")
    icr1 = _dig(balboa, "timer1", "icr1")
    if icr1 != 400:
        raise ProvisionError(f"the simulator's ICR1 is {icr1!r}, not 400")
    text = _dig(timing, "usart1", "text")
    lines = [line for line in str(text or "").splitlines() if line]
    expected = "W:69 G:58 L:30 R:-15"
    if not lines or lines[-1] != expected:
        raise ProvisionError(f"the timing fixture printed {lines[-1:]!r}, not {expected!r}")
    if _dig(timing, "imu", "registers_written", "CTRL2_G") != 0x58:
        raise ProvisionError("the timing fixture's CTRL2_G write was not seen on the bus")
    counts = _dig(timing, "encoders", "counts")
    if counts != {"left": 30, "right": -15}:
        raise ProvisionError(f"the simulator injected encoder counts {counts!r}, not +30 and -15")
    update = _dig(timing, "probes", "update", "period_cycles", "mean")
    entries = _dig(timing, "probes", "update", "entries")
    if not _within(update, 160_000) or not isinstance(entries, int) or entries < 99:
        raise ProvisionError(
            f"the update ran {entries!r} times every {update!r} cycles, not 100 Hz"
        )
    return {
        "oc1a_frequency_hz": _dig(balboa, "pwm", "PB5", "frequency_hz"),
        "icr1": icr1,
        "who_am_i": "69",
        "ctrl2_g": "58",
        "encoder_counts": counts,
        "update_period_cycles": update,
    }


# ---- the build --------------------------------------------------------------------------------


def _python(dest: Path, version: str, env: Mapping[str, str], uv: str) -> Path:
    """Install the pinned interpreter into the environment and name it there.

    Whatever directory provisioning is started in: uv's interpreter commands read the
    settings file of the directory they run in, so they run in provisioning's own home, and
    its search takes a virtual environment there or in any directory above before an
    installed interpreter, so it is told to take none (a checkout's ``.venv`` holding the
    pinned version was named in its place).
    """
    own = Path(env["HOME"])
    try:
        run([uv, "python", "install", version], env, cwd=own)
    except ProvisionError as exc:
        raise ProvisionError(
            f"the pinned interpreter {version} cannot be installed: {exc}"
        ) from None
    found = Path(run([uv, "python", "find", "--system", version], env, cwd=own).strip())
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


def _avrsim(dest: Path, cache: Path, work: Path) -> None:
    copy_avrsim(dest)
    env = {
        **base_environment(work),
        "PATH": f"{dest / 'node' / 'bin'}:/usr/bin:/bin",
        "npm_config_update_notifier": "false",
    }
    run(npm_ci_argv(dest / "node" / "bin" / "npm", cache), env, cwd=dest / AVRSIM)


def _own_servers(dest: Path) -> list[str]:
    (dest / "servers").mkdir()
    copied = []
    source = HERE / "servers"
    for path in sorted(source.glob("*.py")) if source.is_dir() else []:
        shutil.copyfile(path, dest / "servers" / path.name)
        copied.append(path.name)
    return copied


#: The file that says how a session is wired to the environment: the programs it finds by
#: name, what its tools need in its temporary directory, and the variables they read.
SESSION_FILE = "session.json"


def session_file(dest: Path) -> None:
    """Copy the session file into the environment's root, where the harness reads it."""
    shutil.copyfile(HERE / SESSION_FILE, dest / SESSION_FILE)


def _check_libraries(dest: Path, pins: Mapping[str, object], work: Path) -> dict[str, object]:
    env = {**base_environment(work), "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(work / "mpl")}
    out = run([str(dest / "venv" / "bin" / "python"), "-I", "-c", LIBRARY_CHECK], env)
    found = json.loads(out)
    project = (dest / "project" / "pyproject.toml").read_text(encoding="utf-8")
    for name, version in found["versions"].items():
        if f'"{name}=={version}"' not in project:
            raise ProvisionError(f"{name} {version} is not the pinned version")
    return dict(found)


def _build_fixture(dest: Path, work: Path, name: str, main: str) -> tuple[str, Path]:
    """Build a firmware fixture offline; PlatformIO's output and the ELF it built."""
    core = work / "pio-core"
    if not core.exists():
        core.mkdir()
        # The store is read-only, and PlatformIO takes lock files beside each store, so the
        # build's core directory is its own and links into the store.
        for store in ("platforms", "packages", "lib"):
            (core / store).symlink_to(dest / "platformio" / store)
    sketch = work / name
    (sketch / "src").mkdir(parents=True)
    (sketch / "platformio.ini").write_text(FIXTURE_INI, encoding="utf-8")
    (sketch / "src" / "main.cpp").write_text(main, encoding="utf-8")
    env = pio_environment(core, work, offline=True) | {
        "PLATFORMIO_BUILD_DIR": str(work / f"{name}-build"),
        "PLATFORMIO_WORKSPACE_DIR": str(work / f"{name}-workspace"),
        "PLATFORMIO_CACHE_DIR": str(work / "pio-cache"),
    }
    out = run([str(dest / "venv" / "bin" / "pio"), "run"], env, cwd=sketch)
    if (sketch / ".pio").exists():
        raise ProvisionError(f"the offline {name} build built into the module")
    return out, work / f"{name}-build" / "balboa" / "firmware.elf"


def _check_build(dest: Path, work: Path) -> tuple[dict[str, int], Path]:
    out, elf = _build_fixture(dest, work, "sketch", FIXTURE_MAIN)
    sizes: dict[str, int] = {}
    for line in out.splitlines():
        for label in ("RAM", "Flash"):
            if line.startswith(f"{label}:") and "used " in line:
                sizes[f"{label.lower()}_used_bytes"] = int(line.split("used ")[1].split()[0])
    if len(sizes) != 2:
        raise ProvisionError("the offline firmware build gave no size")
    return sizes, elf


def _simulate(
    dest: Path, work: Path, name: str, elf: Path, scenario: Mapping[str, object]
) -> dict[str, object]:
    """Run one fixture on the environment's simulator from an empty environment at the root."""
    path = work / f"{name}.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    argv = [str(dest / AVRSIM / "bin" / AVRSIM), "run", "--elf", str(elf), "--scenario", str(path),
            "--out", str(work / f"{name}.jsonl")]  # fmt: skip
    summary = json.loads(run(argv, base_environment(work), cwd=Path("/")))
    if not isinstance(summary, dict):
        raise ProvisionError(f"the simulator's {name} run gave no summary")
    return summary


def _check_avrsim(dest: Path, work: Path, balboa_elf: Path) -> dict[str, object]:
    version = run(
        [str(dest / AVRSIM / "bin" / AVRSIM), "--version"], base_environment(work), cwd=Path("/")
    )
    _, timing_elf = _build_fixture(dest, work, "timing", TIMING_MAIN)
    balboa = _simulate(dest, work, "balboa", balboa_elf, BALBOA_SCENARIO)
    timing = _simulate(dest, work, "timing", timing_elf, TIMING_SCENARIO)
    return {"version": version.strip(), **avrsim_answers(balboa, timing)}


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
        _avrsim(dest, cache, work)
        servers = _own_servers(dest)
        session_file(dest)
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
            "locks_sha256": {name: sha256_of(HERE / name) for name in built_from()},
        }
        sizes, balboa_elf = _check_build(dest, work)
        record["self_check"] = {
            "libraries": _check_libraries(dest, pins, work),
            "firmware": sizes,
            "platformio_server": _check_server(dest, work),
            "avrsim": _check_avrsim(dest, work, balboa_elf),
        }
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
