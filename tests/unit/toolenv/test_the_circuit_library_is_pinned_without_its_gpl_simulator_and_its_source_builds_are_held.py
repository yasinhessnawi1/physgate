"""The circuit library is a pin of the environment, without the GPL simulator it asks for.

SKiDL writes a schematic from a circuit described in Python. It asks for InSpice, a circuit
simulator under the GPL that every ``import skidl`` would load when installed; nothing here
simulates, and SKiDL imports without it, so the environment's project overrides it with a
marker no platform satisfies. Three packages of the circuit library publish only their
source: they are the only packages provisioning builds, each held by its digest in the lock,
with the build backend (and the one extra build requirement a package's setup asks for) held
to one exact version each. No distribution in the environment may state a GPL licence: every
installed distribution's licence fields are read and held to the allowed list. The script's
judgements are tested here on their own; a real environment is the integration test's.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLENV = REPO / "toolenv"

#: The circuit library, an exact pin of the design group.
CIRCUIT = {"skidl": "3.0.0"}
#: The GPL simulator, kept out of every environment by an override no platform satisfies.
OVERRIDE = "inspice; sys_platform == 'never'"
NEVER = "sys_platform == 'never'"
#: The packages that publish only their source, which provisioning therefore builds.
SOURCE_ONLY = {"hierplace", "kinet2pcb", "skidl"}


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("toolenv_provision", TOOLENV / "provision.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _project() -> dict[str, Any]:
    return tomllib.loads((TOOLENV / "pyproject.toml").read_text(encoding="utf-8"))


def _lock() -> dict[str, dict[str, Any]]:
    lock = tomllib.loads((TOOLENV / "uv.lock").read_text(encoding="utf-8"))
    return {package["name"]: package for package in lock["package"]}


def _raised(call: Callable[[], object]) -> BaseException | None:
    """What ``call`` raised, of any kind, so that a wrong error fails an assertion too."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - every kind is wanted here
        return exc
    return None


def _installed(site: Path, name: str, metadata: str, version: str = "1.0") -> None:
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    head = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n"
    (info / "METADATA").write_text(head + metadata + "\n\nThe description.\n", encoding="utf-8")


def _refusals(site: Path) -> list[str]:
    refusals = getattr(_provision(), "licence_refusals", lambda _site: ["no such function"])
    found = refusals(site)
    assert isinstance(found, list)
    return [str(line) for line in found]


# ---- the pins ---------------------------------------------------------------------------------


def test_the_circuit_library_is_an_exact_pin_of_the_design_group() -> None:
    group = _project().get("dependency-groups", {}).get("design", [])
    for name, version in CIRCUIT.items():
        assert f"{name}=={version}" in group
    assert _lock().get("skidl", {}).get("version") == CIRCUIT["skidl"]


def test_the_gpl_simulator_is_overridden_out_of_every_environment() -> None:
    uv = _project()["tool"]["uv"]
    assert uv.get("override-dependencies") == [OVERRIDE]
    lock = tomllib.loads((TOOLENV / "uv.lock").read_text(encoding="utf-8"))
    assert lock.get("manifest", {}).get("overrides") == [{"name": "inspice", "marker": NEVER}]
    wanted = {dep["name"]: dep.get("marker") for dep in _lock()["skidl"].get("dependencies", [])}
    assert wanted.get("inspice") == NEVER


def test_the_build_backend_and_what_a_setup_asks_for_are_each_held_to_one_exact_version() -> None:
    uv = _project()["tool"]["uv"]
    held = uv.get("build-constraint-dependencies", [])
    assert held, "the project holds no build requirement to a version"
    names = []
    for pin in held:
        found = re.fullmatch(r"([a-z0-9][a-z0-9-]*)==([0-9]+(\.[0-9]+)*)", pin)
        assert found, f"not one exact version: {pin!r}"
        names.append(found.group(1))
    assert len(names) == len(set(names))
    # setuptools builds all three; one package's setup asks for pytest-runner as well.
    assert {"setuptools", "pytest-runner"} <= set(names)


def test_the_lock_carries_the_build_constraints_so_a_frozen_install_holds_them() -> None:
    # Measured on UiA (15.11): uv 0.12.17 installing from a lock that does not carry them built
    # with setuptools 84.2.1, whatever the project names; from a lock that does, with 80.9.0.
    uv = _project()["tool"]["uv"]
    named = sorted(uv.get("build-constraint-dependencies", []))
    lock = tomllib.loads((TOOLENV / "uv.lock").read_text(encoding="utf-8"))
    carried = lock.get("manifest", {}).get("build-constraints", [])
    assert sorted(f"{c['name']}{c['specifier']}" for c in carried) == named


def _reachable(found: dict[str, dict[str, Any]]) -> set[str]:
    """Every package an environment installs: from the project, past no never-true marker."""
    root = found["physgate-tool-environment"]
    waiting = [dep["name"] for dep in root.get("dependencies", [])]
    for group in root.get("dev-dependencies", {}).values():
        waiting += [dep["name"] for dep in group]
    reached: set[str] = set()
    while waiting:
        name = waiting.pop()
        if name in reached:
            continue
        reached.add(name)
        for dep in found[name].get("dependencies", []):
            if dep.get("marker") != NEVER:
                waiting.append(dep["name"])
    return reached


