"""A corpus is fixed by its manifest, and each artefact holds exactly one error of four classes.

The measurement counts errors a reviewer approved and the gate then caught, and
the person who built the gate cannot be the one who chooses them after seeing
which it catches. So the corpus loads only as committed: a byte changed, a file
added or a file removed is a different corpus and is refused. Each artefact is
a clean patch and the same patch with one error, of exactly one of four
classes; a propagation artefact names its one edge, and ten of them name ten
edges. And nothing a reviewer will be shown may say what the corpus is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import node
from instrument_corpus import (
    AUTHOR,
    BASE_NODES,
    IMU,
    LABEL,
    MAGNITUDE_ARTEFACT,
    MOTOR,
    PROPAGATION_ARTEFACT,
    with_quantity,
    write_corpus,
)
from pydantic import ValidationError

from physgate.evaluation.inject.corpus import (
    Corpus,
    CorpusArtefact,
    Manifest,
    digest,
    load_corpus,
    manifest_for,
    require_complete,
    telltales,
    write_manifest,
)
from physgate.evaluation.inject.exceptions import CorpusError


def _artefact(**changes: Any) -> CorpusArtefact:  # noqa: ANN401 - an artefact's own fields
    return CorpusArtefact.model_validate_json(json.dumps({**MAGNITUDE_ARTEFACT, **changes}))


def test_a_corpus_loads_as_its_manifest_lists_it(tmp_path: Path) -> None:
    corpus = load_corpus(write_corpus(tmp_path / "c"))
    assert [a.id for a in corpus.artefacts] == ["m1", "p1"]
    assert corpus.manifest.author_model == AUTHOR
    assert corpus.manifest.label == LABEL
    assert corpus.manifest_sha256 == digest(tmp_path / "c" / "MANIFEST.json")
    assert set(corpus.manifest.files) == {
        "README.md",
        "base.json",
        "artefacts/m1.json",
        "artefacts/p1.json",
    }


@pytest.mark.parametrize("where", ["artefacts/p1.json", "base.json", "README.md"])
def test_one_byte_changed_anywhere_is_another_corpus(tmp_path: Path, where: str) -> None:
    root = write_corpus(tmp_path / "c")
    path = root / where
    path.write_bytes(path.read_bytes().replace(b"e", b"E", 1))
    with pytest.raises(CorpusError) as caught:
        load_corpus(root)
    assert caught.value.context["changed"] == where


def test_a_file_added_or_removed_is_another_corpus(tmp_path: Path) -> None:
    root = write_corpus(tmp_path / "c")
    (root / "artefacts" / "extra.json").write_text("{}")
    with pytest.raises(CorpusError) as caught:
        load_corpus(root)
    assert caught.value.context["unlisted"] == "artefacts/extra.json"
    (root / "artefacts" / "extra.json").unlink()
    (root / "artefacts" / "m1.json").unlink()
    with pytest.raises(CorpusError) as caught:
        load_corpus(root)
    assert caught.value.context["missing"] == "artefacts/m1.json"


def test_a_corpus_without_a_manifest_or_holding_a_link_is_refused(tmp_path: Path) -> None:
    root = write_corpus(tmp_path / "c")
    (root / "notes.md").symlink_to(root / "README.md")
    with pytest.raises(CorpusError, match="files and directories only"):
        load_corpus(root)
    (root / "notes.md").unlink()
    (root / "MANIFEST.json").unlink()
    with pytest.raises(CorpusError, match="no manifest"):
        load_corpus(root)


def test_a_corpus_holds_its_base_its_artefacts_and_documentation_only(tmp_path: Path) -> None:
    root = write_corpus(tmp_path / "c")
    (root / "answers.txt").write_text("m1: magnitude\n")
    write_manifest(root, manifest_for(root, label=LABEL, author_model=AUTHOR))
    with pytest.raises(CorpusError, match="nothing else") as caught:
        load_corpus(root)
    assert caught.value.context["path"] == "answers.txt"


def test_an_artefact_is_named_for_its_id(tmp_path: Path) -> None:
    root = write_corpus(tmp_path / "c")
    (root / "artefacts" / "m1.json").rename(root / "artefacts" / "m2.json")
    write_manifest(root, manifest_for(root, label=LABEL, author_model=AUTHOR))
    with pytest.raises(CorpusError, match="named for its id"):
        load_corpus(root)


def test_the_manifest_names_a_full_model_string_for_its_author() -> None:
    with pytest.raises(ValidationError):
        Manifest(format=1, label="x", author_model="sonnet", files={})


@pytest.mark.parametrize("error_class", ["units", "arithmetic", "", "Unit"])
def test_there_are_exactly_four_classes(error_class: str) -> None:
    with pytest.raises(ValidationError):
        _artefact(error_class=error_class)


def test_an_artefact_whose_two_patches_are_the_same_holds_no_error() -> None:
    with pytest.raises(ValidationError, match="there is no error in it"):
        _artefact(injected=MAGNITUDE_ARTEFACT["clean"])


def test_a_propagation_artefact_names_its_edge_and_no_other_artefact_names_one() -> None:
    with pytest.raises(ValidationError, match="names its edge"):
        _artefact(edge={"source": "electrical.motor_left", "target": "electrical.driver"})
    with pytest.raises(ValidationError, match="names its edge"):
        CorpusArtefact.model_validate_json(json.dumps({**PROPAGATION_ARTEFACT, "edge": None}))


@pytest.mark.parametrize(
    ("edge", "reason"),
    [
        ({"source": "electrical.imu", "target": "electrical.driver"}, "written by both patches"),
        ({"source": "electrical.motor_left", "target": "electrical.imu"}, "constrains its target"),
        ({"source": "electrical.driver", "target": "electrical.driver"}, "two different nodes"),
    ],
)
def test_a_propagation_artefact_s_edge_is_one_the_change_left_behind(
    edge: dict[str, str], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        CorpusArtefact.model_validate_json(json.dumps({**PROPAGATION_ARTEFACT, "edge": edge}))


def test_the_clean_twin_of_a_propagation_artefact_reaches_the_target() -> None:
    clean = {"nodes": [with_quantity(MOTOR, "stall_current", 2.5, "A")]}
    with pytest.raises(ValidationError, match="reaches the edge's target"):
        CorpusArtefact.model_validate_json(json.dumps({**PROPAGATION_ARTEFACT, "clean": clean}))


def test_every_node_of_a_patch_is_a_whole_node() -> None:
    bare = {k: v for k, v in IMU.items() if k != "geometry_hash"}
    with pytest.raises(ValidationError, match="not a whole node"):
        _artefact(injected={"nodes": [bare]})
    unitless = with_quantity(IMU, "sample_rate", 900, "Hz")
    del unitless["quantities"]["sample_rate"]["unit"]
    with pytest.raises(ValidationError, match="not a whole node"):
        _artefact(injected={"nodes": [unitless]})


@pytest.mark.parametrize(
    ("where", "text"),
    [
        ("source", "datasheet, with an injected error"),
        ("source", "a deliberate mistake"),
        ("source", "the magnitude-error artefact"),
        ("source", "see the corpus"),
        ("model", "the wrong IMU"),
        ("key", "sample_rate_injected"),
    ],
)
def test_nothing_in_a_node_says_what_the_corpus_is(where: str, text: str) -> None:
    payload = with_quantity(IMU, "sample_rate", 50_000, "Hz")
    if where == "source":
        payload["quantities"]["sample_rate"]["source"] = text
    elif where == "key":
        payload["quantities"] = {text: payload["quantities"]["sample_rate"]}
    else:
        payload[where] = text
    with pytest.raises(ValidationError, match="give the corpus away"):
        _artefact(injected={"nodes": [payload]})


@pytest.mark.parametrize(
    "text",
    ["the plant's pole", "power budget", "gate driver input", "units of torque", "Pololu 2.1"],
)
def test_the_words_of_the_domain_are_not_telltales(text: str) -> None:
    assert telltales(text) == []


def test_a_patch_may_not_rewrite_an_interface_or_give_a_node_another_owner(tmp_path: Path) -> None:
    interface = node("cross.chassis_mount", kind="interface", domain="cross")
    owned = {**IMU, "owner_role": "control", "quantities": {}}
    for base, patch, reason in (
        (
            (*BASE_NODES, interface),
            {**interface, "geometry_hash": "sha256:" + "1" * 64},
            "interface",
        ),
        (BASE_NODES, owned, "another owner"),
    ):
        artefact = {**MAGNITUDE_ARTEFACT, "injected": {"nodes": [patch]}}
        root = write_corpus(tmp_path / reason, artefacts=(artefact,), base_nodes=base)
        with pytest.raises(CorpusError, match=reason):
            load_corpus(root)


def _forty(distinct_edges: int) -> Corpus:
    artefacts = []
    for n in range(40):
        error_class = ("unit", "magnitude", "equilibrium", "propagation")[n // 10]
        source = node(
            f"electrical.m{n % distinct_edges}",
            quantities={"stall_current": (2, "A")},
            constrains=[f"electrical.d{n % distinct_edges}"],
        )
        target = node(f"electrical.d{n % distinct_edges}", quantities={"current_limit": (3, "A")})
        changed = with_quantity(source, "stall_current", 2 + n / 100, "A")
        edge = {"source": source["id"], "target": target["id"]}
        artefacts.append(
            CorpusArtefact.model_validate_json(
                json.dumps(
                    {
                        **MAGNITUDE_ARTEFACT,
                        "id": f"a{n}",
                        "error_class": error_class,
                        "edge": edge if error_class == "propagation" else None,
                        "clean": {"nodes": [changed, target]},
                        "injected": {"nodes": [changed]},
                    }
                )
            )
        )
    manifest = Manifest(format=1, label=LABEL, author_model=AUTHOR, files={})
    return Corpus(Path("."), manifest, "0" * 64, None, tuple(artefacts))  # type: ignore[arg-type]


def test_a_complete_corpus_has_ten_of_each_class_and_ten_distinct_edges(tmp_path: Path) -> None:
    require_complete(_forty(distinct_edges=10))
    with pytest.raises(CorpusError, match="10 distinct edges") as caught:
        require_complete(_forty(distinct_edges=9))
    assert caught.value.context["distinct"] == "9"
    with pytest.raises(CorpusError, match="10 artefacts of each class") as caught:
        require_complete(load_corpus(write_corpus(tmp_path / "c")))
    assert caught.value.context == {
        "unit": "0",
        "magnitude": "1",
        "equilibrium": "0",
        "propagation": "1",
    }
