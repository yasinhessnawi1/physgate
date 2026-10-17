"""R4 at the run's commit, before any review: the 40 clean twins alone through the gate.

Usage: uv run python -I r4_twins.py <corpus-dir> <fresh-empty-dir> <expected-records-sha256>

Never materialises or gates an injected patch, and prints counts and digests only. The full
records go to <dir>/twins.records (one JSON document per twin, in corpus order), to be compared
byte for byte and never read. Exits 0 only on 40 of 40 twins with no failing record and the
expected records sha256; any other outcome exits 1, and the launch script stops the run.
"""

import hashlib
import json
import sys
from pathlib import Path

from physgate.evaluation.inject.corpus import load_corpus, require_complete
from physgate.evaluation.inject.materialise import materialise
from physgate.evaluation.inject.runner import _gate, control_id
from physgate.gate.runner import PhysicsGate

SEED = 7
corpus_dir, into, expected = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]
into.mkdir(parents=True)  # must be new: a stale record set is never compared
corpus = load_corpus(corpus_dir)
require_complete(corpus)
gate = PhysicsGate()
dumps, no_fail, passed = [], 0, 0
for artefact in corpus.artefacts:
    cid = control_id(SEED, artefact.id)
    result = _gate(gate, materialise(corpus.base, artefact.clean, into / cid), cid)
    no_fail += all(r.outcome != "fail" for r in result.checks)
    passed += result.verdict == "pass"
    dumps.append(json.dumps(result.model_dump(mode="json"), sort_keys=True))
records = "\n".join(dumps).encode()
(into / "twins.records").write_bytes(records)
found = {
    "manifest_sha256": corpus.manifest_sha256,
    "twins": len(dumps),
    "twins_with_no_failing_record": no_fail,
    "twins_verdict_pass": passed,
    "records_sha256": hashlib.sha256(records).hexdigest(),
}
holds = len(dumps) == no_fail == passed == 40 and found["records_sha256"] == expected
print(json.dumps({**found, "expected_records_sha256": expected, "holds": holds}, sort_keys=True))
sys.exit(0 if holds else 1)
