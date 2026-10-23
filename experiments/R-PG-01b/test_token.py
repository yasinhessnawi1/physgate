"""Tests of how launch.sh handles the run account's token (token.sh), with a dummy token only.

Run explicitly, in the run checkout: ``uv run --frozen pytest -q experiments/R-PG-01b``.

Every external command the launcher's token functions run is recorded, with its arguments, by a
shim on ``PATH``; the dummy token must be in none of them, in no output and no log, and in the
environment of the one child given it and of no other.
"""

from __future__ import annotations

import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import testsupport as T  # noqa: E402

TOKEN_SH = HERE / "token.sh"
LAUNCH = HERE / "launch.sh"
#: An obvious dummy of the token's shape: never a credential.
DUMMY = T.DUMMY_TOKEN
NAME = T.TOKEN_NAME
SHIMMED = ("grep", "sed", "tr", "wc", "head", "cat", "setsid", "env", "sh", "sleep", "ps")


def shims(tmp: Path) -> tuple[Path, Path]:
    """A directory of shims that log each call's arguments, then run the real command."""
    bin_dir, log = tmp / "shims", tmp / "argv.log"
    bin_dir.mkdir()
    for name in SHIMMED:
        real = subprocess.run(
            ["/bin/sh", "-c", f"command -v {name}"], capture_output=True, text=True, check=False
        ).stdout.strip()
        if not real:
            continue
        shim = bin_dir / name
        shim.write_text(f'#!/bin/sh\nprintf "%s\\n" "{name} $*" >> "{log}"\nexec "{real}" "$@"\n')
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return bin_dir, log


def drive(tmp: Path, env_line: str, script: str) -> tuple[subprocess.CompletedProcess[str], str]:
    """Source token.sh in a bash that runs ``script``, every command shimmed."""
    env_file = tmp / "run.env"
    env_file.write_text(f"OTHER=1\n{env_line}\n# a comment\n")
    bin_dir, log = shims(tmp)
    done = subprocess.run(
        ["bash", "-c", f'set -euo pipefail\nsource "{TOKEN_SH}"\n{script}', "drive", str(env_file)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp)},
        timeout=60,
    )
    return done, log.read_text() if log.exists() else ""


def test_the_token_is_loaded_unexported_and_given_to_one_child_alone(tmp_path: Path) -> None:
    done, argv = drive(
        tmp_path,
        T.token_line(DUMMY),
        """
rpb_load_token "$1"
echo "loaded: ${#RPB_TOKEN} characters"
( rpb_exec_with_token sh -c 'echo "child: ${CLAUDE_CODE_OAUTH_TOKEN:+given}"' )
rpb_exec_with_token sleep 2 &
pid=$!
ps -o args= -p "$pid" > "$HOME/ps.txt" || true
wait "$pid"
env > "$HOME/launcher-env.txt"
rpb_drop_token
echo "dropped: ${RPB_TOKEN:-none}"
""",
    )
    assert done.returncode == 0, done.stderr
    assert f"loaded: {len(DUMMY)} characters" in done.stdout
    assert "child: given" in done.stdout and "dropped: none" in done.stdout
    assert DUMMY not in done.stdout + done.stderr + argv
    assert DUMMY not in (tmp_path / "ps.txt").read_text()
    assert NAME not in (tmp_path / "launcher-env.txt").read_text()
    assert "sleep 2" in argv  # the child's own arguments were seen, and hold no token


@pytest.mark.parametrize(
    "line",
    [
        T.token_line(" " + DUMMY),
        T.token_line(DUMMY + " trailing"),
        T.token_line(f"'{DUMMY}'", before="export "),
        T.token_line(DUMMY) + "\n" + T.token_line(DUMMY),
        T.token_line(DUMMY, before="  ", between=" = ") + "\n" + T.token_line(DUMMY),
        T.token_line("sk-ant-" + "api03-" + "DUMMY-not-a-credential-" + "0" * 10),
        "",
    ],
    ids=[
        "a-space-after-the-equals",
        "trailing-words",
        "exported-and-quoted",
        "two-lines",
        "a-second-spelling",
        "another-kind-of-key",
        "no-line",
    ],
)
def test_a_malformed_env_file_is_refused_without_echoing_any_of_it(
    tmp_path: Path, line: str
) -> None:
    done, argv = drive(tmp_path, line, 'rpb_load_token "$1" && echo LOADED || echo REFUSED')
    assert "REFUSED" in done.stdout and "LOADED" not in done.stdout
    assert "DUMMY" not in done.stdout + done.stderr + argv
    assert "token's shape" in done.stderr


