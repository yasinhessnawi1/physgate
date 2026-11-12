"""No session is spawned with an environment a shell startup file could reach it through.

Every session of the harness (a role's, a reviewer's, the raw agent's) is spawned held, by one
function. It refuses, before any process exists, an environment that names a file a shell
reads as it starts (``BASH_ENV``, ``ENV``), one without a ``ZDOTDIR`` that is an empty
directory outside the session's home, and a home that holds a startup file or lacks the empty
directory that holds the place of ``.zshrc``: the binary starts shells outside the sandbox, and
each would run what it found.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

from physgate.evaluation.per_role.arms import raw
from physgate.orchestrator import dispatch
from physgate.orchestrator.dispatch import spawn_held
from physgate.orchestrator.exceptions import InvocationError
from physgate.reviewers import claude as reviewers

NAMES = (
    ".zshenv",
    ".zprofile",
    ".zshrc",
    ".zlogin",
    ".zlogout",
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".profile",
    ".bash_logout",
    ".inputrc",
)


def _places(tmp_path: Path) -> tuple[Path, Path, Path]:
    home, zdotdir, marker = tmp_path / "home", tmp_path / "session" / "zdotdir", tmp_path / "ran"
    (home / ".zshrc").mkdir(parents=True)
    zdotdir.mkdir(parents=True)
    return home, zdotdir, marker


def _spawn(tmp_path: Path, env: dict[str, str], marker: Path) -> int:
    with (tmp_path / "out").open("wb") as out, (tmp_path / "err").open("wb") as err:
        process, _ = spawn_held(
            ["/bin/sh", "-c", f"echo ran > '{marker}'"],
            cwd=tmp_path,
            env=env,
            out=out,
            err=err,
            session_id="s1",
            on_spawn=None,
            while_held=lambda _pid, _started: None,
        )
        return process.wait(timeout=30)


def _env(home: Path, zdotdir: Path) -> dict[str, str]:
    return {"HOME": str(home), "PATH": "/usr/bin:/bin", "ZDOTDIR": str(zdotdir)}


def test_a_session_whose_environment_holds_nothing_of_the_kind_is_spawned(tmp_path: Path) -> None:
    home, zdotdir, marker = _places(tmp_path)
    assert _spawn(tmp_path, _env(home, zdotdir), marker) == 0
    assert marker.read_text() == "ran\n"


def _refused(tmp_path: Path, env: dict[str, str], marker: Path, why: str) -> None:
    with pytest.raises(InvocationError, match=why):
        _spawn(tmp_path, env, marker)
    assert not marker.exists(), "the refused session ran"


@pytest.mark.parametrize("name", ["BASH_ENV", "ENV"])
def test_an_environment_that_names_a_file_a_shell_reads_is_refused(
    tmp_path: Path, name: str
) -> None:
    home, zdotdir, marker = _places(tmp_path)
    _refused(tmp_path, {**_env(home, zdotdir), name: str(tmp_path / "rc")}, marker, name)


def test_an_environment_without_a_zdotdir_is_refused(tmp_path: Path) -> None:
    home, zdotdir, marker = _places(tmp_path)
    env = _env(home, zdotdir)
    del env["ZDOTDIR"]
    _refused(tmp_path, env, marker, "ZDOTDIR")


def test_an_environment_without_a_home_is_refused(tmp_path: Path) -> None:
    home, zdotdir, marker = _places(tmp_path)
    env = _env(home, zdotdir)
    del env["HOME"]
    _refused(tmp_path, env, marker, "home")


@pytest.mark.parametrize(
    "case",
    ["holds a file", "is a link", "is missing", "is the home", "lies in the home", "relative"],
)
def test_a_zdotdir_a_session_could_have_filled_is_refused(tmp_path: Path, case: str) -> None:
    home, zdotdir, marker = _places(tmp_path)
    env = _env(home, zdotdir)
    if case == "holds a file":
        (zdotdir / ".zshenv").write_text("echo planted\n")
    elif case == "is a link":
        zdotdir.rmdir()
        (tmp_path / "elsewhere").mkdir()
        zdotdir.symlink_to(tmp_path / "elsewhere")
    elif case == "is missing":
        zdotdir.rmdir()
    elif case == "is the home":
        env["ZDOTDIR"] = str(home)
    elif case == "lies in the home":
        (home / "z").mkdir()
        env["ZDOTDIR"] = str(home / "z")
    else:
        env["ZDOTDIR"] = "session/zdotdir"
    _refused(tmp_path, env, marker, "ZDOTDIR")


@pytest.mark.parametrize("name", NAMES)
def test_a_home_that_holds_a_startup_file_at_the_spawn_is_refused(
    tmp_path: Path, name: str
) -> None:
    home, zdotdir, marker = _places(tmp_path)
    if name == ".zshrc":
        (home / name).rmdir()
    (home / name).symlink_to(tmp_path / "nowhere")
    _refused(tmp_path, _env(home, zdotdir), marker, "already holds a shell startup file")
    assert os.path.lexists(home / name), "the refusal changed the home"


@pytest.mark.parametrize("case", ["missing", "holds something", "a file"])
def test_a_home_where_nothing_holds_the_place_of_the_zshrc_is_refused(
    tmp_path: Path, case: str
) -> None:
    home, zdotdir, marker = _places(tmp_path)
    if case == "holds something":
        (home / ".zshrc" / "inside").write_text("")
    else:
        (home / ".zshrc").rmdir()
    if case == "a file":
        (home / ".zshrc").write_text("echo planted\n")
    _refused(tmp_path, _env(home, zdotdir), marker, r"\.zshrc")


def test_every_session_of_the_harness_is_spawned_by_that_one_function() -> None:
    assert "spawn_held(" in inspect.getsource(dispatch.ClaudeDispatcher._run_session)
    assert vars(raw)["spawn_held"] is spawn_held
    assert vars(reviewers)["spawn_held"] is spawn_held
