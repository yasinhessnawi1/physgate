"""A role's script reads a published model from its environment and records what it measured.

The environment carries the pinned models in ``reference/``, beside the ``helpers/`` folder a
script imports from, so the geometry helper finds a model by its file name alone, from its own
location (or from a root the script names, for a run from a checkout). It answers the path and
the file as a result names it: by name, size and sha256, the digest the pin holds. What a script
measured from such a model is written as a result of its own kind: what was measured, from which
file, by which rules the features were found, what was stated as an input, what was assumed,
and the numbers, each with its unit. Like every result it holds no verdict. Reading a real model
with the kernel is the integration test's.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

HELPERS = Path(__file__).resolve().parents[3] / "toolenv" / "helpers"
KIND = "reference_measurement"
FIELDS = sorted(
    [
        "schema",
        "kind",
        "subject",
        "reference",
        "method",
        "inputs",
        "assumptions",
        "values",
        "libraries",
    ]
)
BODY = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def _raised(call: Callable[[], object]) -> BaseException | None:
    """What ``call`` raised, of any kind, so that a wrong error fails an assertion too."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - every kind is wanted here
        return exc
    return None


def _helpers_in(env: Path) -> ModuleType:
    """The geometry helper as provisioning copies it: ``<env>/helpers``, loaded from there."""
    (env / "helpers").mkdir(parents=True)
    for name in ("geometry.py", "result_file.py"):
        shutil.copyfile(HELPERS / name, env / "helpers" / name)
    for name in ("geometry", "result_file"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("geometry", env / "helpers" / "geometry.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["geometry"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def env(tmp_path: Path) -> Path:
    root = Path(os.path.realpath(tmp_path)) / "env"
    (root / "reference").mkdir(parents=True)
    (root / "reference" / "kit.step").write_bytes(BODY)
    return root


def _reference_file(geometry: ModuleType) -> Callable[..., Any]:
    found = getattr(geometry, "reference_file", None)
    assert found is not None, "the geometry helper finds no published model"
    assert callable(found)
    return found  # type: ignore[no-any-return]


def _reference_result(geometry: ModuleType) -> Callable[..., Any]:
    found = getattr(geometry, "reference_result", None)
    assert found is not None, "the geometry helper writes no result of a published model"
    assert callable(found)
    return found  # type: ignore[no-any-return]


def _entry() -> dict[str, Any]:
    return {
        "file": "reference/kit.step",
        "size": {"value": len(BODY), "unit": "byte"},
        "sha256": hashlib.sha256(BODY).hexdigest(),
    }


def _measured(geometry: ModuleType, **changed: Any) -> dict[str, Any]:  # noqa: ANN401
    given: dict[str, Any] = {
        "method": ["the gear is the body whose name holds 'gear'"],
        "values": {"centre_distance": {"value": 0.0165, "unit": "m"}},
        "inputs": {"wheel_mass": {"value": 0.01984, "unit": "kg", "source": "a datasheet"}},
        "assumptions": ["uniform density in each body"],
    }
    given |= changed
    found = _reference_result(geometry)("the gear centre distance", _entry(), **given)
    assert isinstance(found, dict)
    return found


# ---- finding the model ------------------------------------------------------------------------


def test_the_helper_finds_a_model_beside_its_own_folder_by_name_size_and_digest(env: Path) -> None:
    geometry = _helpers_in(env)
    path, entry = _reference_file(geometry)("kit.step")
    assert Path(path) == env / "reference" / "kit.step"
    assert entry == _entry()


def test_a_script_run_from_a_checkout_names_the_environment(env: Path, tmp_path: Path) -> None:
    geometry = _helpers_in(tmp_path / "checkout" / "toolenv")
    path, entry = _reference_file(geometry)("kit.step", env)
    assert Path(path) == env / "reference" / "kit.step"
    assert entry == _entry()


@pytest.mark.parametrize("name", ["../kit.step", "reference/kit.step", "", ".step", "kit.step/"])
def test_a_name_that_is_not_a_plain_file_name_is_refused(env: Path, name: str) -> None:
    geometry = _helpers_in(env)
    found = _raised(lambda: _reference_file(geometry)(name))
    assert isinstance(found, geometry.HelperRefusedError), repr(found)


def test_a_model_the_environment_does_not_carry_is_refused(env: Path) -> None:
    geometry = _helpers_in(env)
    found = _raised(lambda: _reference_file(geometry)("other.step"))
    assert isinstance(found, geometry.HelperRefusedError), repr(found)
    assert "other.step" in str(found)


def test_a_link_in_the_reference_folder_is_refused(env: Path, tmp_path: Path) -> None:
    geometry = _helpers_in(env)
    (tmp_path / "elsewhere.step").write_bytes(BODY)
    (env / "reference" / "linked.step").symlink_to(tmp_path / "elsewhere.step")
    found = _raised(lambda: _reference_file(geometry)("linked.step"))
    assert isinstance(found, geometry.HelperRefusedError), repr(found)


# ---- the result -------------------------------------------------------------------------------


def test_a_measurement_of_a_model_is_a_result_of_its_own_kind_with_exactly_its_fields(
    env: Path,
) -> None:
    geometry = _helpers_in(env)
    result_file = sys.modules["result_file"]
    assert sorted(result_file.FIELDS.get(KIND, ())) == FIELDS
    found = _measured(geometry)
    assert sorted(found) == FIELDS
    assert found["kind"] == KIND and found["schema"] == result_file.SCHEMA
    assert found["reference"] == _entry()
    assert found["subject"] == "the gear centre distance"
    assert found["method"] == ["the gear is the body whose name holds 'gear'"]
    assert found["values"] == {"centre_distance": {"value": 0.0165, "unit": "m"}}
    assert found["assumptions"] == ["uniform density in each body"]
    assert set(found["libraries"]) == {"build123d", "cadquery-ocp-novtk"}
    assert result_file.render(found).endswith("\n")


@pytest.mark.parametrize(
    "changed",
    [
        {"method": []},
        {"method": ["  "]},
        {"method": "one rule as text"},
        {"assumptions": "one assumption as text"},
        {"assumptions": [3]},
        {"values": {"centre_distance": {"value": 0.0165, "unit": "m"}, "ok": 1}},
        {"values": {"fits": True}},
        {"inputs": {"wheel_mass": {"value": float("nan"), "unit": "kg"}}},
        {"values": []},
    ],
)
def test_a_measurement_with_no_rule_a_verdict_or_a_number_that_is_not_one_is_refused(
    env: Path, changed: dict[str, Any]
) -> None:
    geometry = _helpers_in(env)
    found = _raised(lambda: _measured(geometry, **changed))
    assert isinstance(found, geometry.HelperRefusedError), repr(found)


def test_a_measurement_names_its_file_as_the_helper_found_it(env: Path) -> None:
    geometry = _helpers_in(env)
    for entry in ({}, {"file": "reference/kit.step"}, {**_entry(), "sha256": "x"}):
        found = _raised(
            lambda entry=entry: _reference_result(geometry)(
                "the gear centre distance",
                entry,
                method=["a rule"],
                values={},
                inputs={},
                assumptions=[],
            )
        )
        assert isinstance(found, geometry.HelperRefusedError), (entry, repr(found))


@pytest.mark.parametrize("subject", ["", "  ", "a\nb", "x" * 201])
def test_a_measurement_says_in_one_short_line_what_was_measured(env: Path, subject: str) -> None:
    geometry = _helpers_in(env)
    found = _raised(
        lambda: _reference_result(geometry)(
            subject, _entry(), method=["a rule"], values={}, inputs={}, assumptions=[]
        )
    )
    assert isinstance(found, geometry.HelperRefusedError), repr(found)
