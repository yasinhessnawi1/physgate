"""The hooks' installation is held to its build: the package to the source, all of it to a manifest.

A stand-in installation is laid out the way the builder lays one out (the
``physgate`` script, ``pyvenv.cfg``, the package copied from the source, one
dependency, the environment's own ``.pth``) and its manifest is written by the
same function the builder uses. Each test then plants,
changes or removes one thing and expects the check to refuse the run, naming it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import physgate
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.install import (
    MANIFEST_NAME,
    build_record_path,
    install_manifest,
    require_current,
    write_build_record,
)

SOURCE = Path(physgate.__file__).resolve().parent
ROOT = SOURCE.parents[1]


def stand_in(tmp_path: Path) -> tuple[Path, Path]:
    dest = tmp_path / "install"
    site = dest / "lib" / "python3.12" / "site-packages"
    shutil.copytree(SOURCE, site / "physgate", ignore=shutil.ignore_patterns("__pycache__"))
    (site / "pint").mkdir()
    (site / "pint" / "__init__.py").write_text("VERSION = '0.26.1'\n")
    (site / "_virtualenv.pth").write_text("import _virtualenv\n")
    (dest / "bin").mkdir()
    (dest / "bin" / "physgate").write_text(
        "#!/install/bin/python\nimport sys\nfrom physgate.orchestrator.cli import main\n"
    )
    (dest / "pyvenv.cfg").write_text("home = /usr/bin\ninclude-system-site-packages = false\n")
    (dest / MANIFEST_NAME).write_text(json.dumps(install_manifest(dest)))
    write_build_record(dest)
    return dest, site


def test_an_installation_as_its_build_left_it_is_accepted(tmp_path: Path) -> None:
    dest, site = stand_in(tmp_path)
    require_current(dest, ROOT)
    manifest = json.loads((dest / MANIFEST_NAME).read_text())
    prefix = "lib/python3.12/site-packages/"
    assert {prefix + "_virtualenv.pth", prefix + "physgate/gate/runner.py"} <= set(manifest)
    assert {"bin/physgate", "pyvenv.cfg"} <= set(manifest)


@pytest.mark.parametrize(
    ("path", "tampered"),
    [
        (
            "bin/physgate",
            "#!/install/bin/python\nimport os; os.system('touch /tmp/planted')\n",
        ),
        ("pyvenv.cfg", "home = /usr/bin\ninclude-system-site-packages = true\n"),
    ],
)
def test_a_changed_script_or_interpreter_setting_refuses_the_run(
    tmp_path: Path, path: str, tampered: str
) -> None:
    # The script every hook runs through, and the setting that lets the
    # interpreter import from outside the installation: neither is site-packages.
    dest, _ = stand_in(tmp_path)
    (dest / path).write_text(tampered)
    with pytest.raises(InvocationError, match="not what its build produced") as caught:
        require_current(dest, ROOT)
    assert caught.value.context["changed"] == path


def test_a_planted_compiled_cache_refuses_the_run(tmp_path: Path) -> None:
    # A read-only installation never gains a compiled cache by running, and one
    # planted beside its source runs in place of the source.
    dest, site = stand_in(tmp_path)
    (site / "pint" / "__pycache__").mkdir()
    (site / "pint" / "__pycache__" / "__init__.cpython-312.pyc").write_bytes(b"\0")
    with pytest.raises(InvocationError, match="not what its build produced") as caught:
        require_current(dest, ROOT)
    assert "pint/__pycache__/__init__.cpython-312.pyc" in caught.value.context["added"]


@pytest.mark.parametrize(
    "planted",
    ["evil.pth", "sitecustomize.py", "usercustomize.py", "pint/extra.py"],
)
def test_a_file_the_build_did_not_produce_refuses_the_run(tmp_path: Path, planted: str) -> None:
    dest, site = stand_in(tmp_path)
    (site / planted).write_text("import os; os.system('true')\n")
    with pytest.raises(InvocationError, match="not what its build produced") as caught:
        require_current(dest, ROOT)
    assert "lib/python3.12/site-packages/" + planted in caught.value.context["added"]


def test_a_changed_or_removed_dependency_file_refuses_the_run(tmp_path: Path) -> None:
    dest, site = stand_in(tmp_path)
    (site / "pint" / "__init__.py").write_text("VERSION = 'planted'\n")
    with pytest.raises(InvocationError) as changed:
        require_current(dest, ROOT)
    assert changed.value.context["changed"] == "lib/python3.12/site-packages/pint/__init__.py"
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


def test_the_build_records_the_manifest_s_digest_outside_the_installation(tmp_path: Path) -> None:
    dest, _ = stand_in(tmp_path)
    record = build_record_path(dest)
    assert record.parent == dest.parent and record.name == "install.build.json"
    assert json.loads(record.read_text())["installation"] == str(dest)


def test_a_planted_file_with_the_manifest_rewritten_to_match_refuses_the_run(
    tmp_path: Path,
) -> None:
    # The reviewer's case: a .pth planted and the manifest inside the installation
    # rewritten to list it. The manifest agrees with the files; the build's record
    # outside does not agree with the manifest.
    dest, site = stand_in(tmp_path)
    (site / "zz_planted.pth").write_text("import os\n")
    (dest / MANIFEST_NAME).write_text(json.dumps(install_manifest(dest)))
    with pytest.raises(InvocationError, match="not the one its build recorded"):
        require_current(dest, ROOT)


def test_an_installation_without_its_build_record_is_refused(tmp_path: Path) -> None:
    dest, _ = stand_in(tmp_path)
    record = build_record_path(dest)
    record.chmod(0o600)
    record.unlink()
    with pytest.raises(InvocationError, match="no record of its build"):
        require_current(dest, ROOT)
