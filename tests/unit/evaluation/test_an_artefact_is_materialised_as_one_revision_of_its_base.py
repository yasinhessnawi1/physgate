"""An artefact is made real as the base design and one revision above it, shown neutrally.

The base goes through the real store first and its head is the baseline: the
given design, which owes nothing. The patch is then one change set above it,
as one merged attempt would be. What a reviewer reads is the worktree and a
neutral account of the revision, the same template for every artefact, and it
is refused if it holds an answer: a telltale word, a gate result's field, or
the artefact's own id or description. The worktree's file names are listed to the
reviewer, so a name is held twice: read with its words split apart, however they
are joined, and to the names the instrument itself writes, so any other is refused.
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
    if where == "trajectory":
        made.trajectory.write_text(made.trajectory.read_text() + text)
    else:
        # A node file the design holds, rewritten, so its content is what is held.
        (made.graph_root / "nodes" / "electrical.driver.json").write_text(json.dumps({"n": text}))
    with pytest.raises(BlindnessError) as caught:
        require_blind(made, ("m1", str(MAGNITUDE_ARTEFACT["description"])))
    assert found in caught.value.context["found"]


@pytest.mark.parametrize(
    ("name", "found"),
    [
        ("notes/planted_bracket.md", "planted"),
        ("injected/readme.md", "inject"),
        ("m1_notes.md", "m1"),
    ],
    # Neutral ids: the temporary directory is named after them, and its path is checked too.
    ids=["a-word", "a-directory", "the-id"],
)
def test_a_listed_file_name_that_tells_is_refused(tmp_path: Path, name: str, found: str) -> None:
    """The packet lists every file by name, so a name is shown as plainly as its content."""
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "a")
    target = made.worktree / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("nothing to see\n")
    with pytest.raises(BlindnessError, match="file name") as caught:
        require_blind(made, ("m1", str(MAGNITUDE_ARTEFACT["description"])))
    assert found in caught.value.context["found"]


def test_a_path_named_for_the_artefact_is_refused(tmp_path: Path) -> None:
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "m1")
    with pytest.raises(BlindnessError, match="paths"):
        require_blind(made, ("m1",))


def test_an_id_inside_a_digest_is_not_found(tmp_path: Path) -> None:
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "a")
    notes = made.graph_root / "nodes" / "electrical.driver.json"
    notes.write_text(json.dumps({"n": "sha256:3a01f9m1c0"}))
    require_blind(made, ("a01", "m1c"))
    with pytest.raises(BlindnessError):
        require_blind(made, ("sha256",))


@pytest.mark.parametrize(
    ("name", "found"),
    [
        ("PlantedBracket.md", "planted"),
        ("CleanTwin.md", "twin"),
        ("design/nodes/mechanical.planted2bracket.json", "planted"),
        ("design/nodes/control.twin4.json", "twin"),
    ],
    ids=["camel-case", "camel-case-2", "a-digit-joins", "a-digit-ends"],
)
def test_a_telling_word_joined_by_case_or_a_digit_is_refused(
    tmp_path: Path, name: str, found: str
) -> None:
    """``PlantedBracket.md`` read whole is one word; split at its case, it says what it is."""
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "a")
    target = made.worktree / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}\n")
    with pytest.raises(BlindnessError, match="file name") as caught:
        require_blind(made, ("m1", str(MAGNITUDE_ARTEFACT["description"])))
    assert found in caught.value.context["found"]


@pytest.mark.parametrize(
    "name",
    [
        "notes.md",
        "README",
        "design/summary.txt",
        "design/nodes/Electrical.Motor.json",
        "design/nodes/electrical.imu.md",
        "design/nodes/sub/electrical.imu.json",
        "design/journal.jsonl.bak",
    ],
)
def test_a_listed_name_the_instrument_does_not_write_is_refused(tmp_path: Path, name: str) -> None:
    """Words cannot all be listed; the names the instrument writes can. Any other is refused."""
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "a")
    target = made.worktree / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}\n")
    with pytest.raises(BlindnessError, match="not one the instrument writes") as caught:
        require_blind(made, ("m1", str(MAGNITUDE_ARTEFACT["description"])))
    assert caught.value.context["file"] == name


#: Node-file names a reviewer could read as an answer, which the word list alone let through.
NEAR_FORMS = [
    "control.twins",
    "control.bugs",
    "control.wrongly_sized",
    "control.seeded_error",
    "control.fault",
    "control.clean_copy",
]


@pytest.mark.parametrize(
    "node_id", [*NEAR_FORMS, "control.gain_schedule", "mechanical.spare_bracket"]
)
def test_a_node_file_the_instrument_did_not_write_is_refused(tmp_path: Path, node_id: str) -> None:
    """A node file is listed only for a node this worktree's design holds, however it is named.

    The last two are neutral names, so only the design's own ids can refuse them.
    """
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "a")
    (made.graph_root / "nodes" / f"{node_id}.json").write_text("{}\n")
    with pytest.raises(BlindnessError, match="file name") as caught:
        require_blind(made, ("m1", str(MAGNITUDE_ARTEFACT["description"])))
    assert caught.value.context["file"] == f"design/nodes/{node_id}.json"


@pytest.mark.parametrize("node_id", NEAR_FORMS)
def test_a_node_the_design_holds_under_a_telling_name_is_refused(
    tmp_path: Path, node_id: str
) -> None:
    """A name is held to near forms of the words too: plurals, and error, fault, seed, clean."""
    named = {**BASE_NODES[2], "id": node_id, "domain": "control", "owner_role": "control"}
    base = Base.model_validate_json(json.dumps({"label": LABEL, "nodes": [*BASE_NODES, named]}))
    made = materialise(base, _patch(MAGNITUDE_ARTEFACT, "injected"), tmp_path / "a")
    with pytest.raises(BlindnessError, match="file name") as caught:
        require_blind(made, ("m1", str(MAGNITUDE_ARTEFACT["description"])))
    assert caught.value.context["file"] == f"design/nodes/{node_id}.json"
    assert caught.value.context.get("found")
