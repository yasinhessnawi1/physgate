"""No session writes a shell startup file in its home, and none starts on a home holding one.

Claude Code starts shells of its own outside the sandbox it runs a session's commands in, and
zsh reads its startup files in each: a file the session wrote into its own home, which its
commands write, ran with none of the sandbox's bounds. Held here, rule by rule:

- every startup file's name in the home is a protected root of a role and of the raw agent,
  refused to the file tools and to a shell command that names it, write-denied by the OS
  layer, and put back by the sentinel;
- the install gives every session under test a ``ZDOTDIR``: an empty directory among the
  session's own files, outside its home, so zsh looks there; and it never sets ``BASH_ENV``
  or ``ENV``;
- the install holds the place of the one file zsh is told to read from the home by name
  (``.zshrc``, which the snapshot step sources whatever ``ZDOTDIR`` says) with an empty
  directory, where a file tool cannot write a file;
- the install refuses a home that already holds a startup file, and a ``ZDOTDIR`` that holds
  anything, before it writes anything.

The names are written out here by hand, so a name dropped from the code is seen.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import event

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, build_config, current_installation, install
from physgate.oslayer.policy import sandbox_policy
from physgate.oslayer.session_temp import make_session_temp

ZSH = (".zshenv", ".zprofile", ".zshrc", ".zlogin", ".zlogout")
BASH = (".bashrc", ".bash_profile", ".bash_login", ".profile", ".bash_logout", ".inputrc")
NAMES = (*ZSH, *BASH)
SHELL_PROFILES = ("role", "baseline")
UNDER_TEST = ("role", "baseline", "reviewer")


def _request(base: Path, profile: str, **fields: Any) -> InstallRequest:  # noqa: ANN401
    wt = base / "run" / "wt"
    wt.mkdir(parents=True, exist_ok=True)
    reviewer = profile == "reviewer"
    given: dict[str, Any] = {
        "profile": profile,
        "role": "control" if profile == "role" else None,
        "worktree": str(wt),
        "own_branch": None,
        "store_root": str(base / "run" / "store"),
        "state_dir": str(base / "outside" / "state"),
        "target_dir": str(base / "outside" / "session"),
        "claude_config_dir": str(base / "outside" / "config"),
        "user_home": str(base / "outside" / "home"),
        "token_ceiling": 40960,
        "read_roots": (str(base / "run"),) if reviewer else (),
        "sessions_root": None if reviewer else str(base / "outside" / "sessions"),
    }
    given.update(fields)
    return InstallRequest(**given)


def _config(base: Path, profile: str) -> SessionConfig:
    (base / "outside" / "home").mkdir(parents=True, exist_ok=True)
    return build_config(_request(base, profile), current_installation())


def _refused(hook: Any, config: SessionConfig, **call: Any) -> bool:  # noqa: ANN401
    hook_input = HookInput.model_validate(event(cwd=config.worktree, **call))
    return not hook.pre_tool_use(hook_input, config).allow


@pytest.mark.parametrize("profile", SHELL_PROFILES)
@pytest.mark.parametrize("name", NAMES)
def test_a_startup_file_in_the_home_is_refused_on_every_route(
    tmp_path: Path, profile: str, name: str
) -> None:
    base = tmp_path.resolve()
    config = _config(base, profile)
    home = base / "outside" / "home"
    target = str(home / name)
    write = {"tool_name": "Write", "tool_input": {"file_path": target, "content": "x"}}
    edit = {
        "tool_name": "Edit",
        "tool_input": {"file_path": target, "old_string": "a", "new_string": "b"},
    }
    filesystem = sandbox_policy(config, home=str(home), temp_dir="/tmp/pg-1").settings["sandbox"][
        "filesystem"
    ]
    watched = [r.watch for r in config.protected_roots if r.path == target]
    routes = {
        "the Write tool": _refused(paths, config, **write),
        "the Edit tool": _refused(paths, config, **edit),
        "a redirect onto it": _refused(
            shell_paths, config, tool_name="Bash", tool_input={"command": f"echo x > {target}"}
        ),
        "a command that names it": _refused(
            shell_paths, config, tool_name="Bash", tool_input={"command": f"cp /dev/null {target}"}
        ),
        "a move into its place": _refused(
            shell_paths,
            config,
            tool_name="Bash",
            tool_input={"command": f"mv {config.worktree}/x {target}"},
        ),
        "the OS layer's write denial": target in filesystem["denyWrite"],
        "the sentinel puts it back": watched == ["revert"],
    }
    assert [route for route, held in routes.items() if not held] == []


@pytest.mark.parametrize("profile", SHELL_PROFILES)
def test_the_home_itself_stays_writable_and_an_ordinary_file_there_is_no_root(
    tmp_path: Path, profile: str
) -> None:
    base = tmp_path.resolve()
    config = _config(base, profile)
    home = base / "outside" / "home"
    ordinary = str(home / "notes.txt")
    assert not _refused(
        shell_paths, config, tool_name="Bash", tool_input={"command": f"echo x > {ordinary}"}
    )
    filesystem = sandbox_policy(config, home=str(home), temp_dir="/tmp/pg-1").settings["sandbox"][
        "filesystem"
    ]
    assert str(home) in filesystem["allowWrite"]
    assert str(home) not in filesystem["denyWrite"]
    startup = [p for p in filesystem["denyWrite"] if Path(p).parent == home]
    assert {Path(p).name for p in startup} >= set(NAMES)


@pytest.fixture
def own_temp() -> Any:  # noqa: ANN401 - a generator fixture
    temp = make_session_temp()
    yield str(temp)
    os.rmdir(temp)


@pytest.mark.parametrize("profile", UNDER_TEST)
def test_the_install_points_zsh_at_an_empty_directory_no_session_writes(
    tmp_path: Path, profile: str, own_temp: str
) -> None:
    base = tmp_path.resolve()
    request = _request(base, profile, temp_dir=own_temp)
    done = install(request, REGISTRY)
    where = done.spawn_env.get("ZDOTDIR")
    assert where is not None, "the session's environment sets no ZDOTDIR"
    assert os.path.isdir(where) and not os.path.islink(where)
    assert os.listdir(where) == []
    assert Path(where).parent == Path(request.target_dir)
    assert not Path(where).is_relative_to(Path(request.user_home))
    assert not {"BASH_ENV", "ENV"} & set(done.spawn_env)
    # Among the session's own files, which no tool writes and the sentinel puts back.
    config = build_config(request, current_installation())
    holding = [r for r in config.protected_roots if Path(where).is_relative_to(Path(r.path))]
    assert [r.watch for r in holding] == ["revert"]


@pytest.mark.parametrize("profile", UNDER_TEST)
def test_the_install_holds_the_place_of_the_file_zsh_reads_by_name_with_a_directory(
    tmp_path: Path, profile: str, own_temp: str
) -> None:
    base = tmp_path.resolve()
    request = _request(base, profile, temp_dir=own_temp)
    install(request, REGISTRY)
    held = Path(request.user_home) / ".zshrc"
    assert held.is_dir() and not held.is_symlink(), "nothing holds the place of ~/.zshrc"
    assert list(held.iterdir()) == []
    assert [n for n in NAMES if os.path.lexists(Path(request.user_home) / n)] == [".zshrc"]
    # A second install on the same home (a reviewer's repair) finds its own directory.
    again = install(request, REGISTRY)
    assert again.spawn_env["ZDOTDIR"] == str(Path(request.target_dir) / "zdotdir")


@pytest.mark.parametrize("profile", SHELL_PROFILES)
def test_the_held_directory_is_write_denied_as_it_stands(
    tmp_path: Path, profile: str, own_temp: str
) -> None:
    base = tmp_path.resolve()
    request = _request(base, profile, temp_dir=own_temp)
    install(request, REGISTRY)
    home = Path(request.user_home)
    config = build_config(request, current_installation())
    filesystem = sandbox_policy(config, home=str(home), temp_dir="/tmp/pg-1").settings["sandbox"][
        "filesystem"
    ]
    assert (home / ".zshrc").is_dir()
    assert str(home / ".zshrc") in filesystem["denyWrite"]
    inside = str(home / ".zshrc" / "made-here")
    assert _refused(
        shell_paths, config, tool_name="Bash", tool_input={"command": f"echo x > {inside}"}
    )
    assert _refused(
        paths, config, tool_name="Write", tool_input={"file_path": inside, "content": "x"}
    )


@pytest.mark.parametrize("profile", UNDER_TEST)
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("kind", ["file", "dangling link", "directory that holds something"])
def test_a_home_that_already_holds_a_startup_file_is_refused_and_nothing_is_written(
    tmp_path: Path, profile: str, name: str, kind: str, own_temp: str
) -> None:
    base = tmp_path.resolve()
    request = _request(base, profile, temp_dir=own_temp)
    home = Path(request.user_home)
    home.mkdir(parents=True)
    if kind == "file":
        (home / name).write_text("")
    elif kind == "dangling link":
        (home / name).symlink_to(base / "nowhere")
    else:
        (home / name).mkdir()
        (home / name / "inside").write_text("")
    with pytest.raises(ValueError, match="already holds a shell startup file") as refused:
        install(request, REGISTRY)
    assert name in str(refused.value)
    assert not Path(request.target_dir).exists()


@pytest.mark.parametrize("held", ["a file", "a link in its place"])
def test_a_zdotdir_that_is_not_an_empty_directory_of_its_own_is_refused(
    tmp_path: Path, held: str, own_temp: str
) -> None:
    base = tmp_path.resolve()
    request = _request(base, "role", temp_dir=own_temp)
    target = Path(request.target_dir)
    target.mkdir(parents=True)
    if held == "a file":
        (target / "zdotdir").mkdir()
        (target / "zdotdir" / ".zshenv").write_text("echo planted\n")
    else:
        elsewhere = base / "elsewhere"
        elsewhere.mkdir()
        (target / "zdotdir").symlink_to(elsewhere)
    with pytest.raises(ValueError, match="ZDOTDIR"):
        install(request, REGISTRY)
    assert not (target / "settings.json").exists()


def test_the_orchestrator_s_own_session_keeps_its_home_as_it_is(tmp_path: Path) -> None:
    # Not a session under test: it runs in the operator's own home, whose startup files are
    # the operator's, and nothing of it is sandboxed.
    base = tmp_path.resolve()
    request = _request(base, "orchestrator")
    home = Path(request.user_home)
    home.mkdir(parents=True)
    (home / ".zshrc").write_text("# the operator's own\n")
    done = install(request, REGISTRY)
    assert "ZDOTDIR" not in done.spawn_env
    assert (home / ".zshrc").read_text() == "# the operator's own\n"
    config = build_config(request, current_installation())
    assert str(home / ".zshrc") not in {r.path for r in config.protected_roots}
