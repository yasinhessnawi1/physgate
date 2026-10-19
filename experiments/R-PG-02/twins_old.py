"""R-PG-02, R4: the old set's 40 clean twins alone through the gate. Counts and a digest only.

Usage (from the repository root):

    uv run python -I twins_old.py <corpus-dir> <fresh-empty-dir> [<count> <records-sha256>]
        [--any-count]

Never materialises or gates an injected patch, and prints counts and digests only: never an
artefact id, a check name or a message. The full records go to ``<dir>/twins.records`` (one
JSON document per twin, in corpus order), to be compared byte for byte and never read.

- With no expectation (the one measurement at the criteria's freeze), it prints the count of
  twins with no failing record, of 40, and the records' sha256, and exits 0.
- With ``<count> <records-sha256>`` (the launch script, at the run's commit), it exits 0 only
  if both are reproduced exactly.
- The set must be complete (ten of each class); ``--any-count`` lifts that, for a test corpus
  only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

#: R-PG-01's seed: the twins are gated under the ids R-PG-01's run gave them.
SEED = 7


def gate_twins(
    corpus_dir: Path, into: Path, seed: int = SEED, any_count: bool = False
) -> dict[str, Any]:
    """Gate every clean twin of the corpus once; counts and the records' digest only."""
    from physgate.evaluation.inject.corpus import load_corpus, require_complete
    from physgate.evaluation.inject.materialise import materialise
    from physgate.evaluation.inject.runner import _gate, control_id
    from physgate.gate.runner import PhysicsGate

    into.mkdir(parents=True)  # must be new: a stale record set is never compared
    corpus = load_corpus(corpus_dir.resolve())
    if not any_count:
        require_complete(corpus, 10)
    gate = PhysicsGate()
    dumps: list[str] = []
    no_fail = 0
    for artefact in corpus.artefacts:
        cid = control_id(seed, artefact.id)
        result = _gate(gate, materialise(corpus.base, artefact.clean, into / cid), cid)
        no_fail += all(r.outcome != "fail" for r in result.checks)
        dumps.append(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    records = "\n".join(dumps).encode()
    (into / "twins.records").write_bytes(records)
    return {
        "manifest_sha256": corpus.manifest_sha256,
        "twins": len(dumps),
        "twins_with_no_failing_record": no_fail,
        "records_sha256": hashlib.sha256(records).hexdigest(),
    }


def main(argv: list[str]) -> int:
    any_count = "--any-count" in argv
    argv = [a for a in argv if a != "--any-count"]
    if len(argv) not in (2, 4):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    found = gate_twins(Path(argv[0]), Path(argv[1]).resolve(), any_count=any_count)
    if len(argv) == 2:
        print(json.dumps({**found, "measured": True}, sort_keys=True))
        return 0
    count, digest = int(argv[2]), argv[3]
    holds = found["twins_with_no_failing_record"] == count and found["records_sha256"] == digest
    print(
        json.dumps(
            {**found, "expected_count": count, "expected_records_sha256": digest, "holds": holds},
            sort_keys=True,
        )
    )
    return 0 if holds else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
