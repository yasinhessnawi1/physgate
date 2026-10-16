"""What a command's own text decides is resolved, or refused; it is never skipped.

A refuse-only root has no second layer, so a word the shell layer skips is a word that
reaches it. Each form here is decided by the command alone, and each was skipped before:

- a ``$`` that is quoted or escaped is a literal character, and a word whose written
  prefix is already inside a root reaches it, whatever the rest becomes;
- a variable could hold too many values to check: refused, never skipped;
- ``eval``'s command line runs where it stands, so a ``cd`` or an assignment in it holds
  for what follows; ``chdir`` is ``cd``; ``$"…"`` is its double-quoted string;
- ``~N`` and ``~+N`` are directories this call has been in; a ``~name`` that names no
  user is read by zsh as a directory known only at run time, and is refused;
- a shell's script read from ``/dev/stdin``, by name or through ``source``, is parsed.

What stays out of reach is pinned at the end. Inert markers into a temporary root only.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hook_helpers import bash

from physgate.hooks import shell
from physgate.hooks import shell_paths as sp
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation

ROOT = ".physgate/series"
M = "echo marker"


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionConfig:
    worktree = Path(os.path.realpath(tmp_path)) / "wt"
    (worktree / ROOT).mkdir(parents=True)
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
    "command",
    [
        f"{M} > '.physgate/series/$x'",
        f"mkdir -p 'q$x'; {M} > 'q$x/../.physgate/series/f'",
        f'{M} > ".physgate/series/\\$x"',
        "touch '.physgate/series/$x'",
        f"{M} > .physgate/series/$$",
        f"{M} > .physgate/series/${{x:-f}}",
    ],
    ids=["single-quoted", "through-dot-dot", "escaped", "touch", "pid", "default"],
)
def test_a_quoted_dollar_or_a_written_prefix_inside_a_root_is_judged(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"for x in {{1..63}} .physgate; do {M} > $x/series/f; done",
        f"x=.physgate; for y in {{1..70}}; do :; done; {M} > $x/series/$y",
        f"for x in .phys{{gate,x}}; do {M} > $x/series/f; done",
    ],
    ids=["sixty-five-values", "seventy-one-values", "braces-in-a-for-list"],
)
def test_every_value_a_loop_variable_could_hold_is_checked(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"for a in {{1..40}}; do for b in {{1..40}}; do {M} > $a$b; done; done",
        f"for x in {{1..2000}}; do {M} > $x; done",
        f"for a in {{1..40}}; do :; done; for b in {{1..40}}; do :; done; x=$a$b; {M} > $x",
    ],
    ids=["product", "unbounded-list", "assigned-from-too-many"],
)
def test_a_word_that_could_become_too_many_words_is_refused(
    config: SessionConfig, command: str
) -> None:
    # Refused, never skipped: by the variable bound, or (the list itself) the brace bound.
    told = _decide(config, command)
    bounds = (sp.VARIABLE_UNBOUNDED.split("{word}")[0], sp.BRACE_UNBOUNDED.split("{word}")[0])
    assert any(b in told for b in bounds), told


def test_pwd_after_a_cd_is_every_directory_the_command_could_be_in(
    config: SessionConfig,
) -> None:
    command = f"cd modules; p=$PWD/..; {M} > $p/.physgate/series/f"
    assert _decide(config, command) != "allow"
    # No '..' to cancel, and the value alone names no root: only $PWD's every directory,
    # recorded when p is assigned, reaches it.
    assert _decide(config, f"cd .physgate; p=$PWD; {M} > $p/series/f") != "allow"


def test_eval_runs_where_it_stands() -> None:
    commands = shell.parse("eval cd .physgate; echo marker > series/f")
    assert [c.argv for c in commands] == [
        ("eval", "cd", ".physgate"),
        ("cd", ".physgate"),
        ("echo", "marker"),
    ]


@pytest.mark.parametrize(
    "command",
    [
        f"eval cd .physgate; {M} > series/f",
        f"eval a=.physgate; {M} > $a/series/f",
        f"chdir .physgate; {M} > series/f",
        f'{M} > $".physgate/series/f"',
        'touch $".physgate/series/f"',
        f"pushd .physgate; pushd /tmp; {M} > ~1/series/f",
        f"pushd .physgate; pushd /tmp; {M} > ~+1/series/f",
        f"bash /dev/stdin <<'X'\ncd .physgate\n{M} > series/f\nX\n",
        f"source /dev/stdin <<< 'cd .physgate'; {M} > series/f",
        f". /dev/stdin <<< 'cd .physgate'; {M} > series/f",
    ],
    ids=[
        "eval-cd",
        "eval-assignment",
        "chdir",
        "locale-string",
        "locale-string-touch",
        "stack-entry",
        "stack-entry-plus",
        "script-from-stdin",
        "source-stdin",
        "dot-stdin",
    ],
)
def test_a_literal_form_the_shell_resolves_is_resolved(config: SessionConfig, command: str) -> None:
    assert _decide(config, command) != "allow"


def test_a_tilde_name_whose_directory_only_running_decides_is_refused(
    config: SessionConfig,
) -> None:
    for command in (
        f"p=$(pwd)/.physgate; {M} > ~p/series/f",
        f"{M} > ~no_such_name_here/series/f",
    ):
        told = _decide(config, command)
        assert told.startswith(sp.TILDE_UNKNOWN.split("{word}")[0]), told


@pytest.mark.parametrize(
    "command",
    [
        f"PWD=@W/.physgate; {M} > $PWD/series/f",
        f"p=@W/.physgate; {M} > ~p/series/f",
        f"root=@W/.physgate; {M} > ~root/series/f",
        f"TMPDIR=@W/.physgate; {M} > ~TMPDIR/series/f",
        f"HOME=@W; CDPATH=/tmp:~/.physgate; cd series; {M} > f",
        f"x=.phys; x+=gate; {M} > $x/series/f",
        f"export x=.phys; export x+=gate; {M} > $x/series/f",
        f"cat .physgate/series/earlier.json > /dev/null; {M} > $_",
        f"x=.physgate; {M} > ${{x%/}}/series/f",
        f"x=.physgate; {M} > ${{x#}}/series/f",
        f"x=a.physgate; {M} > ${{x#a}}/series/f",
        f"x=.physgate/series/q; {M} > ${{x%/*}}/f",
        f"{M} > ${{x:-.physgate}}/series/f",
        f"x=y; {M} > ${{x:+.physgate}}/series/f",
        f"{M} > ${{x:=.physgate}}/series/f",
    ],
    ids=[
        "pwd-assigned",
        "zsh-tilde-parameter",
        "zsh-tilde-parameter-over-user",
        "zsh-tilde-inherited",
        "tilde-after-colon",
        "append",
        "export-append",
        "last-argument",
        "trim-suffix",
        "trim-nothing",
        "trim-prefix",
        "trim-pattern",
        "default",
        "alternative",
        "assign-default",
    ],
)
def test_a_parameter_form_the_command_decides_is_resolved(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command.replace("@W", config.worktree)) != "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"x=.physgateZ; {M} > ${{x/Z/}}/series/f",
        f"x=.physgateZZ; {M} > ${{x:0:9}}/series/f",
        f"x=.PHYSGATE; {M} > ${{x,,}}/series/f",
        f"y=.physgate; x=y; {M} > ${{!x}}/series/f",
    ],
    ids=["replace", "substring", "case", "indirect"],
)
def test_a_parameter_form_not_evaluated_is_refused(config: SessionConfig, command: str) -> None:
    told = _decide(config, command)
    assert told.startswith(sp.PARAMETER_FORM.split("{word}")[0]), told


@pytest.mark.parametrize(
    "command",
    [
        "tmp=$(mktemp); rm $tmp",
        f"{M} 'it costs $5' > modules/control/notes.txt",
        'printf "%s\\n" "$HOME" > modules/control/out.txt',
        "eval echo hi",
        "for f in a b c; do touch modules/control/$f.py; done",
        "for i in {1..200}; do echo $i; done > modules/control/n.txt",
        'cd modules/control && for f in *.py; do mv "$f" "${f%.py}.txt"; done',
        "x=${TMPDIR:-/tmp}/build; mkdir -p $x",
        "echo ${#HOME} ${HOME:-/tmp}",
        "mkdir -p modules/control/out && cd $_ && touch f",
        "pushd modules >/dev/null && ls ~1 && popd",
        f"cd ~ && {M} > /dev/null",
    ],
)
def test_ordinary_commands_stay_allowed(config: SessionConfig, command: str) -> None:
    assert _decide(config, command) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"cat <<'X' | bash\ncd .physgate\n{M} > series/f\nX\n",
        f"echo .physgate | xargs -I{{}} sh -c 'cd {{}} && {M} > series/f'",
        f'IFS=/; set -- .physgate series f; {M} > "$*"',
        f"a=(.physgate series); {M} > ${{a[0]}}/series/f",
        f'cd "$(pwd)/.physgate"; {M} > series/f',
        f"set -- .physgate; {M} > $1/series/f",
        f"f() {{ {M} > $1/series/f; }}; f .physgate",
    ],
    ids=[
        "piped-into-a-shell",
        "xargs",
        "positional",
        "array",
        "cd-substitution",
        "set-positional",
        "function-argument",
    ],
)
def test_the_recorded_residual_is_not_seen(config: SessionConfig, command: str) -> None:
    # Allowed on purpose: each reaches the root only through a value or a script the
    # shell builds at run time. Pinned so that closing one is noticed; the OS layer is
    # the proposed closing layer for all of them.
    assert _decide(config, command) == "allow"


def test_the_known_values_of_a_variable_also_set_at_run_time_are_still_checked(
    config: SessionConfig,
) -> None:
    assert _decide(config, f"a=.physgate; read a <<< x; {M} > $a/series/f") != "allow"


def test_a_reviewer_s_word_as_written_is_only_a_mention(tmp_path: Path) -> None:
    worktree = Path(os.path.realpath(tmp_path)) / "wt"
    worktree.mkdir()
    reviewer = build_config(
        InstallRequest(
            profile="reviewer",
            role=None,
            worktree=str(worktree),
            own_branch=None,
            store_root=None,
            state_dir=str(tmp_path / "state"),
            target_dir=str(tmp_path / "target"),
            claude_config_dir=str(tmp_path / "config"),
            user_home=str(tmp_path / "home"),
            token_ceiling=40960,
            read_roots=(str(worktree),),
        ),
        current_installation(),
    )
    # $x is a real, unknown variable: the word as written, /usr/share/$x, lies outside the
    # reviewer's allowance, but for a reader it counts only where it names what may not be
    # named at all. (A quoted '$x' is no variable: that word is read as it stands.)
    assert _decide(reviewer, "cat /usr/share/$x") == "allow"
    assert _decide(reviewer, "cat '/usr/share/$x'") != "allow"
