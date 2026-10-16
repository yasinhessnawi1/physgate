"""A command's name is one key for every rule, and a state the layer cannot follow is not guessed.

Every rule that gives a command name a meaning (a reader, a shell that runs a string, a
``cd``) looks the name up by one normalisation, so no spelling escapes it: a path keeps
its last part and case is folded (``/bin/BASH`` runs bash on a case-insensitive volume).
A reader is trusted by its name only while the name means the usual program: not as
``./cat``, not after the call changes ``PATH``.

Where the call could change what a later word means in a way the layer does not follow
(an alias, a function named like a command a rule trusts, a hashed path, a builtin
turned off, a shell option that changes expansion), the construct is refused: each is
rare in an agent's commands, and a guess would let a write through. A ``trap`` action is
parsed as the commands it runs. After ``source <file>``, which can change any variable
unseen, no value is complete: a ``cd`` through ``HOME`` or ``OLDPWD`` is refused.

Inert markers into a temporary refuse-only root only.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from hook_helpers import bash

from physgate.hooks import git_ops, shell
from physgate.hooks import shell_paths as sp
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation

ROOT = ".physgate/series"
M = "echo marker"
READ = ".physgate/series/earlier.json"


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionConfig:
    worktree = Path(os.path.realpath(tmp_path)) / "wt"
    (worktree / ROOT).mkdir(parents=True)
    (worktree / ROOT / "earlier.json").write_text("{}\n")
    (worktree / "modules" / "control").mkdir(parents=True)
    monkeypatch.delenv("OLDPWD", raising=False)
    monkeypatch.delenv("CDPATH", raising=False)
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(worktree),
        own_branch="b",
        store_root=None,
        state_dir=str(tmp_path / "state"),
        target_dir=str(tmp_path / "target"),
        claude_config_dir=str(tmp_path / "config"),
        user_home=str(tmp_path / "home"),
        token_ceiling=40960,
        extra_protected_refuse_only=(str(worktree / ROOT),),
    )
    return build_config(request, current_installation())


def _decide(config: SessionConfig, command: str) -> str:
    hook_input = HookInput.model_validate(bash(command, cwd=config.worktree))
    decision = sp.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


@pytest.mark.parametrize(
    "word",
    ["bash", "/bin/bash", "BASH", "/bin/BASH", "Bash", "\\bash", "ba''sh", '"bash"'],
)
@pytest.mark.parametrize("prefix", ["", "command ", "env ", "exec "])
def test_a_shell_s_string_is_parsed_however_the_shell_is_spelt(
    config: SessionConfig, word: str, prefix: str
) -> None:
    command = f"{prefix}{word} -c 'cd .physgate && {M} > series/f'"
    assert _decide(config, command) != "allow", command


def test_one_key_for_every_registry() -> None:
    for spelling in ("cat", "/bin/cat", "CAT", "/usr/bin/Cat"):
        assert shell.command_key(spelling) == "cat"
    for spelling in ("\\cat", "c''at", '"cat"'):
        (cmd,) = shell.parse(f"{spelling} x")
        assert shell.command_key(cmd.argv[0]) == "cat"


@pytest.mark.parametrize(
    "command",
    [
        f"./cat {READ}",
        f"bin/cat {READ}",
        f"PATH=.:/opt/tools/bin; cat {READ}",
        f"PATH=. cat {READ}",
        f"env PATH=. cat {READ}",
        f"export PATH=.:/opt/tools/bin; cat {READ}",
    ],
    ids=["dot-slash", "relative", "path-reassigned", "path-prefix", "env-path", "exported"],
)
def test_a_reader_whose_name_may_run_another_program_is_judged_as_a_writer(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


def test_the_reader_by_its_own_path_is_still_a_reader(config: SessionConfig) -> None:
    found = shutil.which("cat")
    assert found is not None
    assert _decide(config, f"{found} {READ}") == "allow"
    assert _decide(config, f"cat {READ}") == "allow"


@pytest.mark.parametrize(
    "setup",
    [
        'cat() { tee "$@"; }',
        'cat () { tee "$@"; }',
        'function cat { tee "$@"; }',
        "build() { make; }",
        "alias cat=tee",
        "alias ll='ls -l'",
        "hash -p /tmp/x cat",
        "enable -n cd",
        "command -p ls",
        "PATH=.:/opt/tools/bin",
        "export PATH=.:/opt/tools/bin",
    ],
)
def test_once_a_name_s_meaning_is_unknown_a_reader_is_judged_as_a_possible_writer(
    config: SessionConfig, setup: str
) -> None:
    # One rule for every way a call can change what a command name runs: from then on no
    # name is trusted as a reader. A literal path into a protected root refuses; any other
    # path is the residual, allowed.
    assert _decide(config, f"{setup}; cat {READ}") != "allow"
    assert _decide(config, f"{setup}; cat modules/control/notes.txt") == "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"sort -o {ROOT}/f modules/control/notes.txt",
        f"find modules -fprint {ROOT}/f",
        f"find {ROOT} -delete",
        f"sed -i s/a/b/ {READ}",
        f"awk '{{print > \"{ROOT}/f\"}}' modules/control/notes.txt",
        f"less -o {ROOT}/f modules/control/notes.txt",
        f"tar -xf a.tar -C {ROOT}",
        f"curl -o {ROOT}/f file:///etc/hosts",
        "git -C .physgate diff --output=series/f",
        "git -C .physgate log --output series/f",
        f"GIT_PAGER='tee {ROOT}/f' git log",
        f"LESSOPEN='|tee {ROOT}/f %s' less modules/control/notes.txt",
        f"env PAGER='tee {ROOT}/f' git log",
        "env -C .physgate sh -c 'echo marker > series/f'",
        "make -C .physgate -f /dev/null series/f",
    ],
)
def test_a_reader_with_a_write_option_or_its_own_environment_is_a_writer(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"shopt -s nocaseglob; {M} > .PHYS*/series/f",
        f"shopt -s dotglob; {M} > */series/f",
        "setopt globsubst",
        "setopt GLOB_DOTS",
        "set -o posix",
        "set -P",
    ],
)
def test_a_shell_option_that_changes_how_words_are_read_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert sp.OPTION_REFUSED.split("{what}")[0] in _decide(config, command)


@pytest.mark.parametrize(
    "command",
    [
        f"set -euo pipefail; {M} > modules/control/out.txt",
        "set -x && ls",
        "set +e; true",
        "build() { make -C modules/control; }; build",
        "shopt nullglob",
        f"source .venv/bin/activate && cd modules && {M} > control/out.txt",
    ],
)
def test_ordinary_settings_and_functions_are_allowed(config: SessionConfig, command: str) -> None:
    assert _decide(config, command) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"trap 'cd .physgate' DEBUG; {M} > series/f",
        f"f() {{ cd .physgate; }}; f; {M} > series/f",
    ],
    ids=["trap-action", "function-body"],
)
def test_a_cd_the_shell_runs_later_is_followed(config: SessionConfig, command: str) -> None:
    assert _decide(config, command) != "allow"


@pytest.mark.parametrize(
    ("command", "told"),
    [
        (f"source ./env.sh; cd -; {M} > f", "$OLDPWD"),
        (f". ./env.sh; cd; {M} > f", "$HOME"),
    ],
)
def test_after_a_sourced_file_a_cd_through_a_variable_is_not_guessed(
    config: SessionConfig, command: str, told: str
) -> None:
    assert _decide(config, command) == sp.CD_UNKNOWN.format(what=told)


@pytest.mark.parametrize("word", ["git", "/usr/bin/git", "GIT", "Git", "\\git", "g''it", "=git"])
def test_a_role_runs_no_git_however_git_is_spelt(config: SessionConfig, word: str) -> None:
    hook_input = HookInput.model_validate(bash(f"{word} status", cwd=config.worktree))
    assert not git_ops.pre_tool_use(hook_input, config).allow
