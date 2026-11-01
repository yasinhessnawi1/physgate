"""R-PG-03, §3.4 and §5 R8: the 3/3/2 lane split, each block's seeded plan, and the check after it.

Usage (from the checkout at ``R``)::

    python -I lanes.py split
    python -I lanes.py plan <corpus dir> <block>
    python -I lanes.py check <run dir> <corpus dir> <block> <arm>

Each prints one JSON document and exits 0 only if the rule holds.

- ``split``: the budget is R-PG-02's, 8 lanes: A2 3, A1 3 and B 2. Each arm's parameters file
  (``params_a.json`` for A2 and A1, ``params_b.json`` for B) is R-PG-02's ``params_fresh.json`` in
  every field but ``lanes``, and gives the arm its lanes.
- ``plan``: the instrument's own draw (``assign_lanes``) at the block's seed, for each arm's lane
  count, by R-PG-02's ``lanes.py`` unedited: an item's twin runs on the item's lane, and each class
  is dealt round the lanes so no lane holds two more of a class than another. All arms of a block
  use the block's seed, so A2 and A1, with 3 lanes each, have the same plan. Counts per lane and
  class, and the sha256 of each ``lanes.json``; nothing else. Before the block.
- ``check``: after the block, one arm's ``lanes.json`` is its plan byte for byte, and every review
  record of an item and of its twin ran on that lane (R-PG-02's rule, by its script).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

PARAMS = {"A2": "params_a.json", "A1": "params_a.json", "B": "params_b.json"}
BUDGET = 8


def frozen_lanes() -> ModuleType:
    """R-PG-02's ``lanes.py``, unedited, under a name of its own."""
    path = common.REPO / "experiments" / "R-PG-02" / "lanes.py"
    spec = importlib.util.spec_from_file_location("rpg02_lanes", path)
    if spec is None or spec.loader is None:
        raise ImportError("R-PG-02's lanes.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules["rpg02_lanes"] = module
    spec.loader.exec_module(module)
    return module


def split(here: Path = common.HERE, repo: Path = common.REPO) -> dict[str, Any]:
    """Each arm's parameters against R-PG-02's file and the 3/3/2 rule."""
    frozen = json.loads((repo / common.PARAMS_FRESH).read_text())
    got: dict[str, Any] = {}
    other_fields: dict[str, list[str]] = {}
    for arm, name in PARAMS.items():
        params = json.loads((here / name).read_text())
        got[arm] = params.get("lanes")
        other_fields[arm] = sorted(
            k
            for k in frozen.keys() | params.keys()
            if k != "lanes" and frozen.get(k) != params.get(k)
        )
    holds = got == common.LANES and sum(got.values()) == BUDGET and not any(other_fields.values())
    return {
        "budget": BUDGET,
        "rule": common.LANES,
        "files": got,
        "fields_other_than_lanes_that_differ": other_fields,
        "holds": holds,
    }


def plan(corpus_dir: Path, block: str) -> dict[str, Any]:
    """The block's seeded plan for each lane count its arms use."""
    lanes = frozen_lanes()
    seed = common.BLOCK_SEED[block]
    per_count = {n: lanes.plan(corpus_dir, seed, n) for n in sorted(set(common.LANES.values()))}
    by_arm = {arm: per_count[n] for arm, n in common.LANES.items()}
    return {
        "block": block,
        "seed": seed,
        "plans": {arm: p for arm, p in by_arm.items()},
        "a2_and_a1_share_a_plan": by_arm["A2"]["lanes_json_sha256"]
        == by_arm["A1"]["lanes_json_sha256"],
        "holds": all(p["holds"] for p in by_arm.values()),
    }


def check(run_dir: Path, corpus_dir: Path, block: str, arm: str) -> dict[str, Any]:
    """One arm's run against its plan, by R-PG-02's rule."""
    lanes = frozen_lanes()
    found: dict[str, Any] = lanes.check(
        run_dir, corpus_dir, common.BLOCK_SEED[block], common.LANES[arm]
    )
    return {"block": block, "arm": arm, **found}


def main(argv: list[str]) -> int:
    """One subcommand; exit 0 only if the rule holds."""
    try:
        if argv == ["split"]:
            out = split()
        elif argv[:1] == ["plan"] and len(argv) == 3 and argv[2] in common.BLOCKS:
            out = plan(Path(argv[1]), argv[2])
        elif (
            argv[:1] == ["check"]
            and len(argv) == 5
            and argv[3] in common.BLOCKS
            and argv[4] in common.ARMS
        ):
            out = check(Path(argv[1]), Path(argv[2]), argv[3], argv[4])
        else:
            print((__doc__ or "").split("\n\n")[1], file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - any failure to read is a refusal, never a pass
        print(json.dumps({"refused": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(out, sort_keys=True))
    return 0 if out["holds"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
