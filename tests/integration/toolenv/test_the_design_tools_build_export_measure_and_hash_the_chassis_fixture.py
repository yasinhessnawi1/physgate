"""A part script builds, exports, measures and hashes the chassis fixture with the design tools.

The script of ``design_fixtures`` is run as a module's own, on a provisioned tool environment's
interpreter, with the helpers of this checkout (a separate test holds the environment's copies
to the same bytes), a home of its own, no display and, where this machine can take it away, no
network. What it wrote and told is then read: the result files, the exports, the numbers and
the hashes, which are the same on macOS arm64 and Linux x86_64.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``); with
none named one is built here, which needs the network once (``PHYSGATE_TOOLENV_CACHE`` keeps
the downloads).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from design_fixtures import (
    CENTRE_MM,
    CHASSIS,
    DENSITY_KG_M3,
    GEOMETRY_HASH,
    INERTIA_MM5,
    PUSHED_IN_MM3,
    VOLUME_MM3,
    chassis_argv,
    offline_prefix,
    quiet_environment,
)

from physgate.toolenv.manifest import scan
from physgate.toolenv.record import measure

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
HELPERS = REPO / "toolenv" / "helpers"
NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
PINNED = {"build123d": "0.13.0", "cadquery-ocp-novtk": "8.0.1.1.0"}
PARTS = ("plate", "motor_mount", "battery_holder")
LINUX = platform.system() == "Linux"

NET_PROBE = (
    "import socket\n"
    "try:\n"
    "    socket.create_connection(('1.1.1.1', 443), timeout=5).close()\n"
    "    print('NET-REACHED')\n"
    "except OSError:\n"
    "    print('NET-REFUSED')\n"
)


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "toolenv_provision", REPO / "toolenv" / "provision.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _writable(root: Path) -> None:
    for directory, dirs, _ in os.walk(root):
        for name in [".", *dirs]:
            path = Path(directory, name)
            if not path.is_symlink():
                path.chmod(0o755)


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if NAMED:
        yield Path(NAMED)
        return
    built = tmp_path_factory.mktemp("built") / "env"
    kept = os.environ.get("PHYSGATE_TOOLENV_CACHE")
    cache = Path(kept) if kept else tmp_path_factory.mktemp("toolenv-cache")
    _provision().provision(built, cache)
    yield built
    _writable(built)


class Run:
    """One run of the chassis script in a module directory of its own."""

    def __init__(self, env: Path, root: Path, *more: str, offline: list[str]) -> None:
        self.module = root / "modules" / "chassis"
        self.module.mkdir(parents=True)
        self.home = root / "home"
        self.home.mkdir()
        (self.module / "chassis.py").write_text(CHASSIS, encoding="utf-8")
        argv = chassis_argv(
            env / "venv" / "bin" / "python", self.module / "chassis.py", HELPERS, *more
        )
        self.done = subprocess.run(
            [*offline, *argv],
            cwd=self.module,
            env=quiet_environment(self.home),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        assert self.done.returncode == 0, self.done.stderr[-3000:]
        line = next(ln for ln in self.done.stdout.splitlines() if ln.startswith("CHASSIS "))
        self.told: dict[str, Any] = json.loads(line[len("CHASSIS ") :])

    def result(self, name: str) -> dict[str, Any]:
        found = json.loads((self.module / f"{name}.result.json").read_text(encoding="utf-8"))
        assert isinstance(found, dict)
        return found


@pytest.fixture(scope="module")
def offline() -> list[str]:
    return offline_prefix()


@pytest.fixture(scope="module")
def run(env: Path, offline: list[str], tmp_path_factory: pytest.TempPathFactory) -> Run:
    before = scan([env])
    made = Run(env, tmp_path_factory.mktemp("first"), offline=offline)
    assert scan([env]) == before, "running the part script wrote into the tool environment"
    return made


@pytest.fixture(scope="module")
def again(env: Path, offline: list[str], tmp_path_factory: pytest.TempPathFactory) -> Run:
    return Run(env, tmp_path_factory.mktemp("second"), offline=offline)


@pytest.fixture(scope="module")
def longer(env: Path, offline: list[str], tmp_path_factory: pytest.TempPathFactory) -> Run:
    return Run(env, tmp_path_factory.mktemp("longer"), "110.1", offline=offline)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _numbers_outside_a_quantity(found: object, inside: bool = False) -> list[object]:
    if isinstance(found, dict):
        has_unit = "unit" in found
        loose = []
        for name, inner in found.items():
            loose += _numbers_outside_a_quantity(inner, has_unit and name == "value")
        return loose
    if isinstance(found, list):
        return [n for inner in found for n in _numbers_outside_a_quantity(inner, inside)]
    if isinstance(found, bool) or not isinstance(found, (int, float)):
        return []
    return [] if inside else [found]


def _truth_values(found: object) -> list[bool]:
    if isinstance(found, dict):
        return [b for inner in found.values() for b in _truth_values(inner)]
    if isinstance(found, list):
        return [b for inner in found for b in _truth_values(inner)]
    return [found] if isinstance(found, bool) else []


# ---- the environment --------------------------------------------------------------------------


def test_the_harness_measures_the_environment_with_the_design_libraries_at_their_pins(
    env: Path,
) -> None:
    measured = measure(
        str(env / "venv" / "bin" / "python"),
        [str(env)],
        native={},
        forbidden={"the harness checkout": REPO},
    )
    versions = {d.name: d.version for d in measured.distributions}
    assert {name: versions.get(name) for name in PINNED} == PINNED
    assert versions.get("numpy") == "2.1.2" and versions.get("scipy") == "1.14.1"
    assert measured.entries > 30_000


def test_provisioning_recorded_what_it_fetched_placed_and_checked(env: Path) -> None:
    written = json.loads((env / "provisioned.json").read_text(encoding="utf-8"))
    own = sorted(p.name for p in HELPERS.glob("*.py"))
    assert written["helpers"] == own
    for name in own:
        assert (env / "helpers" / name).read_bytes() == (HELPERS / name).read_bytes(), name
    assert set(PINNED) <= set(written["licences"])
    pinned = json.loads((REPO / "toolenv" / "pins.json").read_text(encoding="utf-8"))
    packages = pinned["system_libraries"]["linux-x86_64"]
    assert len(packages) == 9
    check = written["self_check"]["design"]
    assert check["part"]["libraries"] == PINNED
    assert check["part"]["geometry_hash"] == GEOMETRY_HASH["plate"]
    assert check["load_case"]["values"]["tip_deflection"]["value"] == pytest.approx(
        1.3913043478260868e-3, rel=1e-12
    )
    home = env / "venv" / "lib" / "python3.12" / "site-packages" / "cadquery_ocp_novtk.libs"
    if LINUX:
        assert [p["sha256"] for p in written["system_libraries"]] == [p["sha256"] for p in packages]
        for package in packages:
            link = home / package["provides"]
            assert link.is_symlink() and not os.readlink(link).startswith("/"), package
            assert link.resolve().is_relative_to(env / "system-libraries"), package
            assert (env / "system-libraries/usr/share/doc" / package["package"]).is_dir()
    else:
        assert written["system_libraries"] == []
        assert not (env / "system-libraries").exists()


# ---- the parts: files, numbers, hashes --------------------------------------------------------


def test_the_script_ran_with_no_display_and_where_possible_no_network(
    env: Path, run: Run, offline: list[str], tmp_path: Path
) -> None:
    assert "DISPLAY" not in quiet_environment(run.home)
    if not offline:
        pytest.skip("this machine can take the network from no single process")
    probe = subprocess.run(
        [*offline, str(env / "venv" / "bin" / "python"), "-I", "-c", NET_PROBE],
        env=quiet_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert probe.stdout.strip() == "NET-REFUSED", probe.stderr[-500:]


@pytest.mark.parametrize("name", PARTS)
def test_a_part_s_volume_mass_centre_and_inertia_are_the_kernel_s_in_si(
    run: Run, name: str
) -> None:
    values = run.result(name)["values"]
    volume = VOLUME_MM3[name] * 1e-9
    assert values["volume"] == {"value": pytest.approx(volume, rel=1e-12), "unit": "m**3"}
    assert values["mass"] == {
        "value": pytest.approx(volume * DENSITY_KG_M3, rel=1e-12),
        "unit": "kg",
    }
    centre = values["centre_of_mass"]
    assert centre["unit"] == "m"
    assert centre["value"] == pytest.approx([c * 1e-3 for c in CENTRE_MM[name]], abs=1e-12)
    inertia = values["inertia"]
    assert inertia["unit"] == "kg*m**2" and inertia["about"] == "the centre of mass"
    diagonal = [inertia["value"][i][i] for i in range(3)]
    assert diagonal == pytest.approx(
        [i * 1e-15 * DENSITY_KG_M3 for i in INERTIA_MM5[name]], rel=1e-9
    )
    for i in range(3):
        for j in range(3):
            assert inertia["value"][i][j] == pytest.approx(inertia["value"][j][i], abs=1e-18)


def test_the_plate_s_numbers_agree_with_arithmetic_done_by_hand(run: Run) -> None:
    values = run.result("plate")["values"]
    # 110 x 60 x 3 mm less four holes of 3.2 mm diameter.
    by_hand = (110 * 60 * 3 - 4 * 3.141592653589793 * 1.6**2 * 3) * 1e-9
    assert values["volume"]["value"] == pytest.approx(by_hand, rel=1e-9)
    box = values["bounding_box"]
    assert box["low_corner"]["value"] == pytest.approx([-0.055, -0.030, -0.0015], abs=1e-9)
    assert box["high_corner"]["value"] == pytest.approx([0.055, 0.030, 0.0015], abs=1e-9)
    stated = run.result("plate")["inputs"]["density"]
    assert stated == {
        "value": pytest.approx(DENSITY_KG_M3),
        "unit": "kg/m**3",
        "source": "a figure for the fixture only",
    }


@pytest.mark.parametrize("name", PARTS)
def test_a_part_s_hash_is_the_one_measured_on_both_platforms(run: Run, name: str) -> None:
    assert run.result(name)["geometry_hash"] == GEOMETRY_HASH[name]


def test_the_hash_is_the_same_on_a_second_run_and_another_after_a_tenth_of_a_millimetre(
    run: Run, again: Run, longer: Run
) -> None:
    for name in PARTS:
        assert again.result(name)["geometry_hash"] == run.result(name)["geometry_hash"], name
    assert longer.result("plate")["geometry_hash"] != GEOMETRY_HASH["plate"]
    assert longer.result("motor_mount")["geometry_hash"] == GEOMETRY_HASH["motor_mount"]
    assert longer.told["assembly_hash"] != run.told["assembly_hash"]
    assert again.told["assembly_hash"] == run.told["assembly_hash"]
    assert run.told["assembly_hash"] not in set(GEOMETRY_HASH.values())


@pytest.mark.parametrize("name", PARTS)
def test_a_part_s_exports_are_in_its_exports_folder_named_by_size_and_digest(
    run: Run, name: str
) -> None:
    exports = run.result(name)["exports"]
    assert [entry["file"] for entry in exports] == [f"exports/{name}.step", f"exports/{name}.stl"]
    for entry in exports:
        path = run.module / entry["file"]
        assert path.is_file()
        assert entry["size"] == {"value": path.stat().st_size, "unit": "byte"}
        assert entry["size"]["value"] > 1000
        assert entry["sha256"] == _sha256(path)
    # A binary STL: an 80-byte header, a count, then 50 bytes for each triangle.
    stl = (run.module / "exports" / f"{name}.stl").read_bytes()
    triangles = int.from_bytes(stl[80:84], "little")
    assert triangles >= 12 and len(stl) == 84 + 50 * triangles
    step = (run.module / "exports" / f"{name}.step").read_text(encoding="utf-8", errors="replace")
    assert step.startswith("ISO-10303-21;")
    assert "AUTOMOTIVE_DESIGN" in step[:2000]


def test_a_step_file_carries_the_fixed_time_and_repeats_its_bytes(run: Run, again: Run) -> None:
    for name in PARTS:
        head = (run.module / "exports" / f"{name}.step").read_text(errors="replace")[:1500]
        assert "'2000-01-01T00:00:00'" in head, name
        one = _sha256(run.module / "exports" / f"{name}.step")
        assert one == _sha256(again.module / "exports" / f"{name}.step"), name


def test_the_module_holds_the_script_its_results_and_its_exports_and_nothing_else(
    run: Run,
) -> None:
    found = sorted(str(p.relative_to(run.module)) for p in run.module.rglob("*") if p.is_file())
    results = [f"{name}.result.json" for name in PARTS]
    results += [f"plate-motor_mount-{case}.result.json" for case in ("resting", "pushed-in")]
    results += ["plate-motor_mount-lifted.result.json", "mount-arm.result.json"]
    results += ["deck.result.json"]
    exports = [f"exports/{name}.{kind}" for name in PARTS for kind in ("step", "stl")]
    assert found == sorted(["chassis.py", *results, *exports])
    # Whatever the libraries cached on first use went under the home the run was given.
    assert all(p.is_relative_to(run.home) for p in run.home.rglob("*"))


def test_two_parts_interference_and_clearance_are_volumes_and_distances_in_si(run: Run) -> None:
    resting, pushed, lifted = (
        run.result(f"plate-motor_mount-{case}")["values"]
        for case in ("resting", "pushed-in", "lifted")
    )
    assert resting["interference_volume"] == {
        "value": pytest.approx(0.0, abs=1e-15),
        "unit": "m**3",
    }
    assert resting["clearance"] == {"value": pytest.approx(0.0, abs=1e-12), "unit": "m"}
    assert pushed["interference_volume"]["value"] == pytest.approx(PUSHED_IN_MM3 * 1e-9, rel=1e-9)
    assert pushed["clearance"]["value"] == pytest.approx(0.0, abs=1e-12)
    assert lifted["interference_volume"]["value"] == pytest.approx(0.0, abs=1e-15)
    assert lifted["clearance"]["value"] == pytest.approx(2.5e-3, rel=1e-9)
    placed = run.result("plate-motor_mount-lifted")
    assert placed["parts"] == ["plate", "motor_mount"]
    assert placed["placed_geometry_hashes"][0] == GEOMETRY_HASH["plate"]
    # The mount is hashed where it is placed, which is not where it was built.
    assert placed["placed_geometry_hashes"][1] != GEOMETRY_HASH["motor_mount"]
    assert (
        placed["placed_geometry_hashes"][1]
        != (run.result("plate-motor_mount-resting")["placed_geometry_hashes"][1])
    )


def test_the_inertia_is_about_the_centre_of_mass_wherever_the_part_is_placed(run: Run) -> None:
    built = run.result("motor_mount")["values"]
    moved = run.told["moved"]
    shift = [0.010, 0.020, 0.030]
    assert moved["centre_of_mass"]["value"] == pytest.approx(
        [c + s for c, s in zip(built["centre_of_mass"]["value"], shift, strict=True)], abs=1e-12
    )
    for i in range(3):
        assert moved["inertia"]["value"][i] == pytest.approx(
            built["inertia"]["value"][i], rel=1e-9, abs=1e-18
        )
    assert moved["mass"]["value"] == pytest.approx(built["mass"]["value"], rel=1e-12)
    assert run.told["moved_hash"] != GEOMETRY_HASH["motor_mount"]


def test_a_shape_with_a_face_not_measured_on_both_platforms_is_refused_a_hash(run: Run) -> None:
    assert "sphere" not in run.told
    assert "SPHERE" in run.told["sphere_refused"]
    assert "not been measured" in run.told["sphere_refused"]


def test_the_load_cases_are_written_as_the_beam_formulas_give_them(run: Run) -> None:
    arm = run.result("mount-arm")
    assert arm["values"]["tip_deflection"] == {
        "value": pytest.approx(1.3913043478260868e-3, rel=1e-12),
        "unit": "m",
    }
    assert arm["values"]["peak_bending_stress"]["value"] == pytest.approx(4.0e6, rel=1e-12)
    deck = run.result("deck")
    # 3 F L / (2 b h**2) with 2 N over 98 mm on a 60 x 3 mm section.
    assert deck["values"]["peak_bending_stress"]["value"] == pytest.approx(
        3 * 2 * 0.098 / (2 * 0.060 * 0.003**2), rel=1e-12
    )
    assert deck["values"]["reaction_force"]["value"] == pytest.approx(1.0)


def test_no_result_of_any_kind_holds_a_verdict_or_a_number_without_a_unit(run: Run) -> None:
    fields = {
        "geometry": {
            "schema",
            "kind",
            "part",
            "geometry_hash",
            "values",
            "inputs",
            "exports",
            "libraries",
        },
        "pair": {"schema", "kind", "parts", "placed_geometry_hashes", "values", "libraries"},
        "load_case": {
            "schema",
            "kind",
            "case",
            "model",
            "formulas",
            "assumptions",
            "inputs",
            "values",
        },
    }
    seen: set[str] = set()
    files = sorted(run.module.glob("*.result.json"))
    assert len(files) == 8
    for path in files:
        found = json.loads(path.read_text(encoding="utf-8"))
        seen.add(found["kind"])
        assert set(found) == fields[found["kind"]], path.name
        assert found["schema"] == 1
        rest = {name: inner for name, inner in found.items() if name != "schema"}
        assert _numbers_outside_a_quantity(rest) == [], path.name
        assert _truth_values(found) == [], path.name
        assert (
            path.read_text(encoding="utf-8") == json.dumps(found, sort_keys=True, indent=2) + "\n"
        )
    assert seen == set(fields)
    assert set(run.result("plate")["values"]) == {
        "volume",
        "mass",
        "centre_of_mass",
        "inertia",
        "bounding_box",
    }
    assert set(run.result("plate-motor_mount-resting")["values"]) == {
        "interference_volume",
        "clearance",
    }
    assert run.result("plate")["libraries"] == PINNED
