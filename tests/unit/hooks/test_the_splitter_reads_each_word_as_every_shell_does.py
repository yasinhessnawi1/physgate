r"""Every word a real shell makes of a command is a word the shell layer checks.

The shell layer checks the words it expects a command to become. If a shell makes a word
it did not expect, a path can reach a protected root unseen, so each construct it resolves
is put through every shell installed here (bash, zsh, sh, dash; in CI, Linux's bash 5 and
dash) and held to one property: **what the shell produces is among what the layer checks**,
or the shell fails the command, or the layer refuses the construct. The layer may check
more than a shell produces, never less.

Only ``printf``, ``cd`` and ``pwd`` run, with globbing off and a bare environment, in a
temporary directory: nothing is written. ksh reads quoted braces and escapes unlike the
others; its command strings are refused, so it is not held to this.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from physgate.hooks import shell
from physgate.hooks import shell_paths as sp

_CANDIDATES = {
    "bash": ["bash", "--norc", "--noprofile", "-c"],
    "zsh": ["zsh", "-f", "-c"],
    "sh": ["sh", "-c"],
    "dash": ["dash", "-c"],
}


def _shells() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name, argv in _CANDIDATES.items():
        path = shutil.which(name)
        if path is not None:
            found[name] = [path, *argv[1:]]
    return found


SHELLS = _shells()
NOGLOB = {"zsh": "setopt noglob; "}


def _run(name: str, script: str, cwd: Path, home: Path) -> subprocess.CompletedProcess[bytes]:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "LC_ALL": "C"}
    argv = [*SHELLS[name], NOGLOB.get(name, "set -f; ") + script]
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=20, check=False)


pytestmark = pytest.mark.skipif(not SHELLS, reason="no shell installed")

BRACES = [
    "a{b,c}d", "{a,{b,c}}", "{a{b,c}}", "{a,b}{c,d}", "{,}", "x{a,}", "{}", "{a}",
    "x{a..c}y", "{z..a}", "{a..Z}", "{1..-2}", "{-1..1}", "{1..5..-2}", "{a..e..2}",
    "{01..03}", "{1..010}", "{-01..1}", "\\{a,b}", "'{a,b}'", '"{a,b}"', "{a,b\\}",
    "{a\\,b}", "{a..c}{1,2}", "{{a,b},c}", "{a,b}c{d,e}", "{@..B}", "{a..}", "{1..2..3..4}",
    "{a,b}}", "{{a,b}", "a{1..3}{x,y}", ".physgate/{series,x}/f", ".phys{gate,}/series/f",
]  # fmt: skip

ANSI_C = [
    "\\x41", "\\x4", "\\x414", "\\101", "\\1011", "\\0101", "\\7", "\\u00e9", "\\U0001F600",
    "\\u", "\\cA", "\\c", "\\e", "\\E", "\\?", "\\q", '\\"', "\\a\\b\\f\\n\\r\\t\\v", "\\\\",
    "\\x2ephysgate/series/f", "\\056physgate", "\\400", "\\777", "\\xZZ", "\\x",
]  # fmt: skip

CDS = [
    "cd a; cd x; cd -",
    "OLDPWD={t}/x; cd -",
    "HOME={t}/x; cd",
    "CDPATH={t}/x; cd b",
    "CDPATH=x cd b",
    "CDPATH=:x; cd b",
    "cd no-such-dir 2>/dev/null; true",
    "(cd a); true",
    "false && cd a; true",
    "cd a; cd ~-",
    "cd ~+/a",
    "cd a/../x",
    "cd ./a/b",
    "pushd a >/dev/null; pushd x >/dev/null; popd >/dev/null",
    "cd a; cd a x 2>/dev/null; true",
    "for d in a x; do cd $d; cd ..; done; cd a",
    "d=x; cd $d/b",
]


def _checked_words(fragment: str) -> set[str] | None:
    (cmd,) = shell.parse("printf %s " + fragment)
    alternatives = cmd.alternatives.get(2, ())
    if alternatives is None:
        return None
    return {cmd.argv[2], *alternatives}


@pytest.mark.parametrize("shell_name", sorted(SHELLS))
@pytest.mark.parametrize("fragment", BRACES)
def test_every_word_a_shell_makes_of_a_brace_pattern_is_checked(
    tmp_path: Path, shell_name: str, fragment: str
) -> None:
    checked = _checked_words(fragment)
    if checked is None:
        return  # refused where it writes
    done = _run(shell_name, f"printf '%s\\n' {fragment}", tmp_path, tmp_path)
    if done.returncode != 0:
        return  # the shell fails the command: nothing runs
    produced = set(done.stdout.decode("utf-8", "surrogateescape").splitlines())
    assert produced <= checked, f"{shell_name} made {produced - checked} of {fragment!r}"


@pytest.mark.parametrize("shell_name", sorted(SHELLS))
@pytest.mark.parametrize("body", ANSI_C)
def test_every_shell_s_reading_of_ansi_c_quoting_is_checked(
    tmp_path: Path, shell_name: str, body: str
) -> None:
    try:
        readings = {os.fsencode(r) for r in shell.ansi_c_readings(body).values()}
    except shell.ShellSyntaxError:
        return  # refused
    done = _run(shell_name, f"printf '%s' $'{body}'", tmp_path, tmp_path)
    if done.returncode != 0:
        return
    assert done.stdout in readings, f"{shell_name} read $'{body}' as {done.stdout!r}"


def _possible_directories(command: str, start: str) -> set[str] | None:
    env = sp._Env()  # noqa: SLF001 - the model under test
    cwds = [start]
    for cmd in shell.parse(command):
        env.record(cmd, cwds)
        try:
            cwds = sp._next_cwds(cmd, cwds, env)  # noqa: SLF001
        except sp._UnknownDirectoryError:  # noqa: SLF001
            return None
    return {os.path.realpath(c) for c in cwds}


@pytest.mark.parametrize("shell_name", sorted(SHELLS))
@pytest.mark.parametrize("command", CDS)
def test_every_directory_a_shell_reaches_is_one_the_layer_judges_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell_name: str, command: str
) -> None:
    root = Path(os.path.realpath(tmp_path))
    for d in ("a/b", "x/b", "home"):
        (root / d).mkdir(parents=True)
    command = command.replace("{t}", str(root))
    monkeypatch.setenv("HOME", str(root / "home"))
    monkeypatch.delenv("OLDPWD", raising=False)
    monkeypatch.delenv("CDPATH", raising=False)
    judged = _possible_directories(command, str(root))
    if judged is None:
        return  # refused
    done = _run(shell_name, f"{command}; pwd -P", root, root / "home")
    reached = os.path.realpath(done.stdout.decode().strip().splitlines()[-1])
    assert reached in judged, f"{shell_name} reached {reached}; judged {sorted(judged)}"
