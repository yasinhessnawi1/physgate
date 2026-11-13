"""Provisioning finds the interpreter it installed, whatever directory it is run from.

uv's interpreter search takes a virtual environment in the working directory, or in one above
it, before any installed interpreter, when its version is the one asked for. Run from a checkout
whose ``.venv`` holds the pinned version, provisioning was handed that one and stopped ("uv
found an interpreter outside the environment"). uv's interpreter commands also read the
settings file of the directory they run in. The rows run provisioning's interpreter step from
such a checkout, with its scratch directory beneath one, and from a checkout whose settings
file uv cannot run under.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment. Its interpreter is copied, so
the step installs nothing and downloads nothing, and the named environment is only read.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("PHYSGATE_TOOL_ENVIRONMENT"),
        reason="no provisioned tool environment named",
    ),
]

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


@dataclass(frozen=True)
class Step:
    provision: ModuleType
    uv: str
    version: str
    dest: Path
    interpreter: Path

    def run_from(self, cwd: Path, work: Path) -> object:
        """The interpreter step, started in ``cwd`` with ``work`` as provisioning's scratch."""
        for name in ("home", "tmp", "bin"):
            (work / name).mkdir(parents=True)
        env = self.provision.uv_environment(self.dest, work.parent / "cache", work)
        before = Path.cwd()
        os.chdir(cwd)
        try:
            return self.provision._python(self.dest, self.version, env, self.uv)
        except self.provision.ProvisionError as exc:
            return exc
        finally:
            os.chdir(before)

    def holds_its_own(self, found: object) -> None:
        assert isinstance(found, Path), found
        assert self.dest / "python" in found.parents, found


@pytest.fixture
def step(tmp_path: Path) -> Step:
    named = Path(os.environ["PHYSGATE_TOOL_ENVIRONMENT"])
    uv = shutil.which("uv")
    assert uv is not None, "uv is not on PATH"
    provision = _provision()
    version = str(provision.load_pins()["python"])
    dest = tmp_path / "env"
    dest.mkdir()
    shutil.copytree(named / "python", dest / "python", symlinks=True)
    for path in [dest / "python", *(dest / "python").rglob("*")]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | 0o200)
    installed = sorted((dest / "python").glob(f"cpython-{version}-*/bin/python3"))
    assert installed, f"the environment holds no interpreter {version}"
    return Step(provision, uv, version, dest, installed[0])


def _checkout_with_a_venv(step: Step, where: Path) -> Path:
    """A checkout whose own virtual environment holds the pinned version."""
    where.mkdir()
    venv = where / ".venv"
    subprocess.run([str(step.interpreter), "-m", "venv", "--without-pip", str(venv)], check=True)
    # The control: from the checkout, uv's own search takes the checkout's interpreter.
    work = where.parent / "control"
    for name in ("home", "tmp", "bin"):
        (work / name).mkdir(parents=True)
    plain = subprocess.run(
        [step.uv, "python", "find", step.version],
        env=step.provision.uv_environment(step.dest, work / "cache", work),
        cwd=where,
        capture_output=True,
        text=True,
        check=False,
    )
    # Its directory, resolved; the program itself is a link to the interpreter it was made from.
    taken = os.path.realpath(Path(plain.stdout.strip()).parent) if plain.stdout.strip() else None
    assert taken == os.path.realpath(venv / "bin"), plain
    return where


def test_run_from_a_checkout_whose_venv_holds_the_pinned_version(
    step: Step, tmp_path: Path
) -> None:
    checkout = _checkout_with_a_venv(step, tmp_path / "checkout")
    step.holds_its_own(step.run_from(checkout, tmp_path / "work"))


def test_run_with_its_scratch_beneath_a_checkout_whose_venv_holds_the_pinned_version(
    step: Step, tmp_path: Path
) -> None:
    # Provisioning's scratch follows the caller's temporary directory, which may lie in a
    # checkout: no directory the step runs in, nor any above it, picks the interpreter.
    checkout = _checkout_with_a_venv(step, tmp_path / "checkout")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    step.holds_its_own(step.run_from(elsewhere, checkout / "tmp" / "provision-1"))


def test_run_from_a_checkout_whose_settings_file_uv_cannot_run_under(
    step: Step, tmp_path: Path
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "uv.toml").write_text('required-version = "==0.0.1"\n', encoding="utf-8")
    # The control: from the checkout, uv refuses to run under that file.
    refused = subprocess.run(
        [step.uv, "python", "find", step.version],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused.returncode != 0 and "0.0.1" in refused.stderr, refused
    step.holds_its_own(step.run_from(checkout, tmp_path / "work"))
