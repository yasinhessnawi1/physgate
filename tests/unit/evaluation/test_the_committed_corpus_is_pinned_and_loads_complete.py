"""The committed injected-error corpus is pinned to its manifest and loads complete.

Unlike the synthetic fixtures the rest of this package tests against
(``instrument_corpus.py``), this is the real, committed corpus the
instrument runs on: forty artefacts, ten of each class, ten distinct
propagation edges. A byte changed anywhere under it, its manifest included,
is a different corpus and this test catches that before anything else does.
"""

from __future__ import annotations

from pathlib import Path

from physgate.evaluation.inject.corpus import digest, load_corpus, require_complete

ROOT = Path(__file__).resolve().parents[3] / "corpora" / "injected-errors" / "v1"
#: The manifest's own digest, pinned here so a change to any file under the
#: corpus (including the manifest itself) is caught by this test failing,
#: not by a silent load.
MANIFEST_SHA256 = "41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a"


def test_the_committed_manifest_is_the_pinned_one() -> None:
    assert digest(ROOT / "MANIFEST.json") == MANIFEST_SHA256


def test_the_committed_corpus_loads_and_is_complete() -> None:
    corpus = load_corpus(ROOT)
    assert corpus.manifest_sha256 == MANIFEST_SHA256
    assert len(corpus.artefacts) == 40
    require_complete(corpus)
