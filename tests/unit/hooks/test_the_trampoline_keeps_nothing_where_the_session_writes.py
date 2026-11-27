"""The hook trampoline keeps its input and answer where no command of the session writes.

Every role, baseline and reviewer session's environment names its own temporary directory as
``TMPDIR``, which its commands write. The trampoline around every hook command holds the hook's
input and answer in two files: made in that directory, a command of the session could replace
the answer before the trampoline passes it on, and where that directory is gone (a session left
running after its run removed it) every hook would fail. So the trampoline makes them where the
system's default is, whatever ``TMPDIR`` says, and the hook is not told one either.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

TRAMPOLINE = Path(__file__).resolve().parents[3] / "src" / "physgate" / "hooks" / "trampoline.sh"


def _through(command: list[str], tmpdir: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", str(TRAMPOLINE), "5", *command],
        input="{}",
        env={"PATH": "/usr/bin:/bin", "TMPDIR": tmpdir},
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_hook_runs_where_the_session_s_temporary_directory_is_gone(tmp_path: Path) -> None:
    done = _through(["/bin/cat"], str(tmp_path / "gone"))
    assert done.returncode == 0, done.stderr
    assert done.stdout == "{}"


def test_nothing_of_the_trampoline_is_made_in_the_session_s_temporary_directory(
    tmp_path: Path,
) -> None:
    own = tmp_path / "own"
    own.mkdir()
    done = _through(["/bin/sh", "-c", 'echo "${TMPDIR-unset}"; ls -A "$0"', str(own)], str(own))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["unset"]
