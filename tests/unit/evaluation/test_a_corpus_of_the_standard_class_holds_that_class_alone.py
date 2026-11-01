"""The domain-standard class is a fifth class, and a corpus of it holds that class alone.

An artefact of the ``standard`` class breaks a rule its domain's standards file states: a rating
exceeded, a derating not applied, a margin below the standard's minimum, a timing or rate budget
overrun. It is written as any artefact of the first four classes is (a clean patch and the same
patch with one error, the check expected nearest to it, a description) and, like every class but
propagation, it names no edge. Such a corpus is complete with ``per_class`` artefacts of that
class and nothing else. The four classes' rule is untouched: a corpus with no artefact of the
fifth class is held to it exactly as before, and a corpus that mixes the fifth with the four is
refused, since no rule counts it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from instrument_corpus import (
    AUTHOR,
    IMU,
    LABEL,
    MAGNITUDE_ARTEFACT,
    SeededFakeReviewer,
    node,
    with_quantity,
    write_corpus,
)
from pydantic import ValidationError

from physgate.cli import main
from physgate.evaluation.inject.corpus import (
    ERROR_CLASSES,
    PER_CLASS,
    Corpus,
    CorpusArtefact,
    Manifest,
    load_corpus,
    require_complete,
)
from physgate.evaluation.inject.exceptions import CorpusError
from physgate.evaluation.inject.runner import CONFIG_NAME, RESULTS_NAME
from physgate.orchestrator.cli import Registrations


def standard(n: int) -> dict[str, Any]:
    """The ``n``-th artefact of the class: the IMU sampled above the rate its datasheet allows."""
    return {
        **MAGNITUDE_ARTEFACT,
        "id": f"s{n:02d}",
        "error_class": "standard",
        "expected_check": "magnitude",
        "description": "the IMU is sampled above the output data rate its standard allows",
        "clean": {"nodes": [with_quantity(IMU, "sample_rate", 800 + n, "Hz")]},
        "injected": {"nodes": [with_quantity(IMU, "sample_rate", 50_000 + n, "Hz")]},
    }


def four_class(per_class: int) -> list[dict[str, Any]]:
    """``per_class`` artefacts of each of the four classes, each propagation one its own edge."""
    out = []
    for n in range(4 * per_class):
        error_class = ERROR_CLASSES[n // per_class]
        source = node(
            f"electrical.m{n}",
            quantities={"stall_current": (2, "A")},
            constrains=[f"mechanical.d{n}"],
        )
        target = node(
            f"mechanical.d{n}", domain="mechanical", quantities={"current_limit": (3, "A")}
        )
        changed = with_quantity(source, "stall_current", 2 + n / 100, "A")
        out.append(
            {
                **MAGNITUDE_ARTEFACT,
                "id": f"a{n}",
                "error_class": error_class,
                "edge": (
                    {"source": source["id"], "target": target["id"]}
                    if error_class == "propagation"
                    else None
                ),
                "clean": {"nodes": [changed, target]},
                "injected": {"nodes": [changed]},
            }
        )
    return out


def corpus_of(artefacts: list[dict[str, Any]]) -> Corpus:
    """A corpus held in memory, for the completeness rule alone."""
    return Corpus(
        root=Path("."),
        manifest=Manifest(format=1, label=LABEL, author_model=AUTHOR, files={}),
        manifest_sha256="0" * 64,
        base=None,  # type: ignore[arg-type]
        sources=None,  # type: ignore[arg-type]
        artefacts=tuple(CorpusArtefact.model_validate_json(json.dumps(a)) for a in artefacts),
        parts_sheet=b"",
    )


def test_standard_is_a_fifth_class_and_not_one_of_risk_row_1_s_four() -> None:
    from physgate.evaluation.inject.corpus import STANDARD

    artefact = CorpusArtefact.model_validate_json(json.dumps(standard(1)))
    assert artefact.error_class == STANDARD == "standard"
    assert STANDARD not in ERROR_CLASSES
    assert ERROR_CLASSES == ("unit", "magnitude", "equilibrium", "propagation")


@pytest.mark.parametrize("spelling", ["standards", "Standard", "domain-standard", "standard "])
def test_the_class_is_spelt_exactly(spelling: str) -> None:
    with pytest.raises(ValidationError):
        CorpusArtefact.model_validate_json(json.dumps({**standard(1), "error_class": spelling}))


def test_an_artefact_of_the_class_names_no_edge() -> None:
    edge = {"source": "electrical.imu", "target": "electrical.driver"}
    with pytest.raises(ValidationError, match="no other artefact names one"):
        CorpusArtefact.model_validate_json(json.dumps({**standard(1), "edge": edge}))


def test_an_artefact_of_the_class_holds_an_error() -> None:
    same = standard(1)["clean"]
    with pytest.raises(ValidationError, match="there is no error in it"):
        CorpusArtefact.model_validate_json(json.dumps({**standard(1), "injected": same}))


def test_a_corpus_of_the_class_loads_as_its_manifest_lists_it(tmp_path: Path) -> None:
    corpus = load_corpus(write_corpus(tmp_path / "c", artefacts=tuple(map(standard, range(1, 11)))))
    assert [a.error_class for a in corpus.artefacts] == ["standard"] * 10
    assert all(a.edge is None for a in corpus.artefacts)


def test_a_corpus_of_the_class_alone_is_complete_with_its_size_of_that_class() -> None:
    ten = corpus_of([standard(n) for n in range(1, 11)])
    require_complete(ten, 10)
    require_complete(ten)  # the default size, risk row 1's ten
    assert PER_CLASS == 10
    require_complete(corpus_of([standard(n) for n in range(1, 6)]), 5)


@pytest.mark.parametrize(("count", "per_class"), [(9, 10), (11, 10), (10, 5), (1, 2)])
def test_a_corpus_of_the_class_of_another_size_is_refused(count: int, per_class: int) -> None:
    corpus = corpus_of([standard(n) for n in range(1, count + 1)])
    with pytest.raises(CorpusError, match=f"{per_class} artefacts of the standard class") as caught:
        require_complete(corpus, per_class)
    assert caught.value.context == {"standard": str(count)}


def test_a_corpus_that_mixes_the_class_with_the_four_is_refused() -> None:
    # Ten of each of the four and ten edges: complete by the four classes' own count, which does
    # not see the fifth, so the fifth is what refuses it.
    mixed = corpus_of([*four_class(10), standard(1)])
    with pytest.raises(CorpusError, match="holds that class alone") as caught:
        require_complete(mixed, 10)
    assert caught.value.context == {"standard": "1", "others": "40"}
    nine_and_one = corpus_of([*(standard(n) for n in range(1, 10)), MAGNITUDE_ARTEFACT])
    with pytest.raises(CorpusError, match="holds that class alone") as caught:
        require_complete(nine_and_one, 10)
    assert caught.value.context == {"standard": "9", "others": "1"}


def test_a_corpus_of_the_four_classes_is_held_to_their_rule_as_before() -> None:
    require_complete(corpus_of(four_class(10)), 10)
    require_complete(corpus_of(four_class(5)), 5)
    with pytest.raises(CorpusError, match="5 artefacts of each class") as caught:
        require_complete(corpus_of(four_class(5)[:-1]), 5)
    assert caught.value.context == {
        "unit": "5",
        "magnitude": "5",
        "equilibrium": "5",
        "propagation": "4",
    }


def test_a_size_below_one_is_refused_for_the_class_as_for_the_four() -> None:
    for artefacts in ([standard(1)], four_class(1)):
        with pytest.raises(CorpusError, match="at least one artefact of each class"):
            require_complete(corpus_of(artefacts), 0)


def _argv(corpus: Path, tmp_path: Path, per_class: int) -> list[str]:
    return [
        "inject",
        "--corpus",
        str(corpus),
        "--run-dir",
        str(tmp_path / "run"),
        "--scratch",
        str(tmp_path / "s"),
        "--run-id",
        "x",
        "--seed",
        "1",
        "--per-class",
        str(per_class),
        "--review-clean-twins",
    ]


def test_the_command_runs_the_class_alone_and_records_each_row_under_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = write_corpus(tmp_path / "c", artefacts=(standard(1), standard(2)))
    registered = Registrations(reviewers={"electrical": SeededFakeReviewer()})
    assert main(_argv(corpus, tmp_path, 2), registered) == 0
    capsys.readouterr()
    rows = [json.loads(x) for x in (tmp_path / "run" / RESULTS_NAME).read_text().splitlines()]
    assert [(r["artefact"], r["error_class"]) for r in rows] == [
        ("s01", "standard"),
        ("s02", "standard"),
    ]
    assert json.loads((tmp_path / "run" / CONFIG_NAME).read_text())["per_class"] == 2


def test_the_command_refuses_the_class_mixed_with_the_four(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = write_corpus(tmp_path / "c", artefacts=(standard(1), MAGNITUDE_ARTEFACT))
    registered = Registrations(reviewers={"electrical": SeededFakeReviewer()})
    assert main(_argv(corpus, tmp_path, 1), registered) == 2
    error = json.loads(capsys.readouterr().err)
    assert "holds that class alone" in error["error"]
    assert (error["standard"], error["others"]) == ("1", "1")
    assert not (tmp_path / "run").exists()
