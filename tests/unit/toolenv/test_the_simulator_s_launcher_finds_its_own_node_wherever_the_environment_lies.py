"""The simulator's launcher finds its Node and its sources from where it really lies.

A session finds ``avrsim`` by name through a link in a directory of its own; a run records it
by its version line, asked from an empty environment at the filesystem root. The launcher
therefore follows the link to the file it names and takes the Node beside the environment it
lies in, never one from the search path, and the same environment moved to another root is the
same environment. Node's own start-up variables are dropped, since they would load code from
outside the environment into the process whose output is the evidence.

A tree here stands in for a provisioned one: the rig's real launcher and sources, the Node on the
search path, and a package file in place of the simulator library (the version line and a
scenario's check load no more).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from avrsim_node import RIG, node

EMPTY = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C"}


def _environment(root: Path) -> Path:
    """A tree laid out as provisioning lays the simulator out; its launcher's path."""
    (root / "node" / "bin").mkdir(parents=True)
    (root / "node" / "bin" / "node").symlink_to(os.path.realpath(node()))
    rig = root / "avrsim"
    (rig / "bin").mkdir(parents=True)
    shutil.copy2(RIG / "bin" / "avrsim", rig / "bin" / "avrsim")
    shutil.copytree(RIG / "src", rig / "src")
    shutil.copy2(RIG / "package.json", rig / "package.json")
    (rig / "node_modules" / "avr8js").mkdir(parents=True)
    (rig / "node_modules" / "avr8js" / "package.json").write_text(
        '{"name": "avr8js", "version": "0.21.1"}', encoding="utf-8"
    )
    return rig / "bin" / "avrsim"


def _version(launcher: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(launcher), "--version"],
        cwd="/",
        env=env or EMPTY,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _node_version() -> str:
    return (
        subprocess.run([node(), "--version"], capture_output=True, text=True, check=True)
        .stdout.strip()
        .lstrip("v")
    )


def test_the_version_line_is_answered_from_an_empty_environment_at_the_root(tmp_path: Path) -> None:
    launcher = _environment(tmp_path / "env")
    done = _version(launcher)
    assert done.returncode == 0, done.stderr
    assert done.stdout == f"avrsim 0.3.0 avr8js 0.21.1 node {_node_version()}\n"


def test_the_launcher_is_found_through_the_link_a_session_s_search_path_names(
    tmp_path: Path,
) -> None:
    launcher = _environment(tmp_path / "env")
    session_bin = tmp_path / "session" / "bin"
    session_bin.mkdir(parents=True)
    (session_bin / "avrsim").symlink_to(launcher)
    # A link to a link, and one named relatively, are followed the same way.
    (tmp_path / "session" / "again").symlink_to(Path("bin") / "avrsim")
    for named in (session_bin / "avrsim", tmp_path / "session" / "again"):
        done = _version(named)
        assert done.returncode == 0, done.stderr
        assert done.stdout.startswith("avrsim 0.3.0 avr8js 0.21.1 node ")


def test_the_same_environment_at_another_root_is_the_same_environment(tmp_path: Path) -> None:
    _environment(tmp_path / "first")
    (tmp_path / "first").rename(tmp_path / "second")
    done = _version(tmp_path / "second" / "avrsim" / "bin" / "avrsim")
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("avrsim 0.3.0 ")


def test_no_node_on_the_search_path_is_taken_in_place_of_the_environment_s(tmp_path: Path) -> None:
    launcher = _environment(tmp_path / "env")
    impostor = tmp_path / "impostor"
    impostor.mkdir()
    (impostor / "node").write_text("#!/bin/sh\necho impostor\n", encoding="utf-8")
    (impostor / "node").chmod(0o755)
    done = _version(launcher, {**EMPTY, "PATH": f"{impostor}:/usr/bin:/bin"})
    assert done.returncode == 0, done.stderr
    assert "impostor" not in done.stdout


