"""R-PG-02, R4: the fresh set's precondition, held again at the run's commit. Counts only.

Usage (from the repository root):

    uv run python -I twins_fresh.py <corpus-dir> <fresh-empty-dir> [--any-count]

Every clean twin alone through the gate, and the base and every clean patch through the
source-consistency check; the injected patches are never gated or read. Prints the twins with
no failing record, of the set's size, the source check's counts by kind (never a fact), and
the records' sha256; the records go to ``<dir>/twins.records`` and are never read. Exits 0
only if the set is complete (ten of each class), every twin has no failing record and the
source check finds no mismatch. ``--any-count`` lifts the size, for a test corpus only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

#: The fresh set's seed (CRITERIA.md §2).
SEED = 13
PER_CLASS = 10


def precondition(corpus_dir: Path, into: Path, any_count: bool = False) -> dict[str, Any]:
    """Both halves of the precondition, as counts."""
    from physgate.evaluation.inject.corpus import load_corpus, require_complete
    from physgate.evaluation.inject.materialise import materialise
    from physgate.evaluation.inject.runner import _gate, control_id
    from physgate.evaluation.inject.source_check import check_sources
    from physgate.gate.runner import PhysicsGate

    into.mkdir(parents=True)
    corpus = load_corpus(corpus_dir.resolve())
    if not any_count:
        require_complete(corpus, PER_CLASS)
    gate = PhysicsGate()
    dumps: list[str] = []
    no_fail = 0
    for artefact in corpus.artefacts:
        cid = control_id(SEED, artefact.id)
        result = _gate(gate, materialise(corpus.base, artefact.clean, into / cid), cid)
        no_fail += all(r.outcome != "fail" for r in result.checks)
        dumps.append(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    records = "\n".join(dumps).encode()
    (into / "twins.records").write_bytes(records)
    found = check_sources(corpus)
    counts = {k: sum(f.kind == k for f in found) for k in ("mismatch", "unresolved", "subtracted")}
    return {
        "manifest_sha256": corpus.manifest_sha256,
        "twins": len(dumps),
        "twins_with_no_failing_record": no_fail,
        "records_sha256": hashlib.sha256(records).hexdigest(),
        "source_check": counts,
        "holds": no_fail == len(dumps)
        and (any_count or len(dumps) == 4 * PER_CLASS)
        and counts["mismatch"] == 0,
    }


def main(argv: list[str]) -> int:
    any_count = "--any-count" in argv
    argv = [a for a in argv if a != "--any-count"]
    if len(argv) != 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    out = precondition(Path(argv[0]), Path(argv[1]).resolve(), any_count)
    print(json.dumps(out, sort_keys=True))
    return 0 if out["holds"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
