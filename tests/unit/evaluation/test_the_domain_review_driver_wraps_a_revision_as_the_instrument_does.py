"""The validation driver reviews a revision exactly as the injected-error instrument does.

The electrical and mechanical reviewers' validation reviews its revisions through the
driver's own wrapper, since the instrument's command refuses a set smaller than its full
corpus. That wrapper must give the reviewer the same artefact the instrument's per-artefact
review gives it, from the same given design and revision. The two differ only in where on
disk they are written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from instrument_corpus import BASE_NODES, MAGNITUDE_ARTEFACT, SeededFakeReviewer

from physgate.evaluation.inject.corpus import Base, CorpusArtefact
from physgate.evaluation.inject.runner import _review

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integration" / "orchestrator"))
from real_domain_reviewers import wrap_revision  # noqa: E402

WHERE = ("worktree", "graph_root", "trajectory", "repository")


def test_the_driver_s_artefact_is_the_instrument_s(tmp_path: Path) -> None:
    artefact = CorpusArtefact.model_validate_json(json.dumps(MAGNITUDE_ARTEFACT))
    fake = SeededFakeReviewer()
    base = Base(label="a design", nodes=BASE_NODES)
    _review(fake, "claude-sonnet-5", base, artefact.injected, tmp_path / "a", "r1", artefact)
    (instrument,) = fake.seen
    driver = wrap_revision(
        "r1",
        artefact.assigned_role,
        BASE_NODES,
        artefact.injected.nodes,
        (artefact.id, artefact.description),
        tmp_path / "b",
    )
    assert driver.model_dump(exclude=set(WHERE)) == instrument.model_dump(exclude=set(WHERE))
    for field in WHERE:
        assert getattr(driver, field) != getattr(instrument, field)
