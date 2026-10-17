"""R6, after the run only: a second gate pass over the same corpus must give byte-identical records.
Usage: regate_r6.py <corpus> <run-dir> <seed> <fresh-empty-dir>"""
import json, sys
from pathlib import Path
from physgate.evaluation.inject.corpus import load_corpus
from physgate.evaluation.inject.materialise import materialise
from physgate.evaluation.inject.runner import _gate, review_id, control_id
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.events import GateRan, read_events

corpus = load_corpus(Path(sys.argv[1]).resolve())
run, seed, into = Path(sys.argv[2]).resolve(), int(sys.argv[3]), Path(sys.argv[4]).resolve()
gate = PhysicsGate()
differ = 0
for log_path, id_of, patch_of in (
    (run / "events.jsonl", review_id, lambda a: a.injected),
    (run / "controls" / "events.jsonl", control_id, lambda a: a.clean),
):
    first = {e.subtask_id: e.result for e in read_events(log_path) if isinstance(e, GateRan)}
    for a in corpus.artefacts:
        sid = id_of(seed, a.id)
        again = _gate(gate, materialise(corpus.base, patch_of(a), into / sid), sid)
        same = json.dumps(again.model_dump(mode="json"), sort_keys=True) == json.dumps(first[sid].model_dump(mode="json"), sort_keys=True)
        differ += not same
print(json.dumps({"compared": 2 * len(corpus.artefacts), "differ": differ}))
