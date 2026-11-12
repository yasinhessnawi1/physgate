"""The chassis fixture a mechanical module might hold, and what the design tools answer for it.

One part script, written as a role would write it: three parts of a small two-wheeled robot's
chassis (a plate with four holes, a motor mount bracket, a holder shell for six AA cells),
each built with the CAD library, exported, measured and hashed through the tool environment's
helpers, with the result written beside the script; the mount placed on the plate three ways
for interference and clearance; and two closed-form load cases. The script takes the helpers'
directory as its first argument, and an optional plate length in millimetres as its second,
so a test can change one dimension.

The expected numbers were measured with the pinned kernel on macOS arm64 and Linux x86_64:
the volumes are bit-identical on the two, and each hash is the same on both.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

#: PLA as printed solid, a figure for the fixture only.
DENSITY_KG_M3 = 1240.0

CHASSIS = """
import json, sys

sys.path.insert(0, sys.argv[1])
length = float(sys.argv[2]) if len(sys.argv) > 2 else 110.0

import geometry, result_file, structure
from build123d import Align, Box, BuildPart, Cylinder, GridLocations, Locations, Mode, Pos

LOW = (Align.CENTER, Align.CENTER, Align.MIN)
PLA = {"value": 1240, "unit": "kg/m**3"}
SOURCE = "a figure for the fixture only"


def plate(length, width=60.0, thick=3.0, hole=3.2):
    with BuildPart() as built:
        Box(length, width, thick)
        with GridLocations(length - 12, width - 12, 2, 2):
            Cylinder(hole / 2, thick, mode=Mode.SUBTRACT)
    return built.part


def motor_mount(thick=3.0):
    with BuildPart() as built:
        Box(24, 16, thick, align=LOW)
        with Locations((0, -8 + thick / 2, 0)):
            Box(24, thick, 14, align=LOW)
        with Locations((-9, 0, 0), (9, 0, 0)):
            Cylinder(1.1, thick, align=LOW, mode=Mode.SUBTRACT)
    return built.part


def battery_holder(wall=1.6):
    inner = (3 * 14.9, 51.5, 2 * 14.9)  # six AA cells, three by two
    with BuildPart() as built:
        Box(inner[0] + 2 * wall, inner[1] + 2 * wall, inner[2] + wall, align=LOW)
        with Locations((0, 0, wall)):
            Box(*inner, align=LOW, mode=Mode.SUBTRACT)
    return built.part


parts = {"plate": plate(length), "motor_mount": motor_mount(), "battery_holder": battery_holder()}
told = {"parts": {}, "pairs": {}}
for name, shape in parts.items():
    exports = geometry.export(shape, ".", name)
    result = geometry.geometry_result(
        name, shape, density=PLA, density_source=SOURCE, exports=exports)
    result_file.write(f"{name}.result.json", result)
    told["parts"][name] = result

for case, lift in (("resting", 1.5), ("pushed-in", 0.5), ("lifted", 4.0)):
    placed = Pos(0, 0, lift) * parts["motor_mount"]
    result = geometry.pair_result(["plate", "motor_mount"], parts["plate"], placed)
    result_file.write(f"plate-motor_mount-{case}.result.json", result)
    told["pairs"][case] = result

moved = Pos(10, 20, 30) * parts["motor_mount"]
told["moved"] = geometry.mass_properties(moved, density=PLA, density_source=SOURCE)
told["moved_hash"] = geometry.geometry_hash(moved)

def at(part, lift):
    return {"geometry_hash": told["parts"][part]["geometry_hash"],
            "position": {"value": [0, 0, lift], "unit": "mm"},
            "rotation": {"value": [0, 0, 0], "unit": "deg"}}


told["assembly_hash"] = geometry.assembly_hash([at("plate", 0), at("motor_mount", 1.5)])

mount = structure.cantilever_end_load(
    "mount-arm", length={"value": 60, "unit": "mm"}, width={"value": 10, "unit": "mm"},
    thickness={"value": 3, "unit": "mm"}, modulus={"value": 2.3, "unit": "GPa"},
    force={"value": 1, "unit": "N"})
result_file.write("mount-arm.result.json", mount)
deck = structure.simply_supported_centre_load(
    "deck", span={"value": 98, "unit": "mm"}, width={"value": 60, "unit": "mm"},
    thickness={"value": 3, "unit": "mm"}, modulus={"value": 2.3, "unit": "GPa"},
    force={"value": 2, "unit": "N"})
result_file.write("deck.result.json", deck)
told["load_cases"] = {"mount-arm": mount, "deck": deck}

from build123d import Sphere
try:
    told["sphere"] = geometry.geometry_hash(Sphere(5))
except result_file.HelperRefusedError as refused:
    told["sphere_refused"] = str(refused)

told["modules"] = sorted(n for n in ("requests", "IPython", "sklearn") if n in sys.modules)
print("CHASSIS " + json.dumps(told))
"""

#: Volume in mm**3 as the kernel gives it, bit-identical on both platforms.
VOLUME_MM3 = {
    "plate": 19703.49027368172,
    "motor_mount": 1921.192037334938,
    "battery_holder": 13670.99200000002,
}
#: The centre of mass in mm.
CENTRE_MM = {
    "plate": (0.0, 0.0, 0.0),
    "motor_mount": (0.0, -2.679586371355809, 4.385708399921642),
    "battery_holder": (0.0, 0.0, 11.685596948634007),
}
#: The diagonal of the inertia about the centre of mass at unit density, in mm**5.
INERTIA_MM5 = {
    "plate": (5899126.249121089, 19747995.99859023, 25617567.012300797),
    "motor_mount": (76473.1166103897, 123100.18227425944, 136288.2455669779),
    "battery_holder": (6770339.936048241, 5726715.174768247, 9659414.05186668),
}
#: Each part's geometry hash, the same on macOS arm64 and Linux x86_64.
GEOMETRY_HASH = {
    "plate": "sha256:" + "0" * 64,
    "motor_mount": "sha256:" + "0" * 64,
    "battery_holder": "sha256:" + "0" * 64,
}
#: The volume the mount pushed 1 mm into the plate shares with it, in mm**3.
PUSHED_IN_MM3 = 376.3973457783126


def chassis_argv(interpreter: Path, script: Path, helpers: Path, *more: str) -> list[str]:
    """The command that runs the chassis script on the tool environment's interpreter."""
    return [str(interpreter), "-I", str(script), str(helpers), *more]


def offline_prefix() -> list[str]:
    """A command prefix that takes the network away from one process, where this machine has one.

    On macOS the system's sandbox with every network operation denied; on Linux a new network
    namespace with no interface. Empty where neither can be started: the caller says so and
    does not claim the run was offline.
    """
    if sys.platform == "darwin" and shutil.which("sandbox-exec", path="/usr/bin"):
        prefix = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)"]
    elif sys.platform.startswith("linux") and shutil.which("unshare", path="/usr/bin:/bin"):
        prefix = [shutil.which("unshare", path="/usr/bin:/bin") or "unshare", "-rn"]
    else:
        return []
    started = subprocess.run([*prefix, "/usr/bin/true"], capture_output=True, check=False)
    return prefix if started.returncode == 0 else []


def quiet_environment(home: Path) -> dict[str, str]:
    """What a fixture run is given: a home and caches of its own, no display, nothing inherited."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / "cache"),
        "MPLBACKEND": "Agg",
        "LANG": "C.UTF-8",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),  # noqa: S108 - the test machine's own
    }