def test_only_the_three_source_only_packages_are_built_each_held_by_its_digest() -> None:
    found = _lock()
    reached = _reachable(found)
    assert "skidl" in reached
    assert "inspice" not in reached
    built = {name for name in reached if not found[name].get("wheels")}
    assert built == SOURCE_ONLY
    for name in sorted(built):
        sdist = found[name].get("sdist", {})
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", sdist.get("hash", "")), name


def test_the_script_names_the_circuit_library_s_licence() -> None:
    licences = getattr(_provision(), "DESIGN_LICENCES", {})
    assert licences.get("skidl", "").startswith("MIT")
    assert "inspice" not in {name.lower() for name in licences}


# ---- the licences an installed distribution states -------------------------------------------


@pytest.mark.parametrize(
    "metadata",
    [
        "License-Expression: GPL-3.0-or-later",
        "License: GPLv3",
        "License: GNU General Public License v3 or later",
        "Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "License-Expression: MIT OR GPL-2.0-only",
        "License-Expression: AGPL-3.0-only",
    ],
)
def test_a_distribution_that_states_a_gpl_licence_is_refused_by_name(
    tmp_path: Path, metadata: str
) -> None:
    _installed(tmp_path, "rich", "License-Expression: MIT")
    _installed(tmp_path, "simulator", metadata, version="1.7")
    found = _refusals(tmp_path)
    assert len(found) == 1, found
    assert "simulator 1.7" in found[0]
    # Refused as a GPL licence, not merely as one off the allowed list.
    assert "states a GPL licence" in found[0]


def test_a_distribution_that_states_no_licence_is_refused(tmp_path: Path) -> None:
    _installed(tmp_path, "silent", "Summary: says nothing of its licence")
    found = _refusals(tmp_path)
    assert len(found) == 1, found
    assert "silent 1.0" in found[0]
    assert "no licence" in found[0]


def test_a_licence_off_the_allowed_list_is_refused(tmp_path: Path) -> None:
    _installed(tmp_path, "closed", "License: Proprietary, all rights reserved")
    found = _refusals(tmp_path)
    assert len(found) == 1, found
    assert "closed 1.0" in found[0]
    assert "allowed" in found[0]


@pytest.mark.parametrize(
    "metadata",
    [
        "License-Expression: MIT",
        "License: MIT",
        "Classifier: License :: OSI Approved :: MIT License",
        "License-Expression: BSD-3-Clause",
        "License: Apache-2.0\nClassifier: License :: OSI Approved :: Apache Software License",
    ],
)
def test_an_allowed_licence_passes(tmp_path: Path, metadata: str) -> None:
    _installed(tmp_path, "fine", metadata)
    assert _refusals(tmp_path) == []


def test_a_gpl_mention_in_a_full_licence_text_is_refused_unless_the_distribution_is_named(
    tmp_path: Path,
) -> None:
    text = (
        "License: Copyright (c) the authors.\n"
        "        All rights reserved.\n"
        "        A bundled library is under the GNU General Public License.\n"
        "Classifier: License :: OSI Approved :: BSD License"
    )
    _installed(tmp_path, "bundler", text)
    found = _refusals(tmp_path)
    assert len(found) == 1, found
    assert "bundler 1.0" in found[0]
    assert "GPL" in found[0] or "General Public" in found[0]
    named = getattr(_provision(), "LICENCE_TEXT_EXCEPTIONS", {})
    assert isinstance(named, dict)
    for name, why in named.items():
        # Each exception says why: the GPL text names a bundled part under its runtime
        # exception, not the distribution's own licence.
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", name), name
        assert len(str(why).split()) > 3, name


@pytest.mark.parametrize(
    ("opening", "refused"),
    [("Apache License", False), ("GNU GPL", True), ("Proprietary licence", True)],
)
def test_a_distribution_whose_licence_is_only_in_its_file_is_read_from_that_file(
    tmp_path: Path, opening: str, refused: bool
) -> None:
    named = getattr(_provision(), "LICENCE_FROM_FILE", {})
    assert named.get("ocpsvg") == "Apache License"
    _installed(tmp_path, "ocpsvg", "Summary: no licence field")
    licences = tmp_path / "ocpsvg-1.0.dist-info" / "licenses"
    licences.mkdir()
    (licences / "LICENSE").write_text(f"   {opening}\n   Version 2.0\n", encoding="utf-8")
    found = _refusals(tmp_path)
    assert (found != []) is refused, found


def test_every_distribution_is_read_and_all_refusals_are_named_at_once(tmp_path: Path) -> None:
    _installed(tmp_path, "one", "License-Expression: GPL-2.0-only")
    _installed(tmp_path, "two", "Summary: nothing")
    _installed(tmp_path, "three", "License-Expression: MIT")
    found = _refusals(tmp_path)
    assert sorted(line.split(" ", 1)[0] for line in found) == ["one", "two"]


