"""R-PG-03 §7, before the freeze: the false-finding control's five keys, counted.

Usage:

    python -I ff_key_probe.py --repo <physgate checkout> \
        --run round-1=<the kept round's run directory> \
        --run repeat-K=<the noise run's run directory>

For each of the five keys (run, item, side, rubric item id) it counts the finding lines of the
practice cycle's review records that the key matches, under R-LAW-01 §2.2's rule for which review
line and which entries count. It imports R-LAW-01's own extractor (``law_extract.py``) unedited and
uses its ``load_run`` (which refuses a run whose four files differ from R-LAW-01's recorded digests,
whose corpus is not the tuning set, or whose reviewer kind or seed differ from R-LAW-01's pins),
``rejecting_entries`` and its last-review-line rule.

The kept round is R-LAW-01 §2.1's run ``round-1``; the noise run is its ``repeat-K``.

It prints counts only: per key, the number of matching lines, and how many of them each branch of
§2.2's entry rule supplies (an ``unmet`` or ``confirmed`` entry, or the failing item's entry added
because it was not among them). It never prints, stores or returns any text of a review, a line or
a corpus file.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

KEYS = (
    # (case, R-LAW-01 run label, run, item, side, rubric item id)
    ("1", "round-1", "the kept round", "a18", "twin", "ES-14"),
    ("2", "round-1", "the kept round", "a21", "twin", "D28"),
    ("3", "round-1", "the kept round", "a28", "twin", "MS-3"),
    ("4a", "repeat-K", "the noise run", "a22", "twin", "DS-27"),
    ("4b", "round-1", "the kept round", "a22", "injected", "DS-27"),
)


def _opt_all(argv: list[str], name: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == name and i + 1 < len(argv)]


def main(argv: list[str]) -> int:
    repo = Path(_opt_all(argv, "--repo")[0]).expanduser().resolve()
    run_dirs = {}
    for spec in _opt_all(argv, "--run"):
        label, _, path = spec.partition("=")
        run_dirs[label] = Path(path).expanduser().resolve()
    if set(run_dirs) != {"round-1", "repeat-K"}:
        print(json.dumps({"refused": "give exactly --run round-1=… and --run repeat-K=…"}))
        return 2

    law_dir = repo / "experiments" / "R-LAW-01"
    sys.path.insert(0, str(law_dir))
    import law_extract as lx  # R-LAW-01's frozen extractor, unedited

    extractor_sha256 = hashlib.sha256((law_dir / "law_extract.py").read_bytes()).hexdigest()
    digests_sha256 = hashlib.sha256(lx.INPUTS.read_bytes()).hexdigest()
    digests = json.loads(lx.INPUTS.read_text())
    pins = {p.label: p for p in lx.FROZEN.runs}

    runs = {}
    try:
        for label, path in run_dirs.items():
            runs[label] = lx.load_run(lx.FROZEN, pins[label], path, digests)
    except lx.Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1

    out = []
    for case, label, run_name, item, side, rubric_id in KEYS:
        run = runs[label]
        rows = [r for r in run.rows if r["artefact"] == item]
        n_lines = n_rejecting = n_failing_branch = 0
        reviews = 0
        for row in rows:
            sid = row["review_id"] if side == "injected" else row["control_id"]
            line = run.last[side].get(sid)
            if line is None or line["kind"] != "review_ran":
                continue
            reviews += 1
            res = line["result"]
            for _pos, it in lx.rejecting_entries(res):
                if it["item"] != rubric_id:
                    continue
                n_lines += 1
                if it["result"] in lx.REJECTING:
                    n_rejecting += 1
                else:
                    n_failing_branch += 1
        out.append(
            {
                "case": case,
                "key": {"run": run_name, "item": item, "side": side, "rubric_item_id": rubric_id},
                "results_rows": len(rows),
                "reviews_read": reviews,
                "lines_matched": n_lines,
                "of_them_unmet_or_confirmed": n_rejecting,
                "of_them_failing_item_branch": n_failing_branch,
            }
        )
    print(
        json.dumps(
            {
                "law_extract_sha256": extractor_sha256,
                "law_inputs_digests_sha256": digests_sha256,
                "runs_held_to_recorded_digests": sorted(runs),
                "keys": out,
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
