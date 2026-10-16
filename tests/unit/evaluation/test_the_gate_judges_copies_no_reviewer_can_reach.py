"""The gate judges fresh copies made outside the review root, where no reviewer session reads.

The review root is the scratch directory every reviewer session works under: its
packet, its worktree and its session files. A session left running after its
verdict, or a reviewer that wrote somewhere under that root, must find nothing
there the gate will judge. So every copy the gate reads, of an injected artefact
or of a clean twin, is made outside the review root (and outside the corpus), in
the run's own directory, which the reviewer is never shown and which may not lie
under the root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from instrument_corpus import SeededFakeReviewer, write_corpus

from physgate.evaluation.inject import runner
from physgate.evaluation.inject.corpus import load_corpus
from physgate.evaluation.inject.runner import (
    COPIES_DIRNAME,
    control_id,
    review_id,
    run_instrument,
)
from physgate.gate.graph import ChangeHistory, GraphView
from physgate.orchestrator.protocols import Artefact

SEED = 11


def _inside(path: Path, root: Path) -> bool:
    path, root = path.resolve(), root.resolve()
    return path == root or root in path.parents


def test_every_copy_the_gate_reads_is_outside_the_review_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = load_corpus(write_corpus(tmp_path / "corpus"))
    run_dir, scratch = tmp_path / "out" / "run", tmp_path / "out" / "scratch"
    read: list[Path] = []
    reviewed: list[Path] = []

    class Spied(GraphView):
        @classmethod
        def read(
            cls, root: Path, base_revision: int, history: ChangeHistory | None = None
        ) -> GraphView:
            read.append(Path(root))
            return GraphView.read(root, base_revision, history)

    def reviewing(artefact: Artefact) -> None:
        # Where a reviewer is: its worktree, under the review root, as it judges.
        reviewed.append(Path(artefact.worktree))
        assert _inside(Path(artefact.worktree), scratch)

    monkeypatch.setattr(runner, "GraphView", Spied)
    rows = run_instrument(
        corpus,
        {"electrical": SeededFakeReviewer(before_verdict=reviewing)},
        run_dir=run_dir,
        scratch=scratch,
        run_id="dry-1",
        seed=SEED,
        review_clean_twins=True,
    )
    # Every injected artefact and every clean twin was gated, and every twin reviewed.
    assert len(read) == 2 * len(rows) == 4 and len(reviewed) == 4
    for root in read:
        assert not _inside(root, scratch), root
        assert not _inside(root, corpus.root), root
        assert _inside(root, run_dir / COPIES_DIRNAME), root
        assert root.is_dir()
    # Nothing a reviewer could reach is left under the root: the review copies are gone,
    # and no gate copy was ever made there.
    assert [p.relative_to(scratch) for p in scratch.rglob("*")] == [Path("review")]


def test_writes_under_the_review_root_change_nothing_the_gate_judges(
    tmp_path: Path,
) -> None:
    """A reviewer writes under its root, as a session left running might.

    It writes at every name the gate's copies could take there, and the run gates exactly
    what an untouched run gates.
    """
    corpus = load_corpus(write_corpus(tmp_path / "corpus"))
    names = [review_id(SEED, a.id) for a in corpus.artefacts]
    names += [control_id(SEED, a.id) for a in corpus.artefacts]

    def planter(scratch: Path) -> SeededFakeReviewer:
        def plant(artefact: Artefact) -> None:
            for kind in ("gate", "control", COPIES_DIRNAME):
                for name in names:
                    design = scratch / kind / name / "worktree" / "design"
                    design.mkdir(parents=True, exist_ok=True)
                    (design / "journal.jsonl").write_text("not a journal\n")

        return SeededFakeReviewer(before_verdict=plant)

    gated: dict[str, Any] = {}
    for name in ("untouched", "written"):
        scratch = tmp_path / name / "scratch"
        rows = run_instrument(
            corpus,
            {"electrical": planter(scratch) if name == "written" else SeededFakeReviewer()},
            run_dir=tmp_path / name / "run",
            scratch=scratch,
            run_id="dry-1",
            seed=SEED,
        )
        gated[name] = [(r.gate_verdict, r.gate_blocking, r.control_verdict) for r in rows]
    assert gated["written"] == gated["untouched"]
    assert [v for v, _, _ in gated["written"]] == ["fail", "fail"]