def test_the_scan_counts_files_and_puts_no_token_on_a_command_line(tmp_path: Path) -> None:
    run, scratch = tmp_path / "run", tmp_path / "scratch"
    (run / "a").mkdir(parents=True)
    scratch.mkdir()
    (run / "a" / "leak.txt").write_text(f"x {DUMMY} y\n")
    (scratch / "partial.txt").write_text("a sk-ant- prefix and oat01\n")
    (scratch / "clean.txt").write_text("nothing\n")
    done, argv = drive(
        tmp_path,
        T.token_line(DUMMY),
        f'rpb_load_token "$1"\nrpb_scan "{run}" "{scratch}" || echo "SCAN FOUND"\nrpb_drop_token',
    )
    assert "scan token: 1 files" in done.stdout and "scan sk-ant-: 2 files" in done.stdout
    assert "scan oat01: 2 files" in done.stdout and "SCAN FOUND" in done.stdout
    assert DUMMY not in done.stdout + done.stderr + argv
    assert "grep" in argv  # the scan ran through the shimmed grep, and its arguments hold no token


def test_the_token_alone_is_looked_for_where_the_prefixes_are_named(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "log").write_text("scan sk-ant-: 0 files; scan oat01: 0 files\n")
    done, argv = drive(
        tmp_path,
        T.token_line(DUMMY),
        f'rpb_load_token "$1"\nrpb_scan_token "{tmp_path / "d"}" && echo CLEAN',
    )
    assert "CLEAN" in done.stdout and "scan token: 0 files" in done.stdout
    assert "sk-ant-:" not in done.stdout and DUMMY not in done.stdout + done.stderr + argv


def test_a_clean_scan_succeeds(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f.txt").write_text("nothing\n")
    done, _ = drive(
        tmp_path,
        T.token_line(DUMMY),
        f'rpb_load_token "$1"\nrpb_scan "{tmp_path / "d"}" && echo CLEAN',
    )
    assert "CLEAN" in done.stdout and "scan token: 0 files" in done.stdout


def test_launch_sh_gives_the_token_through_token_sh_alone() -> None:
    text = LAUNCH.read_text()
    assert 'source "$HERE/token.sh"' in text or 'source "$HERE/token.sh"' in text
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    for line in code:
        assert NAME + "=" not in line or line.strip().startswith("unset "), line
        assert not re.search(r"export\s+CLAUDE_CODE_OAUTH_TOKEN", line), line
        assert "$CLAUDE_CODE_OAUTH_TOKEN" not in line and "${CLAUDE_CODE_OAUTH_TOKEN" not in line, (
            line
        )
        assert not re.search(r"set\s+-[a-z]*x", line) and "xtrace" not in line, line
    # Every use of the token's value is token.sh's: the launcher only names the functions.
    assert "$RPB_TOKEN" not in text and "${RPB_TOKEN" not in text


def test_token_sh_itself_never_prints_or_passes_the_value() -> None:
    code = [ln for ln in TOKEN_SH.read_text().splitlines() if not ln.lstrip().startswith("#")]
    uses = [ln for ln in code if "RPB_TOKEN" in ln]
    assert uses, "token.sh reads the token into RPB_TOKEN"
    for line in uses:
        assert not re.search(r"\b(echo|say|tee)\b", line), line
        # The value goes into the one child's environment, or into a pattern file by printf.
        assert (
            "RPB_TOKEN=" in line
            or f'export {NAME}="$RPB_TOKEN"' in line
            or "printf '%s\\n' \"$RPB_TOKEN\"" in line
            or "${#RPB_TOKEN}" in line
            or "unset RPB_TOKEN" in line
            or '-n "$RPB_TOKEN"' in line
            or '-z "$RPB_TOKEN"' in line
        ), line


def test_no_committed_file_holds_a_real_looking_token() -> None:
    shape = re.compile(r"sk-ant-(?:oat|api)[0-9]{2}-[A-Za-z0-9_-]{20,}")
    for path in sorted(HERE.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        for found in shape.findall(path.read_text(errors="replace")):
            assert "dummy" in found.lower(), (path.name, found[:16])
