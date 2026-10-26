"""Tests of token.sh, and of how launch.sh and authoring.sh handle the token, with a dummy only.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

Every external command the token functions run is recorded, with its arguments, by a shim on
``PATH``; the dummy token must be in none of them, in no output and no log, and in the
environment of the one child given it and of no other. (R-PG-01b's tests of its own token.sh.)
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
import fixture as fx  # noqa: E402

TOKEN_SH = HERE / "token.sh"
DUMMY = fx.DUMMY_TOKEN
NAME = fx.TOKEN_NAME
SHIMMED = ("grep", "sed", "tr", "wc", "head", "cat", "setsid", "env", "sh", "sleep", "ps")


def shims(tmp: Path) -> tuple[Path, Path]:
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
        fx.token_line(DUMMY),
        """
rp3_load_token "$1"
echo "loaded: ${#RP3_TOKEN} characters"
( rp3_exec_with_token sh -c 'echo "child: ${CLAUDE_CODE_OAUTH_TOKEN:+given}"' )
env > "$HOME/launcher-env.txt"
rp3_drop_token
echo "dropped: ${RP3_TOKEN:-none}"
""",
    )
    assert done.returncode == 0, done.stderr
    assert f"loaded: {len(DUMMY)} characters" in done.stdout
    assert "child: given" in done.stdout and "dropped: none" in done.stdout
    assert DUMMY not in done.stdout + done.stderr + argv
    assert NAME not in (tmp_path / "launcher-env.txt").read_text()


@pytest.mark.parametrize(
    "line",
    [
        fx.token_line(" " + DUMMY),
        fx.token_line(DUMMY + " trailing"),
        fx.token_line(f"'{DUMMY}'", before="export "),
        fx.token_line(DUMMY) + "\n" + fx.token_line(DUMMY),
        fx.token_line("sk-ant-" + "api03-" + "DUMMY-not-a-credential-" + "0" * 10),
        "",
    ],
    ids=["a-space", "trailing-words", "exported-and-quoted", "two-lines", "another-key", "no-line"],
)
def test_a_malformed_env_file_is_refused_without_echoing_any_of_it(
    tmp_path: Path, line: str
) -> None:
    done, argv = drive(tmp_path, line, 'rp3_load_token "$1" && echo LOADED || echo REFUSED')
    assert "REFUSED" in done.stdout and "LOADED" not in done.stdout
    assert "DUMMY" not in done.stdout + done.stderr + argv


def test_the_scan_counts_files_and_puts_no_token_on_a_command_line(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "leak.txt").write_text(f"x {DUMMY} y\n")
    (run / "partial.txt").write_text("a sk-ant- prefix and oat01\n")
    done, argv = drive(
        tmp_path, fx.token_line(DUMMY), f'rp3_load_token "$1"\nrp3_scan "{run}" || echo FOUND'
    )
    assert "scan token: 1 files" in done.stdout and "scan sk-ant-: 2 files" in done.stdout
    assert "FOUND" in done.stdout and DUMMY not in done.stdout + done.stderr + argv


@pytest.mark.parametrize("script", ["launch.sh", "authoring.sh"])
def test_a_script_gives_the_token_through_token_sh_alone(script: str) -> None:
    text = (HERE / script).read_text()
    assert 'source "$HERE/token.sh"' in text
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    for ln in code:
        assert NAME + "=" not in ln or ln.strip().startswith("unset "), ln
        assert not re.search(r"export\s+CLAUDE_CODE_OAUTH_TOKEN", ln), ln
        assert "$CLAUDE_CODE_OAUTH_TOKEN" not in ln and "${CLAUDE_CODE_OAUTH_TOKEN" not in ln, ln
        assert not re.search(r"set\s+-[a-z]*x", ln) and "xtrace" not in ln, ln
    assert "$RP3_TOKEN" not in text and "${RP3_TOKEN}" not in text
    assert "rp3_drop_token" in text and "rp3_scan" in text


def test_token_sh_never_prints_or_passes_the_value() -> None:
    code = [ln for ln in TOKEN_SH.read_text().splitlines() if not ln.lstrip().startswith("#")]
    uses = [ln for ln in code if "RP3_TOKEN" in ln]
    assert uses
    for ln in uses:
        assert not re.search(r"\b(echo|say|tee)\b", ln), ln


def test_the_python_side_takes_the_token_from_its_own_environment_and_prints_it_nowhere() -> None:
    for script in ("reality.py", "authoring.py"):
        text = (HERE / script).read_text()
        assert "os.environ.get(common.TOKEN_VARIABLE" in text
        assert not re.search(r"print\([^)]*TOKEN", text)


def test_no_committed_file_holds_a_real_looking_token() -> None:
    shape = re.compile(r"sk-ant-(?:oat|api)[0-9]{2}-[A-Za-z0-9_-]{20,}")
    for path in sorted(HERE.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        for found in shape.findall(path.read_text(errors="replace")):
            assert "dummy" in found.lower(), (path.name, found[:16])


def test_token_sh_run_gives_the_token_to_one_step_watches_it_and_scans_what_it_wrote(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # setsid is Linux's; here a shim runs the step in a session of its own the same way.
    (bin_dir / "setsid").write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -c '
        '"import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])" "$@"\n'
    )
    (bin_dir / "setsid").chmod(0o755)
    env_file = tmp_path / "run.env"
    env_file.write_text(fx.token_line(DUMMY) + "\n")
    out = tmp_path / "out"
    step = 'echo "${CLAUDE_CODE_OAUTH_TOKEN:+given}" > "$1/seen.txt"'
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "RP3_ENV_FILE": str(env_file),
        "RP3_WATCH_SECONDS": "1",
    }
    done = subprocess.run(
        [
            "bash",
            str(TOKEN_SH),
            "run",
            str(tmp_path / "log"),
            "reality",
            str(out),
            "--",
            "sh",
            "-c",
            step,
            "x",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert (out / "seen.txt").read_text() == "given\n"
    log = (tmp_path / "log").read_text()
    assert "scan token: 0 files" in log and DUMMY not in log + done.stdout + done.stderr
    leak = 'echo "$CLAUDE_CODE_OAUTH_TOKEN" > "$1/leak.txt"'
    done = subprocess.run(
        [
            "bash",
            str(TOKEN_SH),
            "run",
            str(tmp_path / "log2"),
            "reality",
            str(out),
            "--",
            "sh",
            "-c",
            leak,
            "x",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )
    assert done.returncode == 1 and "found a hit" in (tmp_path / "log2").read_text()


def run_machine_bin(tmp: Path) -> Path:
    """Shims for the run machine's ``setsid`` and ``uname -s``, so the watcher acts as it would."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "setsid").write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -c '
        '"import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])" "$@"\n'
    )
    (bin_dir / "uname").write_text(
        '#!/bin/sh\n[ "${1:-}" = -s ] && { echo Linux; exit 0; }\nexec /usr/bin/uname "$@"\n'
    )
    for name in ("setsid", "uname"):
        (bin_dir / name).chmod(0o755)
    return bin_dir


