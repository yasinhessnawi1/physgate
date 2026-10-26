"""R-PG-03, §5 R6, as R-PG-02's: the gate is deterministic, so its records must repeat.

Usage (from the checkout at ``R``, after a block has ended)::

    python -I regate.py block <block> <corpus dir> --a2 <run> --a1 <run> --b <run> --into <new dir>

For one block: a second gate pass over its corpus, every injected patch and every clean twin, into
a fresh directory, compared with A2's own gate lines byte for byte (as JSON with sorted keys); and
A1's and B's gate lines compared with A2's, item for item. Both comparisons are R-PG-02's
``regate.py``, imported unedited (``again`` and ``compare``). Prints counts only and exits 0 only
if nothing differs. A record that differs is a deviation for the gate's figures only (§11): the
reviewers' decisions stand.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def frozen_regate() -> ModuleType:
    """R-PG-02's ``regate.py``, unedited, under a name of its own."""
    path = common.REPO / "experiments" / "R-PG-02" / "regate.py"
    spec = importlib.util.spec_from_file_location("rpg02_regate", path)
    if spec is None or spec.loader is None:
        raise ImportError("R-PG-02's regate.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules["rpg02_regate"] = module
    spec.loader.exec_module(module)
    return module


def block(name: str, corpus: Path, runs: dict[str, Path], into: Path) -> dict[str, Any]:
    """R6 for one block: A2 gated again, and A1's and B's records against A2's."""
    regate = frozen_regate()
    again: dict[str, Any] = regate.again(corpus, runs["A2"], common.BLOCK_SEED[name], into)
    a1: dict[str, Any] = regate.compare(runs["A2"], runs["A1"])
    b: dict[str, Any] = regate.compare(runs["A2"], runs["B"])
    return {
        "block": name,
        "a2_gated_again": again,
        "a1_against_a2": a1,
        "b_against_a2": b,
        "holds": bool(again["holds"] and a1["holds"] and b["holds"]),
    }


def main(argv: list[str] | None = None) -> int:
    """R6 for one block; counts only; exit 0 only if nothing differs."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("cmd", choices=("block",))
    parser.add_argument("block", choices=common.BLOCKS)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--a2", type=Path, required=True)
    parser.add_argument("--a1", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    parser.add_argument("--into", type=Path, required=True)
    args = parser.parse_args(argv)
    runs = {"A2": args.a2.resolve(), "A1": args.a1.resolve(), "B": args.b.resolve()}
    try:
        found = block(args.block, args.corpus, runs, args.into.resolve())
    except Exception as exc:  # noqa: BLE001 - a run that cannot be read is a refusal
        print(json.dumps({"refused": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(found, sort_keys=True))
    return 0 if found["holds"] else 1


if __name__ == "__main__":
    sys.exit(main())
