"""A recorded script measures what Pololu publishes no number for, from Pololu's own model.

The chassis brief asks for two dimensions of the assembled Balboa 32U4 that no drawing gives:
where each gearmotor sits relative to the board's holes, and the centre distance of the 45:21
gear pair between each motor shaft and its wheel axle. Pololu publishes a STEP model of the
assembled robot; provisioning fetched it by its pinned digest into the environment's
``reference/`` folder. The script of ``design_reference`` reads it there through the geometry
helper, finds the features by rules it writes into its result, and writes the numbers, each
with its unit; and, from the model's volumes under stated component masses, the robot's centre
of mass above the axle and its inertia about the axle, with the cases that bound them. The
numbers are the ones recorded on the first run, on every platform, to a nanometre.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment; without it one is provisioned.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from design_fixtures import offline_prefix, quiet_environment

from physgate.toolenv.manifest import manifest, scan

try:
    design_reference: ModuleType | None = importlib.import_module("design_reference")
except ImportError:  # the red rows run before the script exists
    design_reference = None

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
HELPERS = REPO / "toolenv" / "helpers"
NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
BALBOA = "balboa-balancing-robot-kit.step"


def _script() -> ModuleType:
    assert design_reference is not None, "no recorded script measures the published model"
    return design_reference


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


class Measured:
    """One run of the recorded script, from the checkout's helpers, on the named environment."""

    def __init__(self, env: Path, root: Path) -> None:
        script = _script()
        self.module = root / "modules" / "chassis"
        self.module.mkdir(parents=True)
        home = root / "home"
        home.mkdir()
        (self.module / "balboa.py").write_text(script.BALBOA, encoding="utf-8")
        argv = [str(env / "venv" / "bin" / "python"), "-I", "balboa.py", str(HELPERS), str(env)]
        self.done = subprocess.run(
            [*offline_prefix(), *argv],
            cwd=self.module,
            env=quiet_environment(home),
            capture_output=True,
            text=True,
            timeout=1200,
            check=False,
        )
        assert self.done.returncode == 0, self.done.stderr[-3000:]
        self.result: dict[str, Any] = json.loads(
            (self.module / script.BALBOA_RESULT).read_text(encoding="utf-8")
        )


@pytest.fixture(scope="module")
def measured(env: Path, tmp_path_factory: pytest.TempPathFactory) -> Measured:
    before = scan([env])
    made = Measured(env, tmp_path_factory.mktemp("balboa"))
    assert scan([env]) == before, "measuring the model wrote into the tool environment"
    return made


def _value(found: dict[str, Any], name: str) -> Any:  # noqa: ANN401 - a value as recorded
    quantity = found["values"][name]
    assert set(quantity) >= {"value", "unit"}, (name, quantity)
    return quantity["value"]


# ---- the pinned file --------------------------------------------------------------------------


def test_provisioning_placed_the_pinned_model_read_only_and_recorded_it(env: Path) -> None:
    pins = json.loads((REPO / "toolenv" / "pins.json").read_text(encoding="utf-8"))
    pinned = [m for m in pins["reference_models"] if m["file"] == BALBOA]
    assert len(pinned) == 1
    written = json.loads((env / "provisioned.json").read_text(encoding="utf-8"))
    assert written["reference_models"] == pins["reference_models"]
    placed = env / "reference" / BALBOA
    assert hashlib.sha256(placed.read_bytes()).hexdigest() == pinned[0]["sha256"]
    assert not placed.is_symlink() and placed.stat().st_mode & 0o222 == 0
    assert (env / "reference").stat().st_mode & 0o222 == 0
    assert manifest([env]).entries > 1


# ---- the measurement --------------------------------------------------------------------------


def test_the_script_names_the_pinned_file_its_rules_its_inputs_and_its_assumptions(
    request: pytest.FixtureRequest,
) -> None:
    script = _script()
    found = request.getfixturevalue("measured").result
    assert found["kind"] == "reference_measurement"
    pins = json.loads((REPO / "toolenv" / "pins.json").read_text(encoding="utf-8"))
    assert found["reference"]["file"] == f"reference/{BALBOA}"
    assert found["reference"]["sha256"] == pins["reference_models"][0]["sha256"]
    assert found["method"] == list(script.BALBOA_RULES)
    assert found["assumptions"] == list(script.BALBOA_ASSUMPTIONS)
    assert sorted(found["inputs"]) == sorted(script.BALBOA_MASSES)


def test_every_measured_number_is_the_recorded_one_on_this_platform(
    request: pytest.FixtureRequest,
) -> None:
    script = _script()
    found = request.getfixturevalue("measured").result
    assert sorted(found["values"]) == sorted(script.BALBOA_RECORDED)
    for name, (recorded, unit) in script.BALBOA_RECORDED.items():
        quantity = found["values"][name]
        assert quantity["unit"] == unit, name
        value = quantity["value"]
        recorded_list = recorded if isinstance(recorded, list) else [recorded]
        value_list = value if isinstance(value, list) else [value]
        assert len(value_list) == len(recorded_list), name
        for one, other in zip(value_list, recorded_list, strict=True):
            # A nanometre, as the geometry hash keeps; inertia and mass to a part in 10**9.
            if unit == "m":
                assert one == pytest.approx(other, abs=1e-9), name
            else:
                assert one == pytest.approx(other, rel=1e-9), name


def test_the_two_sides_agree_and_the_centre_distance_is_whole_teeth_of_one_module(
    request: pytest.FixtureRequest,
) -> None:
    found = request.getfixturevalue("measured").result
    left = _value(found, "gear_centre_distance_left")
    right = _value(found, "gear_centre_distance_right")
    # The kit is one design mirrored: the two pairs agree well inside the brief's tolerance.
    assert abs(left - right) < 0.005e-3, (left, right)
    module = _value(found, "gear_module_from_centre_distance")
    assert module == pytest.approx((left + right) / 2 / 33, rel=1e-12)


def test_the_bounds_hold_the_nominal_case(request: pytest.FixtureRequest) -> None:
    found = request.getfixturevalue("measured").result
    for name in ("centre_of_mass_above_axle", "inertia_about_axle"):
        low, nominal, high = _value(found, name)
        assert low <= nominal <= high, (name, low, nominal, high)
        assert low > 0, name


def test_no_result_holds_a_verdict_or_a_number_without_a_unit(
    request: pytest.FixtureRequest,
) -> None:
    found = request.getfixturevalue("measured").result

    def loose(node: object, inside: bool = False) -> list[object]:
        if isinstance(node, dict):
            return [n for k, v in node.items() for n in loose(v, "unit" in node and k == "value")]
        if isinstance(node, list):
            return [n for v in node for n in loose(v, inside)]
        if isinstance(node, bool):
            return [node]
        return [node] if isinstance(node, (int, float)) and not inside else []

    numbers = loose({k: v for k, v in found.items() if k != "schema"})
    assert numbers == [], numbers