def test_the_reading_resumed_after_a_limit_runs_whole_and_its_cut_step_kept_its_records(
    tmp_path: Path,
) -> None:
    # Step 1's call ends on the limit and leaves its failed-call file; the step then writes its own
    # records. Step 2, after the reset, runs in the same sessions directory with that file in it.
    bin_dir = run_machine_bin(tmp_path)
    env_file = tmp_path / "run.env"
    env_file.write_text(fx.token_line(DUMMY) + "\n")
    out = tmp_path / "sessions"
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "RP3_ENV_FILE": str(env_file),
        "RP3_WATCH_SECONDS": "1",
    }
    steps = (
        'echo "usage_limit_reached" > "$1/Q0001.attempt1.failed-20261105T0800Z.json"; '
        'sleep 3; echo "stopped" > "$1/STOPPED"',
        'sleep 3; echo "{}" > "$1/Q0001.attempt1.json"',
    )
    codes = []
    for n, step in enumerate(steps, 1):
        done = subprocess.run(
            ["bash", str(TOKEN_SH), "run", str(tmp_path / f"log{n}"), "reality", str(out), "--"]
            + ["sh", "-c", step, "x", str(out)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=120,
        )
        codes.append(done.returncode)
    assert (out / "STOPPED").read_text() == "stopped\n"  # the cut step's own record is written
    assert (out / "Q0001.attempt1.json").is_file()  # the resumed step is not aborted
    assert codes == [0, 0]
    assert "ABORT" not in (tmp_path / "log1").read_text() + (tmp_path / "log2").read_text()


def test_token_sh_run_needs_its_whole_command_line(tmp_path: Path) -> None:
    done = subprocess.run(
        ["bash", str(TOKEN_SH), "run", "log", "reality"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2 and "usage" in done.stderr
