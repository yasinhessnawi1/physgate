"""R-PG-02, R8: the lane budget split across the three runs, and each run's seeded lane plan.

Usage (from the repository root):

    uv run python -I lanes.py split <params_fresh.json> <params_old.json>
    uv run python -I lanes.py plan <corpus-dir> <seed> <lanes>
    uv run python -I lanes.py check <run-dir> <corpus-dir> <seed> <lanes>

Each prints one JSON document and exits 0 only if the rule holds.

- ``split``: the budget is 4 lanes in all. The two fresh-set arms get equal lanes, so the
  primary contrast's arms run alike; the old set takes the rest, never fewer than either fresh
  arm. With 4 that is 1, 1 and 2. The two parameters files must state exactly that.
- ``plan``: the instrument's own draw (``assign_lanes``) for the corpus at the seed: an
  artefact's twin runs on the artefact's lane, and each class is dealt round the lanes so no
  lane holds two more of a class than another. Prints counts per lane and per class and the
  sha256 of the ``lanes.json`` the run will write, nothing else. Before the run.
- ``check``: after the run, the run's ``lanes.json`` is the plan byte for byte, and every
  review record (``reviews/<id>.json``), of an artefact and of its twin, ran on that lane.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

#: The approved lane budget for the whole experiment (CRITERIA.md §12, row 9).
BUDGET = 4
#: The three runs, in the order the launch script starts them.
RUNS = ("a-fresh", "b-fresh", "a-old")


def split(budget: int = BUDGET) -> dict[str, int]:
    """The lanes of each run: the fresh arms equal, the old set the rest, never fewer."""
    fresh = budget // 3
    if fresh < 1:
        msg = f"a budget of {budget} lanes cannot run three runs at once"
        raise ValueError(msg)
    return {"a-fresh": fresh, "b-fresh": fresh, "a-old": budget - 2 * fresh}


def lanes_json(lane_of: dict[str, int]) -> bytes:
    """The bytes the instrument writes as ``lanes.json`` for this draw."""
    return (json.dumps(lane_of, indent=1, sort_keys=True) + "\n").encode()


def plan(corpus_dir: Path, seed: int, lanes: int) -> dict[str, Any]:
    """The seeded lane plan of one run, as counts and a digest, with the rule's verdict."""
    from physgate.evaluation.inject.corpus import load_corpus
    from physgate.evaluation.inject.runner import assign_lanes

    corpus = load_corpus(corpus_dir.resolve())
    lane_of = assign_lanes(seed, corpus.artefacts, lanes)
    per_lane = Counter(lane_of.values())
    per_class: dict[str, dict[int, int]] = {}
    for artefact in corpus.artefacts:
        cell = per_class.setdefault(artefact.error_class, dict.fromkeys(range(lanes), 0))
        cell[lane_of[artefact.id]] += 1
    balanced = all(max(c.values()) - min(c.values()) <= 1 for c in per_class.values())
    every = set(lane_of) == {a.id for a in corpus.artefacts}
    return {
        "lanes": lanes,
        "seed": seed,
        "items_per_lane": {str(k): 2 * per_lane.get(k, 0) for k in range(lanes)},
        "classes_per_lane": {
            c: {str(k): n for k, n in v.items()} for c, v in sorted(per_class.items())
        },
        "lanes_json_sha256": hashlib.sha256(lanes_json(lane_of)).hexdigest(),
        "holds": balanced and every,
    }


def check(run_dir: Path, corpus_dir: Path, seed: int, lanes: int) -> dict[str, Any]:
    """The run's lanes against the plan: ``lanes.json`` and every review record."""
    from physgate.evaluation.inject.corpus import load_corpus
    from physgate.evaluation.inject.runner import (
        LANES_NAME,
        REVIEWS_DIRNAME,
        assign_lanes,
        control_id,
        review_id,
    )

    corpus = load_corpus(corpus_dir.resolve())
    lane_of = assign_lanes(seed, corpus.artefacts, lanes)
    written = (run_dir / LANES_NAME).read_bytes()
    off: list[str] = []
    missing = 0
    for artefact in corpus.artefacts:
        for subtask in (review_id(seed, artefact.id), control_id(seed, artefact.id)):
            path = run_dir / REVIEWS_DIRNAME / f"{subtask}.json"
            if not path.is_file():
                missing += 1
                continue
            if json.loads(path.read_text())["lane"] != lane_of[artefact.id]:
                off.append(subtask)
    same = written == lanes_json(lane_of)
    return {
        "lanes_json_is_the_plan": same,
        "review_records_missing": missing,
        "reviews_off_their_lane": off,
        "holds": same and not off and missing == 0,
    }


def _split_files(fresh: Path, old: Path) -> dict[str, Any]:
    want = split()
    got = {
        "a-fresh": json.loads(fresh.read_text()).get("lanes"),
        "b-fresh": json.loads(fresh.read_text()).get("lanes"),
        "a-old": json.loads(old.read_text()).get("lanes"),
    }
    return {"budget": BUDGET, "rule": want, "files": got, "holds": got == want}


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["split"] and len(argv) == 3:
            out = _split_files(Path(argv[1]), Path(argv[2]))
        elif argv[:1] == ["plan"] and len(argv) == 4:
            out = plan(Path(argv[1]), int(argv[2]), int(argv[3]))
        elif argv[:1] == ["check"] and len(argv) == 5:
            out = check(Path(argv[1]), Path(argv[2]), int(argv[3]), int(argv[4]))
        else:
            print(__doc__.split("\n\n")[1], file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - any failure to read is a refusal, never a pass
        print(json.dumps({"refused": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(out, sort_keys=True))
    return 0 if out["holds"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
