"""The hooks' installation is held to its build: the package to the source, the rest to a manifest.

A stand-in installation is laid out the way the builder lays one out (the package
copied from the source, one dependency, the environment's own ``.pth``) and its
manifest is written by the same function the builder uses. Each test then plants,
changes or removes one thing and expects the check to refuse the run, naming it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import physgate
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.install import MANIFEST_NAME, require_current, site_manifest

SOURCE = Path(physgate.__file__).resolve().parent
ROOT = SOURCE.parents[1]


def stand_in(tmp_path: Path) -> tuple[Path, Path]:
    dest = tmp_path / "install"
    site = dest / "lib" / "python3.12" / "site-packages"
    shutil.copytree(SOURCE, site / "physgate", ignore=shutil.ignore_patterns("__pycache__"))
    (site / "pint").mkdir()
    (site / "pint" / "__init__.py").write_text("VERSION = '0.26.1'\n")
    (site / "_virtualenv.pth").write_text("import _virtualenv\n")
    (dest / MANIFEST_NAME).write_text(json.dumps(site_manifest(site)))
    return dest, site


def test_an_installation_as_its_build_left_it_is_accepted(tmp_path: Path) -> None:
    dest, site = stand_in(tmp_path)
    require_current(dest, ROOT)
    manifest = json.loads((dest / MANIFEST_NAME).read_text())
    assert "_virtualenv.pth" in manifest and "physgate/gate/runner.py" in manifest


def test_compiled_caches_are_not_drift(tmp_path: Path) -> None:
    dest, site = stand_in(tmp_path)
    (site / "pint" / "__pycache__").mkdir()
    (site / "pint" / "__pycache__" / "__init__.cpython-312.pyc").write_bytes(b"\0")
    require_current(dest, ROOT)


@pytest.mark.parametrize(
    "planted",
    ["evil.pth", "sitecustomize.py", "usercustomize.py", "pint/extra.py"],
)
def test_a_file_the_build_did_not_produce_refuses_the_run(tmp_path: Path, planted: str) -> None:
    dest, site = stand_in(tmp_path)
    (site / planted).write_text("import os; os.system('true')\n")
    with pytest.raises(InvocationError, match="not what its build produced") as caught:
        require_current(dest, ROOT)
    assert planted in caught.value.context["added"]


def test_a_changed_or_removed_dependency_file_refuses_the_run(tmp_path: Path) -> None:
    dest, site = stand_in(tmp_path)
    (site / "pint" / "__init__.py").write_text("VERSION = 'planted'\n")
    with pytest.raises(InvocationError) as changed:
        require_current(dest, ROOT)
    assert changed.value.context["changed"] == "pint/__init__.py"
    (site / "_virtualenv.pth").unlink()
    with pytest.raises(InvocationError) as removed:
        require_current(dest, ROOT)
    assert "_virtualenv.pth" in removed.value.context["removed"]


def test_a_module_planted_in_the_installed_gate_refuses_the_run(tmp_path: Path) -> None:
    dest, site = stand_in(tmp_path)
    (site / "physgate" / "gate" / "check_pass.py").write_text("PASS = True\n")
    with pytest.raises(InvocationError, match="not the source as it is now") as caught:
        require_current(dest, ROOT)
    assert "gate/check_pass.py (not in the source)" in caught.value.context["differs"]


def test_an_installation_without_its_manifest_is_refused(tmp_path: Path) -> None:
    dest, _ = stand_in(tmp_path)
    (dest / MANIFEST_NAME).unlink()
    with pytest.raises(InvocationError, match="no manifest"):
        require_current(dest, ROOT)
