"""R-PG-02, R6, after the run only: the gate is deterministic, so its records must repeat.

Usage (from the repository root):

    uv run python -I regate.py again <corpus-dir> <run-dir> <seed> <fresh-empty-dir>
    uv run python -I regate.py compare <run-dir> <other-run-dir>

- ``again``: a second gate pass over the set, every injected patch and every clean twin, into
  a fresh directory, compared with the run's own gate lines byte for byte (as JSON with sorted
  keys).
- ``compare``: two runs over the same set at the same seed (arm A's and arm B's on the fresh
  set) must have gated every item to byte-identical records.

Prints counts only and exits 0 only if nothing differs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _dump(result: Any) -> str:  # noqa: ANN401 - a GateResult
    return json.dumps(result.model_dump(mode="json"), sort_keys=True)


def _gate_lines(run: Path) -> dict[str, str]:
    from physgate.orchestrator.events import GateRan, read_events

    found: dict[str, str] = {}
    for log in (run / "events.jsonl", run / "controls" / "events.jsonl"):
        for event in read_events(log):
            if isinstance(event, GateRan):
                found[event.subtask_id] = _dump(event.result)
    return found


def again(corpus_dir: Path, run: Path, seed: int, into: Path) -> dict[str, Any]:
    """Gate the set once more and compare with the run's own lines."""
    from physgate.evaluation.inject.corpus import load_corpus
    from physgate.evaluation.inject.materialise import materialise
    from physgate.evaluation.inject.runner import _gate, control_id, review_id
    from physgate.gate.runner import PhysicsGate

    into.mkdir(parents=True)
    corpus = load_corpus(corpus_dir.resolve())
    first = _gate_lines(run)
    gate = PhysicsGate()
    differ = missing = 0
    for artefact in corpus.artefacts:
        for sid, patch in (
            (review_id(seed, artefact.id), artefact.injected),
            (control_id(seed, artefact.id), artefact.clean),
        ):
            if sid not in first:
                missing += 1
                continue
            result = _gate(gate, materialise(corpus.base, patch, into / sid), sid)
            differ += _dump(result) != first[sid]
    compared = 2 * len(corpus.artefacts)
    return {
        "compared": compared,
        "missing": missing,
        "differ": differ,
        "holds": differ == 0 and missing == 0,
    }


def compare(run: Path, other: Path) -> dict[str, Any]:
    """Two runs' gate lines over the same items, byte for byte."""
    a, b = _gate_lines(run), _gate_lines(other)
    differ = sum(a[k] != b[k] for k in a.keys() & b.keys())
    unmatched = len(a.keys() ^ b.keys())
    return {
        "compared": len(a.keys() & b.keys()),
        "unmatched": unmatched,
        "differ": differ,
        "holds": differ == 0 and unmatched == 0 and bool(a),
    }


def main(argv: list[str]) -> int:
    if argv[:1] == ["again"] and len(argv) == 5:
        out = again(Path(argv[1]), Path(argv[2]).resolve(), int(argv[3]), Path(argv[4]).resolve())
    elif argv[:1] == ["compare"] and len(argv) == 3:
        out = compare(Path(argv[1]).resolve(), Path(argv[2]).resolve())
    else:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0 if out["holds"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
