"""Every corpus written before the domain-standard class still loads, byte for byte, as it did.

The fifth class widens what an artefact may be; it must change nothing about a corpus written
before it. Each earlier corpus loads only as its manifest lists it, byte for byte, and its
manifest is the one its experiment froze, pinned here by digest as the tests that first loaded it
pin it. Each loads under the five-class code with the classes and the size it was written with,
and at every size the four classes' completeness rule gives it the verdict the rule gave before
the fifth class existed. The corpora are opened only through the loader.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from physgate.evaluation.inject.corpus import (
    BASE_NAME,
    ERROR_CLASSES,
    MANIFEST_NAME,
    SOURCES_NAME,
    Corpus,
    digest,
    load_corpus,
    require_complete,
)
from physgate.evaluation.inject.exceptions import CorpusError

REPO = Path(__file__).resolve().parents[3]
V1 = "corpora/injected-errors/v1"
V1_FULLSHEET = "corpora/injected-errors/v1-fullsheet"
#: The earlier corpora whose manifests their experiments froze by digest, and each one's size per
#: class: the instrument's committed corpus, R-PG-02's fresh set, and R-PG-02's practice set.
FROZEN = {
    V1: ("41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a", 10),
    "corpora/injected-errors/fresh-v1": (
        "e76a4904e7b42326a85a9a9267973518e6f79b510c8f2b8b3391e8b23d37620c",
        10,
    ),
    "experiments/R-PG-02/practice/corpus-v1": (
        "ddc255ab538f134c2983edfb71d29cbeba3c0dc3dd23cc01df9415120d9ddfb0",
        5,
    ),
}
#: v1 with the complete parts sheet, whose manifest digest no experiment has filled yet: v1's base
#: and artefacts byte for byte (as R-PG-01b writes it), and this sheet.
V1_FULLSHEET_SHEET_SHA256 = "2efbb6a8ab889ceac54d8ebdba15c8530274d8524c9eaf6181d22abf5ccbef90"
#: Every corpus the repository tracked when the fifth class was added, and its size per class.
EARLIER = {**{where: size for where, (_, size) in FROZEN.items()}, V1_FULLSHEET: 10}


@pytest.fixture(scope="module")
def loaded() -> dict[str, Corpus]:
    return {where: load_corpus(REPO / where) for where in EARLIER}


def _tracked_corpora() -> set[str]:
    listed = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z", "--", f"*{MANIFEST_NAME}"],
        capture_output=True,
        check=True,
    ).stdout.decode()
    return {str(Path(p).parent) for p in listed.split("\0") if p}


def test_every_earlier_corpus_is_still_tracked_and_every_tracked_corpus_loads() -> None:
    tracked = _tracked_corpora()
    assert set(EARLIER) <= tracked
    for where in sorted(tracked - set(EARLIER)):  # a corpus written later loads too
        load_corpus(REPO / where)


@pytest.mark.parametrize("where", sorted(FROZEN))
def test_an_earlier_corpus_loads_at_the_manifest_its_experiment_froze(
    loaded: dict[str, Corpus], where: str
) -> None:
    corpus = loaded[where]
    assert corpus.manifest_sha256 == FROZEN[where][0] == digest(REPO / where / MANIFEST_NAME)
    assert hashlib.sha256(corpus.parts_sheet).hexdigest() == corpus.manifest.files[SOURCES_NAME]


def test_the_complete_sheet_s_corpus_is_v1_byte_for_byte_with_its_sheet(
    loaded: dict[str, Corpus],
) -> None:
    def design(corpus: Corpus) -> dict[str, str]:
        files = corpus.manifest.files
        return {p: d for p, d in files.items() if p == BASE_NAME or p.startswith("artefacts/")}

    full, v1 = loaded[V1_FULLSHEET], loaded[V1]
    assert design(full) == design(v1) and len(design(v1)) == 1 + 40
    assert full.manifest.files[SOURCES_NAME] == V1_FULLSHEET_SHEET_SHA256
    assert hashlib.sha256(full.parts_sheet).hexdigest() == V1_FULLSHEET_SHEET_SHA256


@pytest.mark.parametrize("where", sorted(EARLIER))
def test_an_earlier_corpus_holds_the_four_classes_alone_at_its_size(
    loaded: dict[str, Corpus], where: str
) -> None:
    corpus = loaded[where]
    counts = Counter(a.error_class for a in corpus.artefacts)
    assert counts == dict.fromkeys(ERROR_CLASSES, EARLIER[where])
    require_complete(corpus, EARLIER[where])


def _the_rule_before_the_fifth_class(corpus: Corpus, per_class: int) -> None:
    """``require_complete`` as it read before the fifth class, verbatim but for this line."""
    if per_class < 1:
        msg = "a complete corpus has at least one artefact of each class"
        raise CorpusError(msg, per_class=str(per_class))
    counts = {c: sum(a.error_class == c for a in corpus.artefacts) for c in ERROR_CLASSES}
    if any(n != per_class for n in counts.values()):
        msg = f"a complete corpus has {per_class} artefacts of each class"
        raise CorpusError(msg, **{c: str(n) for c, n in counts.items()})
    edges = {(a.edge.source, a.edge.target) for a in corpus.artefacts if a.edge is not None}
    if len(edges) != per_class:
        msg = (
            f"a complete corpus's {per_class} propagation artefacts name {per_class} distinct edges"
        )
        raise CorpusError(msg, distinct=str(len(edges)))
    for artefact in corpus.artefacts:
        if artefact.edge is None:
            continue
        source = artefact.injected.node(artefact.edge.source) or {}
        target = artefact.clean.node(artefact.edge.target) or {}
        if source.get("domain") == target.get("domain"):
            msg = "a propagation artefact's edge joins two domains"
            raise CorpusError(msg, artefact=artefact.id, domain=str(source.get("domain")))


def _verdict(
    rule: Callable[[Corpus, int], None], corpus: Corpus, per_class: int
) -> tuple[str, dict[str, str]] | None:
    try:
        rule(corpus, per_class)
    except CorpusError as exc:
        return str(exc), dict(exc.context)
    return None


@pytest.mark.parametrize("where", sorted(EARLIER))
def test_the_four_classes_rule_gives_an_earlier_corpus_its_old_verdict_at_every_size(
    loaded: dict[str, Corpus], where: str
) -> None:
    corpus = loaded[where]
    for per_class in range(0, 13):
        before = _verdict(_the_rule_before_the_fifth_class, corpus, per_class)
        assert _verdict(require_complete, corpus, per_class) == before, per_class
    assert _verdict(require_complete, corpus, EARLIER[where]) is None
