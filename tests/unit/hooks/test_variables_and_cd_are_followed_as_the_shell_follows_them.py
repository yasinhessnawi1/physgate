r"""A word and a ``cd`` are read the way the shell running them reads them.

The shell layer must not resolve a word one way while the shell resolves it another: a
difference is a path that reaches a protected root unseen. So:

- a variable the call assigns is never read from the hook's own environment: it could hold
  the inherited value or any literal value the call gives it, and every one is checked;
- ``cd`` alone follows ``HOME``, ``cd -`` and ``~-`` follow ``OLDPWD``, ``$PWD`` and ``~+``
  are the directory being judged from, and a relative ``cd`` is also looked up beneath
  every ``CDPATH`` entry, as bash and zsh do;
- where one of those is set to a value known only at run time, or a shell option or named
  directory sends ``cd`` where no word says, that construct alone is refused;
- each shell's reading of ANSI-C quoting and of brace sequences is checked, and the
  constructs shells read too differently (``\c``, a digitless ``\x``, a zero step, a
  ksh command string) are refused.

Every write is an inert marker into a temporary refuse-only root.
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
MARKER = "echo marker"


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionConfig:
    worktree = Path(os.path.realpath(tmp_path)) / "wt"
    (worktree / ROOT).mkdir(parents=True)
    (worktree / "modules" / "control").mkdir(parents=True)
    monkeypatch.delenv("OLDPWD", raising=False)
    monkeypatch.delenv("CDPATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
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
    command = command.replace("@W", config.worktree)
    hook_input = HookInput.model_validate(bash(command, cwd=config.worktree))
    decision = sp.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


@pytest.mark.parametrize(
    "command",
    [
        f"TMPDIR=@W/.physgate; {MARKER} > $TMPDIR/series/step.json",
        f"HOME=@W/.physgate; {MARKER} > ~/series/step.json",
        f"HOME=@W/.physgate; {MARKER} > $HOME/series/step.json",
        f"HOME=@W/.physgate; cd; {MARKER} > series/step.json",
        f"HOME=@W/.physgate cd && {MARKER} > series/step.json",
        "export HOME=@W/.physgate; cd ~/series && touch step.json",
        f"OLDPWD=@W/.physgate; cd -; {MARKER} > series/step.json",
        f"cd .physgate && cd /tmp && {MARKER} > ~-/series/step.json",
        f"cd .physgate && {MARKER} > $PWD/series/step.json",
        f"cd .physgate && {MARKER} > ~+/series/step.json",
        "CDPATH=.physgate cd series && touch step.json",
        "export CDPATH=@W/.physgate; cd series; touch step.json",
        "CDPATH=:@W/.physgate; cd series; touch step.json",
        f"for d in .physgate; do {MARKER} > $d/series/step.json; done",
        f"a=.phys; b=gate; {MARKER} > ${{a}}${{b}}/series/step.json",
        f"declare -x d=.physgate/series; {MARKER} > $d/step.json",
    ],
    ids=[
        "inherited-variable-reassigned",
        "home-tilde",
        "home-variable",
        "bare-cd",
        "prefix-home-cd",
        "exported-home-tilde-cd",
        "oldpwd-cd-dash",
        "tilde-minus",
        "pwd-after-cd",
        "tilde-plus",
        "prefix-cdpath",
        "exported-cdpath",
        "cdpath-with-empty-entry",
        "for-loop-variable",
        "braced-fragments",
        "declare-export",
    ],
)
def test_a_path_through_a_variable_the_call_sets_is_judged(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


def test_an_assignment_that_may_not_run_leaves_the_inherited_value_possible(
    config: SessionConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", os.path.join(config.worktree, ".physgate"))
    assert _decide(config, f"false && HOME=/tmp; {MARKER} > ~/series/step.json") != "allow"
    assert _decide(config, f"false && HOME=/tmp; {MARKER} > $HOME/series/step.json") != "allow"
    assert _decide(config, f"false && HOME=/tmp; {MARKER} > ~/notes.txt") == "allow"


@pytest.mark.parametrize(
    ("command", "told"),
    [
        ("CDPATH=$(printf .physgate) cd series && touch step.json", "$CDPATH"),
        (f"read HOME <<< /tmp; cd; {MARKER} > series/step.json", "$HOME"),
        (f"OLDPWD=$(pwd); cd -; {MARKER} > out.txt", "$OLDPWD"),
        ("cdpath=(@W/.physgate); cd series; touch step.json", "$CDPATH"),
    ],
)
def test_a_cd_through_a_value_known_only_at_run_time_is_refused(
    config: SessionConfig, command: str, told: str
) -> None:
    assert _decide(config, command) == sp.CD_UNKNOWN.format(what=told)


@pytest.mark.parametrize(
    "command",
    [
        "hash -d p=@W/.physgate; cd ~p/series && touch step.json",
        "shopt -s cdable_vars",
        "setopt CDABLE_VARS",
        "set -o cdablevars",
    ],
)
def test_a_setting_that_sends_cd_where_no_word_says_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert sp.CD_OPTION.split("{what}")[0] in _decide(config, command)


@pytest.mark.parametrize(
    "command",
    [
        f"cd - && {MARKER} > modules/control/out.txt",
        "cd && ls",
        "HOME=/tmp/elsewhere python3 modules/control/sim.py",
        "export LC_ALL=C && cd modules && touch control/f.py",
        "for f in a b; do touch modules/control/$f.py; done",
        "x=$(date); echo $x",
        "CDPATH= cd modules && touch control/f.py",
        "d=modules/control; cd $d && touch f.py",
        f"cd modules && {MARKER} > $PWD/out.txt",
        "tmp=$(mktemp); rm $tmp",
    ],
)
def test_ordinary_variables_and_cds_are_allowed(config: SessionConfig, command: str) -> None:
    assert _decide(config, command) == "allow"


# --- each shell's reading ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "readings"),
    [
        ("\\q", {"\\q", "q", "$\\q"}),
        ("\\u0041", {"A", "\\u0041", "$\\u0041"}),
        ("\\x2ephysgate", {".physgate", "$\\x2ephysgate"}),
    ],
)
def test_every_shell_s_reading_of_ansi_c_quoting_is_kept(body: str, readings: set[str]) -> None:
    assert set(shell.ansi_c_readings(body).values()) == readings
    (cmd,) = shell.parse(f"touch $'{body}'")
    assert set(cmd.alternatives.get(1) or ()) | {cmd.argv[1]} == readings


@pytest.mark.parametrize(
    "body", ["\\cA", "\\c", "\\u", "\\xZZ", "\\U", "\\400", "a\\x", "\\u00e9", "\\U0001F600"]
)
def test_ansi_c_that_shells_read_too_differently_is_refused(body: str) -> None:
    with pytest.raises(shell.ShellSyntaxError):
        shell.ansi_c_readings(body)


@pytest.mark.parametrize(
    ("word", "includes"),
    [
        ("{01..03}", {"1", "01", "3", "03"}),
        ("{@..B}", {"@", "A", "B"}),
        ("{Z..a}", {"Z", "\\", "", "a"}),
        ("{1..5..-2}", {"1", "3", "5"}),
    ],
)
def test_every_shell_s_brace_sequence_is_kept(word: str, includes: set[str]) -> None:
    expanded = shell.expand_braces(word, word)
    assert expanded is not None
    assert includes <= set(expanded)


def test_a_sequence_with_a_zero_step_is_not_followed(config: SessionConfig) -> None:
    assert shell.expand_braces("{1..3..0}", "{1..3..0}") is None
    assert sp.BRACE_UNBOUNDED.split("{word}")[0] in _decide(config, "touch f{1..3..0}")


@pytest.mark.parametrize("command", ["ksh -c 'touch x'", "ksh <<'EOF'\ntouch x\nEOF\n"])
def test_a_ksh_command_string_is_refused(config: SessionConfig, command: str) -> None:
    assert "ksh" in _decide(config, command)
