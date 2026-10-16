"""What a command's words become, and where it runs, is worked out exactly where it can be.

A root that is only refused, never put back, has no second layer: a write the shell layer
lets through stays. So the forms whose value does not depend on anything outside the command
are resolved here rather than skipped: a brace pattern is checked as every word it becomes,
ANSI-C quoting is decoded, and a ``cd`` is followed to every directory the command could be
in. The call's own working directory comes from the tool call, so one that is not absolute is
refused. Each test writes an inert marker into a refuse-only root made for it.

What stays out of reach is a word built from a variable or a command substitution, and the
directory after ``cd $(…)``; those are asserted as allowed at the end, so the boundary is
written down.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hook_helpers import bash

from physgate.hooks import paths, shell
from physgate.hooks import shell_paths as sp
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation

ROOT = ".physgate/series"
MARKER = "echo marker"


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    worktree = Path(os.path.realpath(tmp_path)) / "wt"
    (worktree / ROOT).mkdir(parents=True)
    (worktree / "modules" / "control").mkdir(parents=True)
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


def _decide(config: SessionConfig, command: str, cwd: str | None = None) -> str:
    hook_input = HookInput.model_validate(
        bash(command, cwd=config.worktree if cwd is None else cwd)
    )
    decision = sp.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def test_the_root_these_tests_write_into_is_refuse_only(config: SessionConfig) -> None:
    roots = {r.path: r.watch for r in config.protected_roots}
    assert roots[os.path.join(config.worktree, ROOT)] == "none"


# --- brace expansion -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "becomes"),
    [
        (".physgate/{series,x}/f", (".physgate/series/f", ".physgate/x/f")),
        (".phys{gate,x}/series/f", (".physgate/series/f", ".physx/series/f")),
        ("a{1..3}b", ("a1b", "a2b", "a3b")),
        ("{01..03}", ("1", "2", "3", "01", "02", "03")),
        ("{c..a}", ("c", "b", "a")),
        ("{5..1..2}", ("5", "3", "1")),
        ("{a,b}{c,d}", ("ac", "ad", "bc", "bd")),
        ("{a{b,c}}", ("{ab}", "{ac}")),
        ("x{,y}", ("x", "xy")),
        ("{only}", ("{only}",)),
    ],
)
def test_a_brace_pattern_becomes_every_word_the_shell_makes_of_it(
    word: str, becomes: tuple[str, ...]
) -> None:
    assert shell.expand_braces(word, word) == becomes


def test_a_quoted_brace_or_comma_is_not_a_pattern() -> None:
    (cmd,) = shell.parse("touch '{a,b}' \\{c,d} {e','f}")
    assert dict(cmd.alternatives) == {}
    (cmd,) = shell.parse("touch \\{a,b}{c,d}")
    assert dict(cmd.alternatives) == {1: ("{a,b}c", "{a,b}d")}


def test_a_brace_pattern_in_a_redirection_is_expanded_too() -> None:
    (cmd,) = shell.parse(f"{MARKER} > .physgate/{{series,x}}/f")
    assert cmd.redirects[0].alternatives == (".physgate/series/f", ".physgate/x/f")


def test_a_pattern_beyond_the_bound_is_recorded_as_unbounded() -> None:
    word = "{1..1025}"
    assert shell.expand_braces(word, word) is None
    assert shell.expand_braces("{1..1024}", "{1..1024}") is not None
    assert shell.expand_braces("{1..32}{1..32}", "{1..32}{1..32}") is not None
    assert shell.expand_braces("{1..33}{1..32}", "{1..33}{1..32}") is None


@pytest.mark.parametrize(
    "command",
    [
        f"{MARKER} > .physgate/{{series,x}}/step.json",
        f"{MARKER} > .phys{{gate,x}}/series/step.json",
        f"{MARKER} >> {{.physgate/series,/tmp}}/step.json",
        "touch .physgate/{series,x}/step.json",
        "cp README.md .phys{gate,}/series/",
    ],
)
def test_a_write_through_a_brace_pattern_into_a_refuse_only_root_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


def test_a_brace_pattern_beyond_the_bound_is_refused_only_where_it_writes(
    config: SessionConfig,
) -> None:
    assert sp.BRACE_UNBOUNDED.split("{word}")[0] in _decide(config, "touch f{1..2000}")
    assert sp.BRACE_UNBOUNDED.split("{word}")[0] in _decide(config, f"{MARKER} > f{{1..2000}}")
    assert _decide(config, "echo {1..2000}") == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "mkdir -p modules/control/{src,tests}",
        "touch modules/control/{a,b}.py",
        f"{MARKER} > modules/control/out{{1,2}}.txt",
        "cat .physgate/{series,x}/earlier.json",
    ],
)
def test_an_ordinary_brace_pattern_is_allowed(config: SessionConfig, command: str) -> None:
    assert _decide(config, command) == "allow"


# --- ANSI-C quoting --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "word"),
    [
        ("echo $'.physgate/series/f'", ".physgate/series/f"),
        ("echo $'\\x2ephysgate/series/f'", ".physgate/series/f"),
        ("echo $'\\056physgate'", ".physgate"),
        ("echo $'it\\'s'", "it's"),
        ("echo $'a\\tb\\n'", "a\tb\n"),
        ("echo $'\\u00e9'", "\u00e9"),
        ("echo $'\\q'", "\\q"),
        ("echo x$'y'z", "xyz"),
    ],
)
def test_ansi_c_quoting_is_decoded_to_the_word_the_command_receives(
    command: str, word: str
) -> None:
    (cmd,) = shell.parse(command)
    assert cmd.argv[1] == word
    assert 1 not in cmd.dynamic


def test_an_ansi_c_quote_that_cannot_be_decoded_is_not_guessed() -> None:
    with pytest.raises(shell.ShellSyntaxError):
        shell.parse("echo $'a\\0b'")
    with pytest.raises(shell.ShellSyntaxError):
        shell.parse("echo $'unterminated")


@pytest.mark.parametrize(
    "command",
    [
        f"{MARKER} > $'.physgate/series/step.json'",
        f"{MARKER} > $'\\x2ephysgate/series/step.json'",
        "cp README.md $'.physgate/series/step.json'",
        "cd $'.physgate' && touch series/step.json",
    ],
)
def test_a_write_through_ansi_c_quoting_into_a_refuse_only_root_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


def test_ordinary_ansi_c_quoting_is_allowed(config: SessionConfig) -> None:
    assert _decide(config, "printf $'a\\tb\\n' > modules/control/out.txt") == "allow"
    assert _decide(config, "grep $'\\t' modules/control/sim.py") == "allow"


# --- the working directory across cd -----------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        # a cd that fails leaves the directory where it was
        f"cd no-such-directory; {MARKER} > .physgate/series/step.json",
        # a cd in a subshell does not carry over
        f"(cd /tmp); {MARKER} > .physgate/series/step.json",
        # a cd that does not run
        f"false && cd /tmp; {MARKER} > .physgate/series/step.json",
        # back to where an earlier cd went
        f"cd .physgate && cd /tmp && cd - && {MARKER} > series/step.json",
        f"pushd .physgate && pushd /tmp && popd && {MARKER} > series/step.json",
        # a cd target that is a brace pattern
        f"cd .phys{{gate,x}} && {MARKER} > series/step.json",
    ],
)
def test_a_write_from_any_directory_the_command_could_be_in_is_judged(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


def test_zsh_s_two_word_cd_is_followed_as_a_substitution(config: SessionConfig) -> None:
    cwd = os.path.join(config.worktree, "modules")
    assert _decide(config, f"cd modules .physgate/series && {MARKER} > f", cwd=cwd) != "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"cd modules/control && {MARKER} > out.txt",
        f"cd /tmp && {MARKER} > notes.txt",
        f"cd modules && cd control && {MARKER} > out.txt",
        f"cd - && {MARKER} > modules/control/out.txt",
        "pushd modules && popd",
    ],
)
def test_an_ordinary_cd_is_allowed(config: SessionConfig, command: str) -> None:
    assert _decide(config, command) == "allow"


def test_cd_dash_returns_only_to_a_directory_already_counted(
    config: SessionConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `cd -` goes to the directory before the last cd, never home; a bare `cd` goes home.
    monkeypatch.setenv("HOME", os.path.join(config.worktree, ".physgate"))
    assert _decide(config, f"cd - && {MARKER} > series/step.json") == "allow"
    assert _decide(config, f"cd && {MARKER} > series/step.json") != "allow"


def test_a_command_that_could_be_in_too_many_directories_is_refused(
    config: SessionConfig,
) -> None:
    command = " && ".join(f"cd d{n}" for n in range(7)) + " && touch x"
    assert _decide(config, command) == sp.CWD_UNBOUNDED.format(limit=sp.CWD_LIMIT)
    fewer = " && ".join(f"cd d{n}" for n in range(5)) + " && touch x"
    assert _decide(config, fewer) == "allow"


# --- the call's own working directory -----------------------------------------------------


@pytest.mark.parametrize("cwd", ["relative/somewhere", "", ".", "wt"])
def test_a_call_whose_working_directory_is_not_absolute_is_refused(
    config: SessionConfig, cwd: str
) -> None:
    told = _decide(config, f"{MARKER} > series/step.json", cwd=cwd)
    assert told == sp.UNKNOWN_CWD.format(cwd=cwd)
    assert _decide(config, "ls", cwd=cwd) == sp.UNKNOWN_CWD.format(cwd=cwd)


def test_a_call_whose_working_directory_is_absolute_is_judged_as_before(
    config: SessionConfig,
) -> None:
    assert _decide(config, f"{MARKER} > modules/control/out.txt") == "allow"
    inside = os.path.join(config.worktree, ".physgate")
    assert _decide(config, f"{MARKER} > series/step.json", cwd=inside) != "allow"


# --- what stays out of reach ---------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        f"a=$(printf .phys); b=gate; {MARKER} > $a$b/series/step.json",
        f"{MARKER} > $(printf .physgate)/series/step.json",
        f"cd $(printf .physgate) && {MARKER} > series/step.json",
    ],
    ids=["variable-fragments", "substitution", "cd-substitution"],
)
def test_a_word_known_only_at_run_time_is_not_refused(config: SessionConfig, command: str) -> None:
    # Allowed on purpose: refusing every word this layer cannot resolve would refuse
    # ordinary commands (`rm $tmp`). For a refuse-only root these are a recorded residual.
    assert _decide(config, command) == "allow"


# --- the cost of judging many words ------------------------------------------------------


def _count_root_resolutions(
    config: SessionConfig, monkeypatch: pytest.MonkeyPatch
) -> dict[str, int]:
    roots = {r.path for r in config.protected_roots}
    counts: dict[str, int] = {}
    real = paths._spellings

    def counting(path: str) -> set[str]:
        if path in roots:
            counts[path] = counts.get(path, 0) + 1
        return real(path)

    monkeypatch.setattr(paths, "_spellings", counting)
    return counts


def test_each_root_is_resolved_once_per_call_however_many_words_are_judged(
    config: SessionConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    counts = _count_root_resolutions(config, monkeypatch)
    command = f"cd modules && cd control && touch f{{1..{shell.BRACE_LIMIT}}}.txt"
    assert _decide(config, command) == "allow"
    assert counts, "no root was resolved"
    assert max(counts.values()) == 1
    assert paths._ROOTS_TAKEN is None
    assert paths._PATHS_TAKEN is None


def test_outside_a_shell_call_every_judgement_reads_the_roots_afresh(
    config: SessionConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    counts = _count_root_resolutions(config, monkeypatch)
    target = os.path.join(config.worktree, "modules", "control", "f.txt")
    paths.protection(target, config.worktree, config, writing=True)
    paths.protection(target, config.worktree, config, writing=True)
    assert counts
    assert min(counts.values()) == 2  # noqa: PLR2004 - two judgements, two resolutions