def test_the_environment_check_stops_provisioning_naming_every_refusal(tmp_path: Path) -> None:
    provision = _provision()
    _installed(tmp_path, "one", "License-Expression: GPL-2.0-only")
    _installed(tmp_path, "two", "Summary: nothing")
    check = getattr(provision, "check_licences", None)
    assert callable(check), "the script has no licence check"
    raised = _raised(lambda: check(tmp_path))
    assert isinstance(raised, provision.ProvisionError), raised
    assert "one 1.0" in str(raised)
    assert "two 1.0" in str(raised)


# ---- what was built from source -------------------------------------------------------------


def _source_project(root: Path, constraint: str = "setuptools==80.9.0") -> Path:
    project = root / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        f'[tool.uv]\nbuild-constraint-dependencies = ["{constraint}"]\n', encoding="utf-8"
    )
    (project / "uv.lock").write_text(
        "version = 1\n"
        '[[package]]\nname = "kinet2pcb"\nversion = "1.1.4"\n'
        'sdist = { url = "https://example.invalid/k.tar.gz", hash = "sha256:' + "a" * 64 + '" }\n'
        '[[package]]\nname = "rich"\nversion = "15.0.0"\n'
        'wheels = [{ url = "https://example.invalid/r.whl", hash = "sha256:' + "b" * 64 + '" }]\n'
        '[[package]]\nname = "pyyaml"\nversion = "6.0.3"\n'
        'sdist = { url = "https://example.invalid/y.tar.gz", hash = "sha256:' + "c" * 64 + '" }\n',
        encoding="utf-8",
    )
    return project


def _built_wheel(cache: Path, generator: str, revision: str = "rev1") -> Path:
    import zipfile

    folder = cache / "uv" / "sdists-v9" / "pypi" / "kinet2pcb" / "1.1.4" / revision
    folder.mkdir(parents=True)
    wheel = folder / "kinet2pcb-1.1.4-py2.py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("kinet2pcb/__init__.py", "")
        archive.writestr(
            "kinet2pcb-1.1.4.dist-info/WHEEL", f"Wheel-Version: 1.0\nGenerator: {generator}\n"
        )
        archive.writestr("kinet2pcb-1.1.4.dist-info/RECORD", "kinet2pcb/__init__.py,,\n")
    return wheel


def _site_with(root: Path, *names: str) -> Path:
    site = root / "site"
    for name in names:
        (site / f"{name}.dist-info").mkdir(parents=True)
    return site


def test_an_installed_source_package_is_recorded_by_its_source_and_wheel_digests(
    tmp_path: Path,
) -> None:
    provision = _provision()
    project = _source_project(tmp_path)
    wheel = _built_wheel(tmp_path / "cache", "setuptools (80.9.0)")
    site = _site_with(tmp_path, "kinet2pcb-1.1.4", "rich-15.0.0")
    built = getattr(provision, "built_from_source", None)
    assert callable(built), "the script records nothing built from source"
    found: dict[str, Any] = {}
    raised = _raised(lambda: found.update(built(project, tmp_path / "cache", site)))
    assert raised is None, raised
    # pyyaml is held only as source too, but is not installed: nothing was built from it.
    assert sorted(found) == ["kinet2pcb"]
    entry = found["kinet2pcb"]
    assert entry["sdist_sha256"] == "a" * 64
    assert entry["wheel"] == wheel.name
    assert entry["wheel_sha256"] == provision.sha256_of(wheel)
    assert len(entry["wheel_record_sha256"]) == 64
    assert entry["built_by"] == "setuptools (80.9.0)"
    assert provision.build_constraints(project) == ["setuptools==80.9.0"]


def test_a_wheel_built_by_another_backend_than_the_one_held_stops_provisioning(
    tmp_path: Path,
) -> None:
    provision = _provision()
    project = _source_project(tmp_path)
    _built_wheel(tmp_path / "cache", "setuptools (84.2.1)")
    site = _site_with(tmp_path, "kinet2pcb-1.1.4")
    built = getattr(provision, "built_from_source", lambda *_: None)
    raised = _raised(lambda: built(project, tmp_path / "cache", site))
    assert isinstance(raised, provision.ProvisionError), raised
    assert "84.2.1" in str(raised)
    assert "80.9.0" in str(raised)


@pytest.mark.parametrize("wheels", [0, 2])
def test_a_source_package_without_exactly_one_built_wheel_stops_provisioning(
    tmp_path: Path, wheels: int
) -> None:
    provision = _provision()
    project = _source_project(tmp_path)
    for index in range(wheels):
        _built_wheel(tmp_path / "cache", "setuptools (80.9.0)", revision=f"rev{index}")
    (tmp_path / "cache" / "uv").mkdir(parents=True, exist_ok=True)
    site = _site_with(tmp_path, "kinet2pcb-1.1.4")
    built = getattr(provision, "built_from_source", lambda *_: None)
    raised = _raised(lambda: built(project, tmp_path / "cache", site))
    assert isinstance(raised, provision.ProvisionError), raised
    assert f"{wheels} wheels" in str(raised)
