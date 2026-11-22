"""Firmware built with the provisioned environment's own PlatformIO and run on its own simulator.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``). The
build is offline: every download goes to a proxy nothing listens on, as the provisioning
self-check's build does, and PlatformIO's core directory is one of the test's own that links
into the environment's read-only store.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

INI = """[env:balboa]
platform = platformio/atmelavr@5.3.0
board = a-star32U4
framework = arduino
"""
DEAD_PROXY = "http://127.0.0.1:9"
#: The environment a program of the environment is asked from: nothing inherited.
EMPTY = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C"}


def environment() -> Path:
    named = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT")
    if not named:
        pytest.skip("no provisioned tool environment named (PHYSGATE_TOOL_ENVIRONMENT)")
    return Path(named)


def avrsim(env: Path) -> Path:
    return env / "avrsim" / "bin" / "avrsim"


def build(env: Path, where: Path, main: str) -> Path:
    """Build ``main`` for the Balboa offline; the ELF."""
    core = where / "pio-core"
    core.mkdir(parents=True)
    for name in ("platforms", "packages", "lib"):
        (core / name).symlink_to(env / "platformio" / name)
    sketch = where / "sketch"
    (sketch / "src").mkdir(parents=True)
    (sketch / "platformio.ini").write_text(INI, encoding="utf-8")
    (sketch / "src" / "main.cpp").write_text(main, encoding="utf-8")
    (where / "home").mkdir()
    env_vars = {
        **EMPTY,
        "HOME": str(where / "home"),
        "PLATFORMIO_CORE_DIR": str(core),
        "PLATFORMIO_BUILD_DIR": str(where / "build"),
        "PLATFORMIO_WORKSPACE_DIR": str(where / "workspace"),
        "PLATFORMIO_CACHE_DIR": str(where / "cache"),
        "PLATFORMIO_SETTING_ENABLE_TELEMETRY": "no",
        "PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL": "36500",
        "PLATFORMIO_NO_ANSI": "true",
        "PLATFORMIO_DISABLE_PROGRESSBAR": "true",
        "HTTP_PROXY": DEAD_PROXY,
        "HTTPS_PROXY": DEAD_PROXY,
        "ALL_PROXY": DEAD_PROXY,
    }
    done = subprocess.run(
        [str(env / "venv" / "bin" / "pio"), "run"],
        cwd=sketch, env=env_vars, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    assert done.returncode == 0, (done.stdout + done.stderr)[-3000:]
    elf = where / "build" / "balboa" / "firmware.elf"
    assert elf.is_file()
    return elf


def simulate(
    env: Path,
    elf: Path,
    scenario: dict[str, Any],
    where: Path,
    name: str = "run",
    stderr: list[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run ``elf`` under ``scenario`` from an empty environment at the root; summary and trace.

    The launcher's standard error is appended to ``stderr`` when a list is given.
    """
    where.mkdir(parents=True, exist_ok=True)
    path = where / f"{name}.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    out = where / f"{name}.jsonl"
    done = subprocess.run(
        [str(avrsim(env)), "run", "--elf", str(elf), "--scenario", str(path), "--out", str(out)],
        cwd="/", env=EMPTY, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-3000:]
    if stderr is not None:
        stderr.append(done.stderr)
    summary = json.loads(done.stdout)
    assert summary == json.loads((where / f"{name}.summary.json").read_text(encoding="utf-8"))
    header, *events = (json.loads(line) for line in out.read_text(encoding="utf-8").splitlines())
    assert header["type"] == "header" and header["elf_sha256"] == summary["elf_sha256"]
    assert header["scenario_sha256"] == summary["scenario_sha256"]
    return summary, events
