"""R-PG-02: `physgate catches` over one run directory and its controls, held to the rows.

Usage, after the run only: uv run python -I read_catches.py <run-dir>

Prints the command's rows for the injected log and the controls log. Exits 1 unless, in the
injected log's ``all`` row, ``caught_after_reviewer_passed`` equals C (rows whose review passed
and whose gate failed) and ``artefacts_caught`` equals the rows the gate caught, and, in the
controls log's, ``artefacts_caught`` equals the rows whose twin the gate failed. Run once for
each of the three run directories.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

#: The command, from the environment this script runs in.
PHYSGATE = str(Path(sys.executable).parent / "physgate")


def all_row(run_dir: Path, label: str) -> dict[str, Any]:
    """The command's ``all`` row for one log (zeros when it caught nothing), every row printed."""
    out = subprocess.run(
        [PHYSGATE, "catches", "--run-dir", str(run_dir)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    found = [json.loads(line) for line in out.splitlines() if line.strip()]
    for row in found:
        print(label, json.dumps(row, sort_keys=True))
    rows = [r for r in found if r["name"] == "all"]
    if len(rows) > 1:
        msg = f"{label}: more than one 'all' row"
        raise SystemExit(msg)
    return rows[0] if rows else {"artefacts_caught": 0, "caught_after_reviewer_passed": 0}


def main(run: Path) -> int:
    lines = (run / "results.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    c = sum(r["reviewer_verdict"] == "pass" and r["gate_verdict"] == "fail" for r in rows)
    caught = sum(r["gate_verdict"] == "fail" for r in rows)
    twins_failed = sum(r["control_verdict"] == "fail" for r in rows)
    injected = all_row(run, "injected")
    controls = all_row(run / "controls", "controls")
    holds = (
        injected["caught_after_reviewer_passed"] == c
        and injected["artefacts_caught"] == caught
        and controls["artefacts_caught"] == twins_failed
    )
    print(
        json.dumps(
            {
                "C_from_rows": c,
                "caught_from_rows": caught,
                "twins_failed_from_rows": twins_failed,
                "holds": holds,
            },
            sort_keys=True,
        )
    )
    return 0 if holds else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]).resolve()))