def test_node_s_start_up_variables_load_nothing_into_the_rig(tmp_path: Path) -> None:
    launcher = _environment(tmp_path / "env")
    marker = tmp_path / "loaded"
    preload = tmp_path / "preload.cjs"
    preload.write_text(f"require('fs').writeFileSync({str(marker)!r}, 'x');\n", encoding="utf-8")
    env = {**EMPTY, "NODE_OPTIONS": f"--require {preload}", "NODE_PATH": str(tmp_path)}
    done = _version(launcher, env)
    assert done.returncode == 0, done.stderr
    assert not marker.exists()
    # The control: the same preload does load into the Node itself.
    subprocess.run(
        [node(), "-e", "0"], env={**env, "PATH": os.environ["PATH"]}, check=True, timeout=60
    )
    assert marker.exists()


def test_a_launcher_whose_environment_has_no_node_fails(tmp_path: Path) -> None:
    launcher = _environment(tmp_path / "env")
    (tmp_path / "env" / "node" / "bin" / "node").unlink()
    done = _version(launcher)
    assert done.returncode != 0


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        ([], "no command"),
        (["simulate"], "unknown command"),
        (["run", "--elf", "x.elf"], "--scenario is required"),
        (["run", "--elf", "x.elf", "--elf", "y.elf"], "--elf is given twice"),
        (["run", "--elf"], "--elf needs a value"),
        (["run", "--elf", "--scenario", "s.json"], "--elf needs a value"),
        (["check", "--scenario", "s.json", "--fast", "1"], "unknown argument"),
        (["--version", "--extra"], "unknown command"),
    ],
)
def test_wrong_arguments_are_refused_with_the_usage(
    tmp_path: Path, argv: list[str], says: str
) -> None:
    launcher = _environment(tmp_path / "env")
    done = subprocess.run(
        [str(launcher), *argv], cwd=tmp_path, env=EMPTY, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 2
    assert says in done.stderr
    assert "usage: avrsim --version" in done.stderr


def test_a_scenario_is_checked_without_running_anything(tmp_path: Path) -> None:
    launcher = _environment(tmp_path / "env")
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text('{"avrsim_scenario": 1, "duration_s": 1}', encoding="utf-8")
    bad.write_text(
        '{"avrsim_scenario": 1, "duration_s": 1, "stalls": [{"start_s": 0}]}', encoding="utf-8"
    )

    def run(path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(launcher), "check", "--scenario", str(path)],
            cwd=tmp_path,
            env=EMPTY,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    assert run(good).returncode == 0
    refused = run(bad)
    assert refused.returncode == 2
    assert "the scenario is refused at stalls[0].end_s" in refused.stderr


def test_a_run_whose_input_is_refused_writes_nothing(tmp_path: Path) -> None:
    launcher = _environment(tmp_path / "env")
    (tmp_path / "s.json").write_text('{"avrsim_scenario": 1, "duration_s": 0}', encoding="utf-8")
    (tmp_path / "firmware.elf").write_bytes(b"\x7fELF")
    done = subprocess.run(
        [str(launcher), "run", "--elf", "firmware.elf", "--scenario", "s.json"]
        + ["--out", "trace.jsonl"],
        cwd=tmp_path, env=EMPTY, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert done.returncode == 2
    assert "refused at duration_s" in done.stderr
    assert not (tmp_path / "trace.jsonl").exists()
    assert not (tmp_path / "trace.summary.json").exists()


@pytest.mark.parametrize("kind", ["link", "directory", "missing"])
def test_an_input_is_read_only_as_a_plain_file(tmp_path: Path, kind: str) -> None:
    launcher = _environment(tmp_path / "env")
    (tmp_path / "real.json").write_text('{"avrsim_scenario": 1, "duration_s": 1}', encoding="utf-8")
    named = tmp_path / "s.json"
    if kind == "link":
        named.symlink_to(tmp_path / "real.json")
    elif kind == "directory":
        named.mkdir()
    done = subprocess.run(
        [str(launcher), "check", "--scenario", str(named)],
        cwd=tmp_path,
        env=EMPTY,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 2
    assert "s.json" in done.stderr
