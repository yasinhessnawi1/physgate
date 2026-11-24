"""Build the tool environment a run's role sessions compute and build with, offline from then on.

Run it outside every session, with the network, once per machine:

    python3 toolenv/provision.py --dest /abs/path/new-env [--cache /abs/path/cache]

Every download is held to a digest recorded before it was fetched: the interpreter by uv's own
table, each wheel by ``uv.lock``, Node by ``pins.json``, each npm package by the server's or the
simulator's ``package-lock.json``, and each PlatformIO package by its registry's checksum at the
pinned version. On Linux the display libraries the CAD kernel links are fetched as distribution
packages, each by the file name, version and sha256 in ``pins.json``. Three packages of the
circuit library publish only their source: uv builds them, each source held by its sha256 in the
lock and the build backend held by the lock's build constraints to one exact version (by version
and the lock's cut-off date, not by digest); each wheel built is recorded by its digest and the
digest of its file list, and refused if another backend built it. Every installed distribution's
licence, as its metadata states it, is held to an allowed list: none may be the GPL. Every file
is copied into the destination, never linked to a cache: a file with a second name outside the
environment could be changed through that name, unseen by anything that guards the
environment's own paths. The result is one directory:

    python/             the uv-managed interpreter
    venv/               the libraries, installed from ``uv.lock``
    project/            the project file and lock it was built from
    platformio/         PlatformIO's package store (platform, toolchain, framework, library)
    node/               the pinned Node release
    platformio-server/  the PlatformIO tool server, installed from its npm lock
    avrsim/             the AVR simulator rig (``avrsim``), on avr8js installed from its npm lock
    servers/            this repository's own tool servers
    helpers/            this repository's own helpers for the design libraries
    system-libraries/   on Linux, the display libraries the CAD kernel links, unpacked
    reference/          published CAD models a design is measured against, by their pinned digest
    provisioned.json    what was built, and what the self-check measured

KiCad's command-line program, a separate program under the GPL, is built into a root of its own
with ``--kicad-dest``, beside this one and never inside or around it: the pinned release (by
exact size and sha256) under ``app/``, copied so that no file has a second name and every link
resolves inside the copy, with its own ``provisioned.json``.

It ends by checking itself offline (the libraries import at their pins and compute, a firmware
fixture builds with every download refused, the PlatformIO server answers, two firmware
fixtures run on the simulator to their known answers, a fixture part is built, exported,
measured and hashed with the CAD kernel), and leaves every file read-only. The harness measures
the result before a run may use it; this script only builds it. It runs on any Python 3.12 and
imports nothing from the harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Mapping, Sequence
from email.parser import HeaderParser
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
#: Where a distribution package is fetched from by its file name. It serves a build after the
#: distribution's own index has moved on to a newer one, so a pin stays fetchable.
PACKAGE_FILES = "https://launchpad.net/ubuntu/+archive/primary/+files"
#: Where the system libraries for each machine are named in ``pins.json``; ``None`` where the
#: CAD kernel links nothing the machine does not always have.
SYSTEM_LIBRARY_PLATFORMS = {
    ("Darwin", "arm64"): None,
    ("Linux", "x86_64"): "linux-x86_64",
}
#: The licences of what the design libraries add, each as its own distribution states it. The
#: system libraries' full texts are kept in the environment, under
#: ``system-libraries/usr/share/doc/<package>/copyright``.
DESIGN_LICENCES = {
    "build123d": "Apache-2.0",
    "cadquery-ocp-novtk": "Apache-2.0 (the bindings); LGPL-2.1 with the Open CASCADE exception "
    "(the kernel inside the wheel)",
    "scikit-fem": "BSD-3-Clause",
    "kicad": "GPL-3.0-or-later, a separate program provisioned and run apart, never linked into"
    " the harness; its symbol, footprint and template libraries CC-BY-SA-4.0 with an exception"
    " for designs made with them",
    "system libraries": "MIT, X11 and BSD families; see each package's copyright file",
    "skidl": "MIT (and the packages it adds: MIT, BSD, Apache-2.0); the GPL circuit simulator it"
    " asks for is overridden out of the environment and never installed",
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
#: Board time for each fixture. The sketch starts 65 ms after power-on (the fuses' start-up
#: time) and the Arduino core then waits some 10 ms for the PLL before setup(), so the first
#: updates come back to back; the timing fixture runs two seconds so that its mean period is the
#: 10 ms schedule within the tolerance. Its wheels turn for half a second from 0.2 s, once
#: encoders.init() has run (+5 and -2.5 motor revolutions a second, 12 counts each), so the
#: counts it prints after that are known exactly: +30 and -15.
BALBOA_SCENARIO = {"avrsim_scenario": 1, "duration_s": 1.0}
TIMING_SCENARIO = {
    "avrsim_scenario": 1,
    "duration_s": 2.0,
    "encoders": {
        "left_rev_s": [[0, 0], [0.2, 0], [0.2001, 5], [0.7, 5], [0.7001, 0]],
        "right_rev_s": [[0, 0], [0.2, 0], [0.2001, -2.5], [0.7, -2.5], [0.7001, 0]],
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


#: What the self-check asks the design libraries: a fixture plate built, exported, measured and
#: hashed through the helpers, a closed-form load case, the same case solved by finite elements,
#: and which files the loader mapped.
DESIGN_CHECK = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
import geometry, structure
from build123d import Box, BuildPart, Cylinder, GridLocations, Mode
with BuildPart() as built:
    Box(110.0, 60.0, 3.0)
    with GridLocations(98.0, 48.0, 2, 2):
        Cylinder(1.6, 3.0, mode=Mode.SUBTRACT)
plate = built.part
exports = geometry.export(plate, sys.argv[2], "plate")
part = geometry.geometry_result(
    "plate", plate, density={"value": 1240, "unit": "kg/m**3"},
    density_source="a figure for the self-check only", exports=exports)
beam = structure.cantilever_end_load(
    "self-check", length={"value": 60, "unit": "mm"}, width={"value": 10, "unit": "mm"},
    thickness={"value": 3, "unit": "mm"}, modulus={"value": 2.3, "unit": "GPa"},
    force={"value": 1, "unit": "N"})
solved = structure.solve(
    "self-check", load_case="cantilever_end_load", part="self-check bar",
    length={"value": 60, "unit": "mm"}, width={"value": 10, "unit": "mm"},
    thickness={"value": 3, "unit": "mm"}, modulus={"value": 2.3, "unit": "GPa"},
    poisson={"value": 0.35, "unit": "1"}, force={"value": 1, "unit": "N"})
maps = "/proc/self/maps"
lines = open(maps).read().splitlines() if os.path.exists(maps) else []
mapped = sorted({line.split()[-1] for line in lines if "/" in line})
print(json.dumps({"part": part, "load_case": beam, "solve": solved, "mapped": mapped}))
"""
#: The libraries a solve names, each of which must be the pinned version.
SOLVER_LIBRARIES = ("scikit-fem", "numpy", "scipy")


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


