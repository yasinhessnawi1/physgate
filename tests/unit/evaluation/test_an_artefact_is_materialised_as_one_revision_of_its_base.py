"""An artefact is made real as the base design and one revision above it, shown neutrally.

The base goes through the real store first and its head is the baseline: the
given design, which owes nothing. The patch is then one change set above it,
as one merged attempt would be. What a reviewer reads is the worktree and a
neutral account of the revision, the same template for every artefact, and it
is refused if it holds an answer: a telltale word, a gate result's field, or
the artefact's own id or description.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from instrument_corpus import (
    BASE_NODES,
    LABEL,
    MAGNITUDE_ARTEFACT,
    PROPAGATION_ARTEFACT,
    write_corpus,
)

from physgate.evaluation.inject.corpus import Base, Patch, load_corpus
from physgate.evaluation.inject.exceptions import BlindnessError, CorpusError
from physgate.evaluation.inject.materialise import materialise, require_blind
from physgate.state.store import journal_records_after

BASE = Base.model_validate_json(json.dumps({"label": LABEL, "nodes": list(BASE_NODES)}))


def _patch(artefact: dict[str, object], which: str) -> Patch:
    return Patch.model_validate_json(json.dumps(artefact[which]))


def test_the_base_is_the_baseline_and_the_patch_one_revision_above_it(tmp_path: Path) -> None:
    made = materialise(BASE, _patch(PROPAGATION_ARTEFACT, "clean"), tmp_path / "a")
    lines = journal_records_after(made.graph_root, 0)
    assert made.baseline == 3
    assert made.revisions == (4, 5)
    assert [line.node_id for line in lines] == [
        "electrical.driver",
        "electrical.motor_left",
        "electrical.imu",
        "electrical.motor_left",
        "electrical.driver",
    ]
    assert lines[3].payload["quantities"]["stall_current"]["value"] == 2.6
    assert re.fullmatch(r"[0-9a-f]{40}", made.commit)
    assert made.graph_root == made.worktree / "design"


def test_with_no_patch_the_base_is_the_one_revision_over_nothing(tmp_path: Path) -> None:
    made = materialise(BASE, None, tmp_path / "a")
    assert (made.baseline, made.revisions) == (0, (1, 2, 3))


def test_the_same_patch_gives_the_same_commit_and_files(tmp_path: Path) -> None:
    patch = _patch(MAGNITUDE_ARTEFACT, "injected")
    one, two = materialise(BASE, patch, tmp_path / "1"), materialise(BASE, patch, tmp_path / "2")
    assert one.commit == two.commit
    assert one.trajectory.read_bytes() == two.trajectory.read_bytes()


def test_the_account_of_the_revision_is_one_template_naming_only_the_nodes(tmp_path: Path) -> None:
    made = [
        materialise(BASE, _patch(a, "injected"), tmp_path / str(a["id"]))
        for a in (MAGNITUDE_ARTEFACT, PROPAGATION_ARTEFACT)
    ]
    texts = [m.trajectory.read_text() for m in made]
    heads = [t.split("\n## ")[0] for t in texts]
    assert heads[0] == heads[1]
    assert "## electrical.imu" in texts[0]
    assert "## electrical.motor_left" in texts[1] and "## electrical.driver" not in texts[1]
    for text in texts:
        assert not re.search(r"magnitude|propagation|m1|p1|inject|clean", text)


def test_a_store_refusal_or_a_used_directory_stops_the_artefact(tmp_path: Path) -> None:
    other_owner = {**BASE_NODES[2], "owner_role": "control"}
    with pytest.raises(CorpusError, match="refused"):
        materialise(BASE, Patch(nodes=(other_owner,)), tmp_path / "a")
    (tmp_path / "b").mkdir()
    with pytest.raises(CorpusError, match="does not exist yet"):
        materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "clean"), tmp_path / "b")


def test_input_that_tells_nothing_passes(tmp_path: Path) -> None:
    corpus = load_corpus(write_corpus(tmp_path / "c"))
    for n, artefact in enumerate(corpus.artefacts):
        made = materialise(corpus.base, artefact.injected, tmp_path / f"x{n}")
        require_blind(made, (artefact.id, artefact.description))


@pytest.mark.parametrize(
    ("where", "text", "found"),
    [
        ("trajectory", '{"expected_check": "magnitude"}', "expected_check"),
        ("trajectory", '{"verdict": "fail"}', "verdict"),
        ("trajectory", "an injected error", "inject"),
        ("worktree", "see m1 for the answer", "m1"),
        (
            "worktree",
            "the IMU is sampled at 50 kHz, above the fastest rate its register sets",
            "IMU",
        ),
    ],
)
def test_input_that_tells_is_refused(tmp_path: Path, where: str, text: str, found: str) -> None:
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "a")
    target = made.trajectory if where == "trajectory" else made.worktree / "notes.md"
    target.write_text(target.read_text() + text if target.exists() else text)
    with pytest.raises(BlindnessError) as caught:
        require_blind(made, ("m1", str(MAGNITUDE_ARTEFACT["description"])))
    assert found in caught.value.context["found"]


def test_a_path_named_for_the_artefact_is_refused(tmp_path: Path) -> None:
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "m1")
    with pytest.raises(BlindnessError, match="paths"):
        require_blind(made, ("m1",))


def test_an_id_inside_a_digest_is_not_found(tmp_path: Path) -> None:
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "a")
    (made.worktree / "notes.md").write_text("sha256:3a01f9m1c0")
    require_blind(made, ("a01", "m1c"))
    with pytest.raises(BlindnessError):
        require_blind(made, ("sha256",))
