"""An experiment's scan that finds nothing reports 0 and lets its launch script go on.

grep exits 1 when it finds nothing, so a launch script running `grep … | wc -l` under
`set -euo pipefail` ended at its clean scan, before writing its closing lines. The shared
helper counts without that: the script runs under the same options here, over an empty
directory, a directory with hits and a directory it cannot read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

HELPER = Path(__file__).resolve().parents[2] / "scripts" / "experiment" / "scan.sh"


def _run(*dirs: Path, pattern: str = "oat01") -> subprocess.CompletedProcess[str]:
    script = (
        "set -euo pipefail\n"
        f'source "{HELPER}"\n'
        f'n="$(count_files_with {pattern} {" ".join(str(d) for d in dirs)})"\n'
        'echo "found $n"\n'
        "echo after\n"
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)


def test_a_scan_of_an_empty_directory_reports_zero_and_the_script_goes_on(tmp_path: Path) -> None:
    done = _run(tmp_path)
    assert done.returncode == 0
    assert done.stdout.splitlines() == ["found 0", "after"]


def test_a_scan_with_hits_counts_the_files(tmp_path: Path) -> None:
    for name in ("a", "b"):
        (tmp_path / name).write_text("token oat01 here\n")
    (tmp_path / "c").write_text("clean\n")
    done = _run(tmp_path)
    assert done.stdout.splitlines() == ["found 2", "after"]


def test_the_old_pipeline_did_end_its_script_on_a_clean_scan(tmp_path: Path) -> None:
    # The form the helper replaces, kept here so the failure it fixes stays visible.
    script = (
        "set -euo pipefail\n"
        f'n="$(grep -rlF -- oat01 {tmp_path} 2>/dev/null | wc -l | tr -d " ")"\n'
        "echo after\n"
    )
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert done.returncode != 0 and "after" not in done.stdout


def test_a_scan_of_a_directory_that_is_not_there_fails(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    done = _run(missing)
    assert done.returncode != 0 and "after" not in done.stdout
