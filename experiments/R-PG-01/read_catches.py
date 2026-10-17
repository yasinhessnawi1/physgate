"""`physgate catches --run-dir` over the run directory and its controls, held to the rows.

Usage, after the run only: uv run python -I read_catches.py <run-dir>

Prints the command's rows for the injected log and the controls log. Exits 1 unless, in the
injected log's `all` row, `caught_after_reviewer_passed` equals C (rows approved and caught) and
`artefacts_caught` equals the rows the gate caught, and the controls log catches nothing.
"""

import json
import subprocess
import sys
from pathlib import Path

run = Path(sys.argv[1]).resolve()
rows = [json.loads(line) for line in (run / "results.jsonl").read_text().splitlines() if line.strip()]
c = sum(r["reviewer_verdict"] == "pass" and r["gate_verdict"] == "fail" for r in rows)
caught = sum(r["gate_verdict"] == "fail" for r in rows)


def all_row(run_dir: Path, label: str) -> dict:
    out = subprocess.run(
        ["physgate", "catches", "--run-dir", str(run_dir)], capture_output=True, text=True, check=True
    ).stdout
    found = [json.loads(line) for line in out.splitlines() if line.strip()]
    for row in found:
        print(label, json.dumps(row, sort_keys=True))
    (row,) = [r for r in found if r["name"] == "all"]
    return row


injected = all_row(run, "injected")
controls = all_row(run / "controls", "controls")
holds = (
    injected["caught_after_reviewer_passed"] == c
    and injected["artefacts_caught"] == caught
    and controls["artefacts_caught"] == 0
)
print(json.dumps({"C_from_rows": c, "caught_from_rows": caught, "holds": holds}, sort_keys=True))
sys.exit(0 if holds else 1)