def fetch(url: str, into: Path, work: Path, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> Path:
    """Download ``url`` into the new directory ``into``, bounded in size.

    ``curl`` fetches it, with the system's own certificate store; an interpreter's bundled one
    may be missing. The bound is :data:`MAX_DOWNLOAD_BYTES`, unless a pin states the exact size
    of its own file: that size then bounds that one download.
    """
    into.mkdir(parents=True, exist_ok=False)
    target = into / url.rsplit("/", 1)[-1]
    curl = shutil.which("curl", path="/usr/bin:/bin")
    if curl is None:
        raise ProvisionError("curl is not installed")
    argv = [curl, "-fsSL", "--proto", "=https", "--max-filesize", str(max_bytes)]
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


def system_packages(pins: Mapping[str, object], system: str, machine: str) -> list[dict[str, str]]:
    """The pinned distribution packages for a machine; none where the kernel needs none.

    Raises:
        ProvisionError: the machine is one no packages are pinned for, or a pin lacks its
            package name, version, file name, sha256 or the library it provides.
    """
    if (system, machine) not in SYSTEM_LIBRARY_PLATFORMS:
        raise ProvisionError(f"no pinned system libraries for {system} {machine}")
    name = SYSTEM_LIBRARY_PLATFORMS[(system, machine)]
    if name is None:
        return []
    libraries = pins.get("system_libraries")
    packages = libraries.get(name) if isinstance(libraries, dict) else None
    if not isinstance(packages, list) or not packages:
        raise ProvisionError(f"pins.json names no system libraries for {system} {machine}")
    found = []
    for package in packages:
        fields = {"package", "version", "file", "sha256", "provides"}
        if not isinstance(package, dict) or not fields <= set(package):
            raise ProvisionError(f"a system library's pin names {sorted(fields)}")
        if "/" in str(package["file"]) or "/" in str(package["provides"]):
            raise ProvisionError(f"{package['file']}: a pin names files, never paths")
        found.append({field: str(package[field]) for field in sorted(fields)})
    return found


def unpack_tree(archive: Path, into: Path) -> None:
    """Unpack a package's file tree (an uncompressed tar) under ``into``.

    The standard library's ``data`` filter refuses a member that would land outside ``into``,
    an absolute or escaping link, and device files.
    """
    try:
        with tarfile.open(archive, "r:") as tar:
            tar.extractall(into, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise ProvisionError(f"the package tree {archive.name} was refused: {exc}") from None


def _package_tree(package: Path, work: Path) -> Path:
    """The file tree of a distribution package, as an uncompressed tar in ``work``.

    The distribution's own tool only decompresses: nothing of the package is run or
    installed, and the tree is unpacked by :func:`unpack_tree`.
    """
    tool = shutil.which("dpkg-deb", path="/usr/bin:/bin")
    if tool is None:
        raise ProvisionError("dpkg-deb is needed to read a distribution package, and is absent")
    tree = Path(tempfile.mkdtemp(prefix="package-", dir=work)) / "tree.tar"
    with tree.open("wb") as handle:
        done = subprocess.run(  # noqa: S603
            [tool, "--fsys-tarfile", str(package)],
            env=base_environment(work),
            stdout=handle,
            stderr=subprocess.PIPE,
            timeout=STEP_TIMEOUT_S,
            check=False,
        )
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace")[-2000:]
        raise ProvisionError(f"dpkg-deb could not read {package.name}:\n{tail}")
    return tree


def place_beside_kernel(
    dest: Path, packages: Sequence[Mapping[str, str]], beside: str
) -> list[str]:
    """Link each provided library into the directory the CAD kernel's own run path searches.

    The kernel's wheel names one directory of its own for the libraries it brought; a library
    found there needs no variable set for a session and no file outside the environment.
    Each link is relative, so the environment may be restored at another path.

    Raises:
        ProvisionError: the kernel's directory is not there exactly once, or a package did
            not provide the library its pin names.
    """
    homes = sorted((dest / "venv").glob(f"lib/python*/site-packages/{beside}"))
    if len(homes) != 1 or not homes[0].is_dir():
        raise ProvisionError(f"the kernel's library directory {beside} was not found once")
    unpacked = dest / "system-libraries"
    placed = []
    for package in packages:
        name = package["provides"]
        found = sorted(unpacked.glob(f"usr/lib/*/{name}"))
        if len(found) != 1 or not found[0].resolve().is_file():
            raise ProvisionError(f"{package['file']} did not provide {name}")
        link = homes[0] / name
        link.symlink_to(os.path.relpath(found[0], homes[0]))
        placed.append(name)
    return placed


def _fetch_package(package: Mapping[str, str], into: Path, work: Path) -> Path:
    """Fetch one pinned package by its file name, or say which file and which digest are missing.

    The archive is asked by file name alone, and an older build can be dropped from it. Whoever
    reads the refusal then needs the exact file and the bytes it must have, to find the same
    package elsewhere and place it in the cache, where its digest is checked as any fetch's.
    """
    try:
        return fetch(f"{PACKAGE_FILES}/{package['file']}", into, work)
    except (ProvisionError, subprocess.TimeoutExpired) as exc:
        raise ProvisionError(
            f"the package file {package['file']} (sha256 {package['sha256']}) could not be"
            f" fetched from {PACKAGE_FILES}; placing that file in the cache's system-libraries"
            f" folder lets provisioning go on:\n{exc}"
        ) from None


def _system_libraries(
    dest: Path, pins: Mapping[str, object], cache: Path, work: Path
) -> list[dict[str, str]]:
    packages = system_packages(pins, platform.system(), platform.machine())
    if not packages:
        return []
    libraries = pins["system_libraries"]
    assert isinstance(libraries, dict)
    (dest / "system-libraries").mkdir()
    for package in packages:
        kept = cache / "system-libraries" / package["file"]
        if not kept.exists():
            # As for Node: checked before it is kept, so the cache only holds what matched.
            downloads = Path(tempfile.mkdtemp(prefix="package-", dir=work))
            fetched = _fetch_package(package, downloads / "archive", work)
            require_digest(fetched, package["sha256"])
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(fetched, kept)
        require_digest(kept, package["sha256"])
        unpack_tree(_package_tree(kept, work), dest / "system-libraries")
    place_beside_kernel(dest, packages, str(libraries["placed_beside"]))
    return packages


#: The environment's folder of published models, read-only to a session like every other file.
REFERENCE = "reference"
#: The fields of a reference model's pin, exactly these.
REFERENCE_FIELDS = frozenset({"file", "url", "sha256", "describes"})
_REFERENCE_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def reference_models(pins: Mapping[str, object]) -> list[dict[str, str]]:
    """The published models ``pins`` names to be fetched; none where it names none.

    Each is a plain file name, the ``https`` address that ends in that name, the sha256 its
    bytes must have, and what it describes, recorded before anything is fetched.

    Raises:
        ProvisionError: the models are not a list of such pins, a pin lacks a field or has
            another, or two pins name one file.
    """
    models = pins.get("reference_models")
    if models is None:
        return []
    if not isinstance(models, list):
        raise ProvisionError("pins.json's reference_models is a list of pins")
    found: list[dict[str, str]] = []
    for model in models:
        if not isinstance(model, dict) or set(model) != REFERENCE_FIELDS:
            fields = sorted(REFERENCE_FIELDS)
            raise ProvisionError(f"a reference model's pin names exactly {fields}")
        pin = {field: model[field] for field in sorted(REFERENCE_FIELDS)}
        if not all(isinstance(value, str) for value in pin.values()):
            raise ProvisionError("a reference model's pin holds text only")
        name = pin["file"]
        if not _REFERENCE_FILE.fullmatch(name):
            raise ProvisionError(f"{name!r}: a reference model's pin names a file, never a path")
        if not (pin["url"].startswith("https://") and pin["url"].endswith(f"/{name}")):
            raise ProvisionError(f"{name}: a reference model is fetched over https by its own name")
        if not _SHA256.fullmatch(pin["sha256"]):
            raise ProvisionError(f"{name}: a reference model's pin holds its sha256 in hex")
        if not pin["describes"].strip():
            raise ProvisionError(f"{name}: a reference model's pin says what it describes")
        if name in {other["file"] for other in found}:
            raise ProvisionError(f"{name}: two reference models are pinned under one name")
        found.append(pin)
    return found


def _fetch_reference(model: Mapping[str, str], into: Path, work: Path) -> Path:
    """Fetch one pinned model, or say which file, from where, and with which digest."""
    try:
        return fetch(model["url"], into, work)
    except (ProvisionError, subprocess.TimeoutExpired) as exc:
        raise ProvisionError(
            f"the reference model {model['file']} (sha256 {model['sha256']}) could not be"
            f" fetched from {model['url']}; placing that file in the cache's {REFERENCE}"
            f" folder lets provisioning go on:\n{exc}"
        ) from None


def _reference_models(
    dest: Path, pins: Mapping[str, object], cache: Path, work: Path
) -> list[dict[str, str]]:
    """Fetch each pinned model once, hold it to its pin, and copy it into ``dest/reference``.

    A download whose bytes differ is refused before it is kept, and a kept file is held to the
    pin again before it is copied; either refusal names the file, the pinned digest and the
    one found (:func:`require_digest`).
    """
    models = reference_models(pins)
    if not models:
        return []
    (dest / REFERENCE).mkdir()
    for model in models:
        kept = cache / REFERENCE / model["file"]
        if not kept.exists():
            downloads = Path(tempfile.mkdtemp(prefix="reference-", dir=work))
            fetched = _fetch_reference(model, downloads / "file", work)
            require_digest(fetched, model["sha256"])
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(fetched, kept)
        require_digest(kept, model["sha256"])
        placed = dest / REFERENCE / model["file"]
        shutil.copyfile(kept, placed)
        require_digest(placed, model["sha256"])
    return models


# ---- KiCad: a separate program, in a root of its own --------------------------------------------

#: Where each machine's KiCad release is named in ``pins.json``.
KICAD_PLATFORMS = {
    ("Linux", "x86_64"): "linux-x86_64",
    ("Darwin", "arm64"): "darwin-arm64",
}
#: The fields every KiCad pin has, and those a machine's pin may add: the image inside the Linux
#: archive with its own digest, the parts of the tree not copied, the parts of the macOS
#: application that are.
KICAD_PIN_FIELDS = frozenset({"file", "url", "bytes", "sha256"})
KICAD_PIN_OPTIONAL = frozenset({"inner", "dropped", "kept"})
#: Where the copied release lies in the KiCad root, and the record written beside it.
KICAD_APP = "app"
KICAD_RECORD = "provisioned.json"
#: The program inside the copied release on each system.
KICAD_CLI = {
    "Linux": ("bin", "kicad-cli"),
    "Darwin": ("KiCad.app", "Contents", "MacOS", "kicad-cli"),
}
#: The most links one resolution may follow, as the system's own limit does.
MAX_LINK_HOPS = 40


def kicad_pin(pins: Mapping[str, object], system: str, machine: str) -> dict[str, object]:
    """The pinned KiCad release for a machine: file name, address, exact size, sha256.

    Raises:
        ProvisionError: no release is pinned for the machine, or its pin is not exactly a
            plain file name, the ``https`` address ending in it, a positive size in bytes and a
            lower-case hex sha256 (with only the image, dropped or kept parts besides).
    """
    name = KICAD_PLATFORMS.get((system, machine))
    kicad = pins.get("kicad")
    pin = kicad.get(name) if isinstance(kicad, dict) and name else None
    if not isinstance(pin, dict):
        raise ProvisionError(f"no pinned KiCad release for {system} {machine}")
    fields = set(pin)
    if not KICAD_PIN_FIELDS <= fields <= KICAD_PIN_FIELDS | KICAD_PIN_OPTIONAL:
        raise ProvisionError(
            f"a KiCad pin names {sorted(KICAD_PIN_FIELDS)}, and of"
            f" {sorted(KICAD_PIN_OPTIONAL)} only what its machine needs"
        )
    file, url, size, digest = pin["file"], pin["url"], pin["bytes"], pin["sha256"]
    if not (isinstance(file, str) and _REFERENCE_FILE.fullmatch(file)):
        raise ProvisionError(f"{file!r}: a KiCad pin names a file, never a path")
    if not (isinstance(url, str) and url.startswith("https://") and url.endswith(f"/{file}")):
        raise ProvisionError(f"{file}: a KiCad release is fetched over https by its own name")
    if type(size) is not int or size <= 0:
        raise ProvisionError(f"{file}: a KiCad pin states its file's size in bytes")
    if not (isinstance(digest, str) and _SHA256.fullmatch(digest)):
        raise ProvisionError(f"{file}: a KiCad pin holds its sha256 in lower-case hex")
    inner = pin.get("inner")
    if inner is not None and not (
        isinstance(inner, dict)
        and set(inner) == {"file", "sha256"}
        and isinstance(inner["file"], str)
        and _REFERENCE_FILE.fullmatch(inner["file"])
        and isinstance(inner["sha256"], str)
        and _SHA256.fullmatch(inner["sha256"])
    ):
        raise ProvisionError(f"{file}: a KiCad pin's inner image is a file name and its sha256")
    for parts in ("dropped", "kept"):
        listed = pin.get(parts)
        if listed is not None and not (
            isinstance(listed, list) and all(isinstance(part, str) for part in listed)
        ):
            raise ProvisionError(f"{file}: a KiCad pin's {parts} parts are a list of paths")
    return dict(pin)


def kicad_archive(pin: Mapping[str, object], cache: Path, work: Path) -> Path:
    """The pinned release from the cache, or fetched once, bounded by its pin and held to it.

    A download whose bytes differ is refused before it is kept, and a kept file is held to the
    pin again before it is used; either refusal names the file and both digests.
    """
    file, digest, size = str(pin["file"]), str(pin["sha256"]), pin["bytes"]
    assert isinstance(size, int)
    kept = cache / "kicad" / file
    if not kept.exists():
        downloads = Path(tempfile.mkdtemp(prefix="kicad-", dir=work))
        try:
            fetched = fetch(str(pin["url"]), downloads / "archive", work, max_bytes=size)
        except (ProvisionError, subprocess.TimeoutExpired) as exc:
            raise ProvisionError(
                f"the KiCad release {file} (sha256 {digest}) could not be fetched from"
                f" {pin['url']}; placing that file in the cache's kicad folder lets"
                f" provisioning go on:\n{exc}"
            ) from None
        require_digest(fetched, digest)
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(fetched, kept)
    require_digest(kept, digest)
    return kept


def _part(source: Path, part: str) -> str:
    """Where a part of a tree, named by a plain relative path that is there, really lies in it.

    A link on the way to it is followed (a release may name its own top as ``usr``), and the
    part itself is the entry found there, whatever it is (a link too); it must lie inside the
    tree, and its place relative to the tree is what is returned.
    """
    pieces = part.split("/")
    if part.startswith("/") or any(piece in ("", ".", "..") for piece in pieces):
        raise ProvisionError(f"{part!r}: a part of the release is named by a plain relative path")
    top = os.path.realpath(source)
    place = os.path.join(os.path.realpath(source.joinpath(*pieces[:-1])), pieces[-1])
    if not os.path.lexists(place):
        raise ProvisionError(f"{part!r}: the release has no such part")
    if not place.startswith(top + os.sep):
        raise ProvisionError(f"{part!r}: a part of the release lies outside it")
    return Path(place).relative_to(top).as_posix()


def _in_parts(relative: str, parts: Sequence[str]) -> bool:
    return any(relative == part or relative.startswith(part + "/") for part in parts)


def _resolves_inside(link: Path, root: Path) -> bool:
    """Whether ``link`` resolves to something that exists inside ``root``, passing nowhere else.

    Its text is followed one component at a time, as the system follows it, a link met on the
    way being read before a later ``..`` applies; absolute text, a step above the root, more than
    :data:`MAX_LINK_HOPS` links (a loop) or an end that does not exist is refused.
    """
    top = str(root)
    current = str(link.parent)
    pending = list(reversed(os.readlink(link).split("/")))
    if os.readlink(link).startswith("/"):
        return False
    hops = 1
    while pending:
        part = pending.pop()
        if part in ("", "."):
            continue
        current = os.path.dirname(current) if part == ".." else os.path.join(current, part)
        if not (current == top or current.startswith(top + os.sep)):
            return False
        if os.path.islink(current):
            hops += 1
            text = os.readlink(current)
            if hops > MAX_LINK_HOPS or text.startswith("/"):
                return False
            current = os.path.dirname(current)
            pending.extend(reversed(text.split("/")))
    return os.path.exists(current)


def copy_apart(
    source: Path,
    into: Path,
    dropped: Sequence[str] = (),
    *,
    kept: Sequence[str] | None = None,
) -> dict[str, object]:
    """Copy a release's tree so the environment's measure accepts it, and say what that took.

    Every regular file is written anew, so a file the release gives several names (hard links)
    becomes a file under each name with one name. A link is copied with its own text and kept
    only where it resolves inside the copy; a link out of it, nowhere or round a loop stops the
    copy with its name, as does anything that is not a file, a directory or a link. The parts in
    ``dropped`` are not copied; with ``kept``, only those parts are (and the directories above
    them). Nothing is ever linked to the source.

    Raises:
        ProvisionError: a part is not a plain relative path that is there, an entry is neither
            a file, a directory nor a link, or a copied link does not resolve inside the copy.
    """
    named = {"dropped": list(dropped), "kept": None if kept is None else list(kept)}
    dropped = [_part(source, part) for part in dropped]
    kept = None if kept is None else [_part(source, part) for part in kept]
    into.mkdir(parents=True, exist_ok=False)
    files = apart = 0
    links: list[tuple[Path, str]] = []
    for directory, dirs, names in os.walk(source, followlinks=False):
        here = Path(directory).relative_to(source)
        dirs.sort()
        for name in sorted(dirs) + sorted(names):
            path = Path(directory, name)
            relative = (here / name).as_posix()
            if _in_parts(relative, dropped):
                if name in dirs:
                    dirs.remove(name)
                continue
            whole = kept is None or _in_parts(relative, kept)
            above = kept is not None and any(part.startswith(relative + "/") for part in kept)
            found = path.lstat()
            if not (whole or (above and stat.S_ISDIR(found.st_mode))):
                if name in dirs:
                    dirs.remove(name)
                continue
            target = into / relative
            if stat.S_ISLNK(found.st_mode):
                if name in dirs:
                    dirs.remove(name)
                target.symlink_to(os.readlink(path))
                links.append((target, relative))
            elif stat.S_ISDIR(found.st_mode):
                target.mkdir()
            elif stat.S_ISREG(found.st_mode):
                shutil.copyfile(path, target, follow_symlinks=False)
                target.chmod(stat.S_IMODE(found.st_mode) | 0o200)
                files += 1
                apart += found.st_nlink > 1
            else:
                raise ProvisionError(
                    f"{relative}: the release holds something that is not a file, a directory"
                    " or a link"
                )
    refused = [
        f"{relative} ({os.readlink(target)})"
        for target, relative in links
        if not _resolves_inside(target, into)
    ]
    if refused:
        raise ProvisionError(
            f"{len(refused)} links of the release lead outside it, nowhere or round a loop: "
            + "; ".join(refused[:40])
        )
    counts: dict[str, object] = {
        "files": files,
        "names_copied_apart": apart,
        "links_kept": len(links),
        "dropped": named["dropped"],
    }
    if named["kept"] is not None:
        counts["kept"] = named["kept"]
    return counts


def kicad_cli(root: Path, system: str) -> Path:
    """Where the command-line program lies in a KiCad root built on ``system``."""
    return root.joinpath(KICAD_APP, *KICAD_CLI[system])


#: Where the copied release keeps its libraries and templates, inside the KiCad root.
KICAD_SHARE = {
    "Linux": ("app", "share", "kicad"),
    "Darwin": ("app", "KiCad.app", "Contents", "SharedSupport"),
}
#: The release's own library tables, which name the libraries by the variables below.
KICAD_TABLES = ("sym-lib-table", "fp-lib-table")
#: The folder of KiCad's configuration that this release reads, beneath its configuration home.
KICAD_CONFIG_VERSION = "10.0"


def kicad_session(system: str) -> dict[str, object]:
    """How a session is wired to the KiCad root built on ``system``: the tool layer's file.

    ``kicad-cli`` on the session's search path; KiCad's configuration in the session's own
    temporary directory, with the release's library tables linked into it, so a session reads
    the pinned libraries and writes its settings nowhere else; the libraries' variables at the
    release's own folders.
    """
    share = "/".join(KICAD_SHARE[system])
    config = f"kicad-config/{KICAD_CONFIG_VERSION}"
    return {
        "programs": {"kicad-cli": "/".join((KICAD_APP, *KICAD_CLI[system]))},
        "directories": ["kicad-config", config],
        "links": {f"{config}/{table}": f"{share}/template/{table}" for table in KICAD_TABLES},
        "variables": {
            "KICAD_CONFIG_HOME": "{temp}/kicad-config",
            "KICAD10_SYMBOL_DIR": f"{{root}}/{share}/symbols",
            "KICAD10_FOOTPRINT_DIR": f"{{root}}/{share}/footprints",
            "KICAD10_TEMPLATE_DIR": f"{{root}}/{share}/template",
        },
    }


def write_kicad_session(root: Path, system: str) -> None:
    """Write the KiCad root's session file (:func:`kicad_session`) beside its copied release."""
    (root / SESSION_FILE).write_text(
        json.dumps(kicad_session(system), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def check_kicad(cli: Path, version: str, work: Path) -> dict[str, str]:
    """Ask the program its version, with every download refused and its writes in ``work``.

    Raises:
        ProvisionError: it fails, or its first line is not the pinned version, either way it is
            asked (the option, and the command).
    """
    env = base_environment(work) | {
        "KICAD_CONFIG_HOME": str(work / "kicad-config"),
        "HTTP_PROXY": DEAD_PROXY,
        "HTTPS_PROXY": DEAD_PROXY,
        "ALL_PROXY": DEAD_PROXY,
    }
    for name in ("home", "tmp", "kicad-config"):
        (work / name).mkdir(exist_ok=True)
    for asked in ("--version", "version"):
        answer = run([str(cli), asked], env).strip().splitlines()
        line = answer[0].strip() if answer else ""
        if line != version:
            raise ProvisionError(
                f"kicad-cli {asked} answered {line!r}, not the pinned version {version}"
            )
    return {"version": version, "asked": "--version, version"}


def attach_argv(image: Path, mount: Path) -> list[str]:
    """Attach a macOS disk image read-only, shown nowhere, opening nothing in it."""
    return [
        "/usr/bin/hdiutil",
        "attach",
        "-readonly",
        "-nobrowse",
        "-noautoopen",
        "-mountpoint",
        str(mount),
        str(image),
    ]


def _linux_release(archive: Path, pin: Mapping[str, object], work: Path) -> Path:
    """Unpack the archive's one image, hold it to its digest, and let it unpack its own tree.

    The image's own runtime unpacks it, with no FUSE and nothing installed; the tree it leaves
    is the one returned.
    """
    inner = pin.get("inner")
    if not isinstance(inner, dict):
        raise ProvisionError(f"{archive.name}: the Linux pin names no inner image")
    unpack = work / "kicad-archive"
    unpack.mkdir()
    try:
        with tarfile.open(archive, "r:") as tar:
            members = tar.getmembers()
            names = [member.name.removeprefix("./") for member in members]
            if names != [inner["file"]] or not members[0].isfile():
                raise ProvisionError(f"{archive.name} holds {names}, not the one image")
            tar.extractall(unpack, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise ProvisionError(f"the archive {archive.name} was refused: {exc}") from None
    image = unpack / str(inner["file"])
    require_digest(image, str(inner["sha256"]))
    image.chmod(0o755)
    out = work / "kicad-tree"
    out.mkdir()
    run([str(image), "--appimage-extract"], base_environment(work), cwd=out)
    image.unlink()
    tree = Path(os.path.realpath(out / "squashfs-root"))
    if not (tree.is_dir() and out in tree.parents):
        raise ProvisionError(f"{inner['file']} left no tree of its own to copy")
    return tree


def _macos_release(
    archive: Path, pin: Mapping[str, object], app: Path, work: Path
) -> dict[str, object]:
    """Copy the kept parts of the application from the attached image, then detach it."""
    kept = pin.get("kept")
    if not isinstance(kept, list) or not kept:
        raise ProvisionError(f"{archive.name}: the macOS pin names no kept parts")
    mount = work / "kicad-image"
    mount.mkdir()
    run(attach_argv(archive, mount), base_environment(work))
    try:
        found = [
            path
            for path in (*mount.glob("KiCad.app"), *mount.glob("*/KiCad.app"))
            if path.is_dir() and not path.is_symlink()
        ]
        if len(found) != 1:
            raise ProvisionError(f"{archive.name} holds {len(found)} KiCad applications, not one")
        return copy_apart(found[0], app / "KiCad.app", kept=[str(part) for part in kept])
    finally:
        run(["/usr/bin/hdiutil", "detach", str(mount)], base_environment(work))


def _apart(root: Path, beside: Path) -> None:
    """Refuse a KiCad root inside the environment's other root, around it, or the same."""
    a, b = os.path.realpath(root), os.path.realpath(beside)
    if a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep):
        raise ProvisionError(
            "the KiCad root may not lie inside the environment's other root, nor hold it"
        )


def provision_kicad(
    root: Path,
    cache: Path,
    pins: Mapping[str, object] | None = None,
    *,
    beside: Path | None = None,
) -> dict[str, object]:
    """Build the KiCad root at ``root``: the pinned release copied apart, checked, read-only.

    ``beside`` is the environment's other root, which this one may not lie in or around.
    ``pins`` defaults to ``pins.json`` beside this script; a test names others.
    """
    if beside is not None:
        _apart(root, beside)
    check_destination(root, REPO)
    pins = load_pins() if pins is None else pins
    system, machine = platform.system(), platform.machine()
    pin = kicad_pin(pins, system, machine)
    kicad = pins["kicad"]
    assert isinstance(kicad, dict)
    root.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    try:
        return _build_kicad(root, cache, pin, str(kicad["version"]), system)
    except BaseException:
        # A half-built root is never left for a run to find.
        _remove(root)
        raise


def _build_kicad(
    root: Path, cache: Path, pin: Mapping[str, object], version: str, system: str
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="provision-kicad-") as scratch:
        work = Path(scratch)
        for name in ("home", "tmp"):
            (work / name).mkdir()
        archive = kicad_archive(pin, cache, work)
        if system == "Linux":
            tree = _linux_release(archive, pin, work)
            dropped = pin.get("dropped", [])
            assert isinstance(dropped, list)
            copied = copy_apart(tree, root / KICAD_APP, [str(part) for part in dropped])
            _remove(work / "kicad-tree")
        else:
            copied = _macos_release(archive, pin, root / KICAD_APP, work)
        checked = check_kicad(kicad_cli(root, system), version, work)
    require_one_name_each(root)
    require_links_inside(root)
    record: dict[str, object] = {
        "kicad": version,
        "pin": dict(pin),
        "machine": f"{platform.system()} {platform.machine()}",
        "program": kicad_cli(root, system).relative_to(root).as_posix(),
        "licence": DESIGN_LICENCES["kicad"],
        "copied": copied,
        "self_check": checked,
    }
    (root / KICAD_RECORD).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_kicad_session(root, system)
    make_read_only(root)
    return record


#: The file at the environment's root that names how committed exports are regenerated.
DERIVED_FILE = "derived.json"


def derivations() -> dict[str, object]:
    """How the commit check regenerates a schematic's three text exports: the tool layer's data.

    The circuit helper's own ``regenerate`` call on the environment's interpreter, the products
    it writes into the module's exports folder named after the schematic, and the words for the
    exit code it ends with on a schematic that draws on a sub-sheet.
    """
    return {
        "derivations": [
            {
                "source": ".kicad_sch",
                "products": [".erc.json", ".net", ".csv"],
                "argv": [
                    "{interpreter}",
                    "-I",
                    "{root}/helpers/circuit.py",
                    "regenerate",
                    "{source}",
                    "{module}",
                    "{name}",
                ],
                "timeout_s": 300,
                "refusals": {
                    "3": "the schematic draws on a sub-sheet; one sheet per schematic is "
                    "checked and exported: draw the circuit in one sheet",
                },
            }
        ]
    }


def _helpers(dest: Path) -> list[str]:
    (dest / "helpers").mkdir()
    copied = []
    source = HERE / "helpers"
    for path in sorted(source.glob("*.py")) if source.is_dir() else []:
        shutil.copyfile(path, dest / "helpers" / path.name)
        copied.append(path.name)
    (dest / DERIVED_FILE).write_text(
        json.dumps(derivations(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return copied


def mapped_outside(
    mapped: Sequence[str], packages: Sequence[Mapping[str, str]], dest: Path
) -> list[str]:
    """Which provided libraries the loader took from outside the environment, or not at all.

    ``mapped`` is every file the checking process had mapped. Each library a pinned package
    provides must be among them, and the file mapped under that name must lie inside
    ``dest``: a host that happens to have the library must not be the one that served it.
    """
    root = os.path.realpath(dest)
    wrong = []
    for package in packages:
        name = package["provides"]
        files = [path for path in mapped if os.path.basename(path).startswith(name)]
        if not files:
            wrong.append(f"{name}: not loaded")
        wrong += [path for path in files if not os.path.realpath(path).startswith(root + os.sep)]
    return wrong


def _check_design(
    dest: Path, packages: Sequence[Mapping[str, str]], work: Path
) -> dict[str, object]:
    module = work / "design-module"
    module.mkdir()
    env = base_environment(work) | {
        "XDG_CACHE_HOME": str(work / "xdg-cache"),
        "HTTP_PROXY": DEAD_PROXY,
        "HTTPS_PROXY": DEAD_PROXY,
        "ALL_PROXY": DEAD_PROXY,
    }
    python = str(dest / "venv" / "bin" / "python")
    out = run([python, "-I", "-c", DESIGN_CHECK, str(dest / "helpers"), str(module)], env)
    found = json.loads(out.strip().splitlines()[-1])
    project = (dest / "project" / "pyproject.toml").read_text(encoding="utf-8")
    solved = found.get("solve")
    if not isinstance(solved, dict) or sorted(solved.get("libraries", {})) != sorted(
        SOLVER_LIBRARIES
    ):
        raise ProvisionError(f"the design check did not solve a block on {list(SOLVER_LIBRARIES)}")
    for name, version in [*found["part"]["libraries"].items(), *solved["libraries"].items()]:
        if f'"{name}=={version}"' not in project:
            raise ProvisionError(f"{name} {version} is not the pinned version")
    wrong = mapped_outside(found["mapped"], packages, dest)
    if wrong:
        raise ProvisionError(f"the kernel's display libraries are not the environment's: {wrong}")
    return {"part": found["part"], "load_case": found["load_case"], "solve": solved}


#: Imports the circuit library and names every module of the GPL simulator then loaded.
CIRCUIT_CHECK = """
import importlib.metadata as m, json, sys
import skidl
print(json.dumps({"skidl": m.version("skidl"),
    "inspice_modules": sorted(k for k in sys.modules if k.split(".")[0].lower() == "inspice")}))
"""


def _check_circuit(dest: Path, work: Path) -> dict[str, object]:
    """The circuit library imports at its pin and loads no module of the GPL simulator."""
    home = work / "circuit-home"
    home.mkdir()
    env = base_environment(work) | {
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_DATA_HOME": str(home / "data"),
    }
    out = run([str(dest / "venv" / "bin" / "python"), "-I", "-c", CIRCUIT_CHECK], env, cwd=home)
    found = json.loads(out.strip().splitlines()[-1])
    if found.get("inspice_modules"):
        raise ProvisionError(
            f"importing skidl loaded the GPL simulator: {found['inspice_modules']}"
        )
    project = (dest / "project" / "pyproject.toml").read_text(encoding="utf-8")
    if f'"skidl=={found.get("skidl")}"' not in project:
        raise ProvisionError(f"skidl {found.get('skidl')} is not the pinned version")
    return dict(found)


# ---- the licences the installed distributions state, and the packages built from source --------

#: Every licence statement an installed distribution may make, exactly as its metadata words
#: it: a ``License-Expression``, a one-line ``License`` field, or a ``License ::`` classifier.
#: Measured from the environment as locked (every one permissive); a distribution that states
#: anything else, or nothing, stops provisioning, so a new dependency's licence is read first.
ALLOWED_LICENCES = frozenset(
    {
        # License-Expression
        "Apache-2.0", "Apache-2.0 OR BSD-2-Clause", "BSD-2-Clause", "BSD-3-Clause", "MIT",
        "MIT-CMU", "PSF-2.0",
        # License, one line
        "Apache 2", "Apache 2.0", "Apache Software License", "BSD", "Dual License",
        "ISC license", "MIT License", "MIT license", "MPL-2.0", "Public domain", "Unlicense",
        # License classifiers
        "License :: OSI Approved :: Apache Software License",
        "License :: OSI Approved :: BSD License",
        "License :: OSI Approved :: ISC License (ISCL)",
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
        "License :: OSI Approved :: Python Software Foundation License",
        "License :: Public Domain",
    }
)  # fmt: skip
#: What a ``License`` field holds when it says nothing (older metadata's default).
NO_STATEMENT = frozenset({"UNKNOWN"})
#: Distributions whose full licence text (a ``License`` field over several lines) mentions the
#: GPL for a part their wheel bundles, not as their own licence.
LICENCE_TEXT_EXCEPTIONS = {
    "numpy": "the wheel bundles the GCC runtime libraries (libgfortran under GPL-3.0 with the GCC"
    " Runtime Library Exception, libquadmath under LGPL-2.1); its own licence is BSD-3-Clause",
    "scipy": "the wheel bundles the GCC runtime libraries (libgfortran under GPL-3.0 with the GCC"
    " Runtime Library Exception, libquadmath under LGPL-2.1); its own licence is BSD-3-Clause",
    "matplotlib": "the wheel bundles FreeType, offered under its own licence or GPL-2.0-or-later"
    " and used under its own; matplotlib's licence is PSF-based",
}
#: Distributions whose metadata states no licence, and the words their own licence file, in
#: their metadata folder, opens with.
LICENCE_FROM_FILE = {"bd-materials": "Apache License", "ocpsvg": "Apache License"}
#: A mention of the GPL, the Affero GPL included, and neither the Lesser nor the Library GPL.
_GPL = re.compile(r"(?<![A-Za-z])A?GPL|(?<!Lesser )(?<!Library )General Public License|Affero")


def licence_statements(metadata: str) -> tuple[list[str], list[str]]:
    """The licence statements of one distribution's metadata, and its full licence texts."""
    head = HeaderParser().parsestr(metadata, headersonly=True)
    statements = [str(value).strip() for value in head.get_all("License-Expression", [])]
    texts = []
    for value in head.get_all("License", []):
        text = str(value).strip()
        if "\n" in text:
            texts.append(text)
        elif text and text not in NO_STATEMENT:
            statements.append(text)
    statements += [
        str(value).strip()
        for value in head.get_all("Classifier", [])
        if str(value).strip().startswith("License ::")
    ]
    return statements, texts


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _licence_files(info: Path) -> list[str]:
    """The texts of the licence files a distribution's metadata folder holds."""
    folder = info / "licenses"
    files = sorted(path for path in folder.rglob("*") if path.is_file()) if folder.is_dir() else []
    return [path.read_text(encoding="utf-8", errors="replace") for path in files]


def licence_refusals(site_packages: Path) -> list[str]:
    """Each installed distribution whose licence statements are refused, with why.

    A distribution is refused if it states no licence, if a statement or a full text of it
    mentions the GPL (a full text only where :data:`LICENCE_TEXT_EXCEPTIONS` does not name
    it), or if a statement is not one of :data:`ALLOWED_LICENCES`. Every distribution is read
    and every refusal named.
    """
    refused = []
    for info in sorted(site_packages.glob("*.dist-info")):
        metadata = (info / "METADATA").read_text(encoding="utf-8", errors="replace")
        head = HeaderParser().parsestr(metadata, headersonly=True)
        who = f"{head.get('Name', info.name)} {head.get('Version', '?')}"
        statements, texts = licence_statements(metadata)
        name = _canonical(str(head.get("Name", "")))
        excepted = name in LICENCE_TEXT_EXCEPTIONS
        if not statements and not texts and name in LICENCE_FROM_FILE:
            texts = _licence_files(info)
            opening = LICENCE_FROM_FILE[name]
            if any(text.lstrip().startswith(opening) for text in texts):
                statements = [opening]
        gpl = [s for s in statements if _GPL.search(s)]
        gpl += [t for t in texts if _GPL.search(t) and not excepted]
        off = [
            s
            for s in statements
            if s not in ALLOWED_LICENCES and s not in LICENCE_FROM_FILE.values()
        ]
        if not statements:
            refused.append(f"{who}: states no licence")
        elif gpl:
            refused.append(f"{who}: states a GPL licence: {gpl[0].splitlines()[0][:80]!r}")
        elif off:
            refused.append(f"{who}: states a licence off the allowed list: {off[0][:80]!r}")
    return refused


def check_licences(site_packages: Path) -> int:
    """Stop provisioning if any installed distribution's licence is refused; how many were read.

    Raises:
        ProvisionError: naming every refused distribution.
    """
    refused = licence_refusals(site_packages)
    if refused:
        raise ProvisionError(f"refused by their licences: {'; '.join(refused)}")
    return len(list(site_packages.glob("*.dist-info")))


def build_constraints(project: Path) -> list[str]:
    """The exact versions the project holds its build requirements to, as it names them."""
    loaded = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    held = loaded.get("tool", {}).get("uv", {}).get("build-constraint-dependencies", [])
    return [str(pin) for pin in held]


def _wheel_facts(wheel: Path) -> tuple[str, str]:
    """The generator a built wheel names, and the sha256 of the file list it carries."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        generator = record = ""
        for name in names:
            if name.endswith(".dist-info/WHEEL"):
                for line in archive.read(name).decode("utf-8", errors="replace").splitlines():
                    if line.startswith("Generator:"):
                        generator = line.split(":", 1)[1].strip()
            elif name.endswith(".dist-info/RECORD"):
                record = hashlib.sha256(archive.read(name)).hexdigest()
    return generator, record


def built_from_source(project: Path, cache: Path, site_packages: Path) -> dict[str, object]:
    """Each installed package the lock holds only as source, with its source's and wheel's digests.

    The source is held by the lock's sha256; the wheel built from it is read from uv's cache,
    by its own sha256 and the sha256 of the file list inside it (which names every file it
    installs by its digest). The build backend each wheel names must be the version the
    project holds it to.

    Raises:
        ProvisionError: a package installed from source has not exactly one wheel built from it
            in the cache, or its wheel names another build backend than the one held.
    """
    lock = tomllib.loads((project / "uv.lock").read_text(encoding="utf-8"))
    stems = [info.name.removesuffix(".dist-info") for info in site_packages.glob("*.dist-info")]
    installed = {
        f"{_canonical(stem.rsplit('-', 1)[0])}=={stem.rsplit('-', 1)[-1]}" for stem in stems
    }
    held = {pin.split("==")[0]: pin.split("==")[1] for pin in build_constraints(project)}
    found: dict[str, object] = {}
    for package in lock.get("package", []):
        name, version = str(package["name"]), str(package.get("version", ""))
        if (
            "sdist" not in package
            or package.get("wheels")
            or f"{_canonical(name)}=={version}" not in installed
        ):
            continue
        wheels = [
            path
            for path in sorted((cache / "uv").glob(f"sdists-v*/*/{name}/{version}/*/*.whl"))
            if path.is_file()
        ]
        if len(wheels) != 1:
            raise ProvisionError(f"{name} {version}: {len(wheels)} wheels built from its source")
        generator, record = _wheel_facts(wheels[0])
        backend = f"setuptools ({held.get('setuptools', '?')})"
        if generator != backend:
            raise ProvisionError(
                f"{name} {version} was built by {generator!r}, not the held {backend!r}"
            )
        found[name] = {
            "version": version,
            "sdist_sha256": str(package["sdist"]["hash"]).removeprefix("sha256:"),
            "wheel": wheels[0].name,
            "wheel_sha256": sha256_of(wheels[0]),
            "wheel_record_sha256": record,
            "built_by": generator,
        }
    return found


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
        site = next((dest / "venv" / "lib").glob("python3.*/site-packages"))
        # Read before anything else is installed: every distribution's licence, and what was
        # built from source, by the digests of its source and of the wheel built from it.
        licences_read = check_licences(site)
        built = built_from_source(dest / "project", cache, site)
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
        helpers = _helpers(dest)
        system = _system_libraries(dest, pins, cache, work)
        reference = _reference_models(dest, pins, cache, work)
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
            "helpers": helpers,
            "system_libraries": system,
            "reference_models": reference,
            "licences": DESIGN_LICENCES,
            "licences_read": licences_read,
            "built_from_source": built,
            "build_constraints": build_constraints(dest / "project"),
            "locks_sha256": {name: sha256_of(HERE / name) for name in built_from()},
        }
        sizes, balboa_elf = _check_build(dest, work)
        record["self_check"] = {
            "libraries": _check_libraries(dest, pins, work),
            "firmware": sizes,
            "platformio_server": _check_server(dest, work),
            "avrsim": _check_avrsim(dest, work, balboa_elf),
            "design": _check_design(dest, system, work),
            "circuit": _check_circuit(dest, work),
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
    parser.add_argument("--kicad-dest", type=Path, help="KiCad's own root, beside --dest")
    args = parser.parse_args(argv)
    try:
        if args.kicad_dest is not None:
            _apart(args.kicad_dest, args.dest)
        with tempfile.TemporaryDirectory(prefix="provision-cache-") as fresh:
            cache = Path(fresh) if args.cache is None else args.cache
            record = provision(args.dest, cache)
            print(json.dumps(record["self_check"], sort_keys=True))
            if args.kicad_dest is not None:
                kicad = provision_kicad(args.kicad_dest, cache, beside=args.dest)
                print(json.dumps(kicad["self_check"], sort_keys=True))
    except ProvisionError as exc:
        print(f"provisioning stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
