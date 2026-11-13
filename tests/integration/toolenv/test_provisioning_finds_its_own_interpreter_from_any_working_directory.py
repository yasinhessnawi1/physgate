"""Provisioning finds the interpreter it installed, whatever directory it is run from.

uv's interpreter search takes a virtual environment in the working directory, or in one above
it, before any installed interpreter, when its version is the one asked for. Run from a checkout
whose ``.venv`` holds the pinned version, provisioning was handed that one and stopped ("uv
found an interpreter outside the environment"). The row runs provisioning's interpreter step
from such a checkout.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment. Its interpreter is copied, so
the step installs nothing and downloads nothing, and the named environment is only read.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.integration

NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
ENV = Path(NAMED) if NAMED else None
TOOLENV = Path(__file__).resolve().parents[3] / "toolenv"


def _provision() -> ModuleType:
    path = TOOLENV / "provision.py"
    assert path.is_file(), "the tool environment has no provisioning script"
    spec = importlib.util.spec_from_file_location("toolenv_provision_cwd", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _writable_copy(source: Path, into: Path) -> None:
    shutil.copytree(source, into, symlinks=True)
    for path in [into, *into.rglob("*")]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | 0o200)


@pytest.mark.skipif(ENV is None, reason="no provisioned tool environment named")
def test_the_interpreter_step_run_from_a_checkout_with_a_venv_finds_the_environment_s_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ENV is not None
    uv = shutil.which("uv")
    assert uv is not None, "uv is not on PATH"
    provision = _provision()
    version = str(provision.load_pins()["python"])
    dest = tmp_path / "env"
    dest.mkdir()
    _writable_copy(ENV / "python", dest / "python")
    installed = sorted((dest / "python").glob(f"cpython-{version}-*/bin/python3"))
    assert installed, f"the environment holds no interpreter {version}"

    # A checkout whose own virtual environment holds the pinned version.
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    venv = checkout / ".venv"
    subprocess.run([str(installed[0]), "-m", "venv", "--without-pip", str(venv)], check=True)
    work = tmp_path / "work"
    for name in ("home", "tmp", "bin"):
        (work / name).mkdir(parents=True)
    env = provision.uv_environment(dest, tmp_path / "cache", work)

    # The control: from the checkout, uv's search takes the checkout's own interpreter.
    plain = subprocess.run(
        [uv, "python", "find", version],
        env=env,
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    # Its directory, resolved; the program itself is a link to the interpreter it was made from.
    taken = os.path.realpath(Path(plain.stdout.strip()).parent) if plain.stdout.strip() else None
    assert taken == os.path.realpath(venv / "bin"), plain

    monkeypatch.chdir(checkout)
    try:
        found: object = provision._python(dest, version, env, uv)
    except provision.ProvisionError as exc:
        found = exc
    assert isinstance(found, Path), found
    assert dest / "python" in found.parents, found
