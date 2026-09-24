"""A node file is what the journal says it is, and no file exists that it has not named.

Four places in this package say the journal is the authority and the node files
are derived from it. For three rounds that was true of the journal and not of the
files: recovery decided a file matched by reading the revision number written
*inside the file*, which is under the control of whatever wrote it. An agent
editing a node in its own worktree and leaving ``rev`` alone produced a graph that
served a value the journal had never recorded, in no change list, invisible to the
check whose docstring names a file edited directly in a worktree as the thing it
covers.

The second half is the file nobody journalled at all, which was never examined:
readable, with an empty history, in no change list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers import node

from physgate.state.divergence import divergence
from physgate.state.exceptions import CorruptRecordError
from physgate.state.store import Store


def node_file(root: Path, node_id: str) -> Path:
    return root / "nodes" / f"{node_id}.json"


def tamper(root: Path, node_id: str, mutate: Any) -> None:
    """Edit a node file in place, leaving its revision number alone."""
    path = node_file(root, node_id)
    on_disk = json.loads(path.read_text())
    before = on_disk["rev"]
    mutate(on_disk)
    path.write_text(json.dumps(on_disk, sort_keys=True, separators=(",", ":")))
    assert json.loads(path.read_text())["rev"] == before, "the fixture must leave rev alone"


@pytest.fixture
def two_revisions(tmp_path: Path) -> Path:
    root = tmp_path / "graph"
    store = Store(root)
    for i in range(2):
        assert store.write_node(
            node("mechanical.gearbox", owner_role="mechanical", updated=f"t{i}"), "mechanical"
        ).accepted
    store.close()
    return root


# --- a file edited in place, with its revision left alone ---------------------


def test_a_tampered_quantity_is_repaired_from_the_journal(two_revisions: Path) -> None:
    tamper(
        two_revisions,
        "mechanical.gearbox",
        lambda d: d["payload"]["quantities"]["stall_current"].__setitem__("value", 99999.0),
    )

    reopened = Store(two_revisions)

    assert reopened.read_node("mechanical.gearbox")["quantities"]["stall_current"]["value"] == 2.4
    assert reopened.repaired_node_files == 1
    reopened.close()


def test_the_tamper_cannot_be_read_back_from_the_file_either(two_revisions: Path) -> None:
    """Repairing the read is not enough if the file still holds the tampered value."""
    tamper(
        two_revisions,
        "mechanical.gearbox",
        lambda d: d["payload"]["quantities"]["stall_current"].__setitem__("value", 99999.0),
    )

    Store(two_revisions).close()

    on_disk = json.loads(node_file(two_revisions, "mechanical.gearbox").read_text())
    assert on_disk["payload"]["quantities"]["stall_current"]["value"] == 2.4


def test_the_tamper_does_not_reach_the_divergence_check(two_revisions: Path) -> None:
    """The channel the check's own docstring claims to cover."""
    tamper(
        two_revisions,
        "mechanical.gearbox",
        lambda d: d["payload"].__setitem__("owner_role", "electrical"),
    )

    reopened = Store(two_revisions)
    assert reopened.read_node("mechanical.gearbox")["owner_role"] == "mechanical"
    assert [d.owner_role for d in divergence(reopened, reopened.diff(0), "mechanical")] == []
    reopened.close()


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        (
            "a changed quantity",
            lambda d: d["payload"]["quantities"]["stall_current"].__setitem__("value", 1.0),
        ),
        ("a changed owner", lambda d: d["payload"].__setitem__("owner_role", "control")),
        ("a changed identifier", lambda d: d["payload"].__setitem__("id", "mechanical.other")),
        ("an added constraint", lambda d: d["payload"]["constrains"].append("control.loop")),
        ("a changed version", lambda d: d.__setitem__("version", 99)),
        ("an added top-level key", lambda d: d.__setitem__("surprise", 1)),
    ],
)
def test_any_difference_from_the_journal_is_repaired(
    label: str, mutate: Any, two_revisions: Path
) -> None:
    """Not only a wrong revision: any difference at all."""
    expected = node_file(two_revisions, "mechanical.gearbox").read_text()
    tamper(two_revisions, "mechanical.gearbox", mutate)
    assert node_file(two_revisions, "mechanical.gearbox").read_text() != expected, label

    reopened = Store(two_revisions)
    assert reopened.repaired_node_files == 1, label
    assert node_file(two_revisions, "mechanical.gearbox").read_text() == expected, label
    reopened.close()


def test_an_untouched_graph_repairs_nothing(two_revisions: Path) -> None:
    """The comparison must not rewrite every file on every open."""
    reopened = Store(two_revisions)
    assert reopened.repaired_node_files == 0
    reopened.close()


# --- a file the journal never named -------------------------------------------


def plant(root: Path, node_id: str) -> Path:
    path = node_file(root, node_id)
    path.write_text(
        json.dumps(
            {"rev": 99, "version": 1, "payload": node(node_id, owner_role="mechanical")},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return path


def test_a_planted_node_file_is_refused(two_revisions: Path) -> None:
    plant(two_revisions, "mechanical.planted")

    with pytest.raises(CorruptRecordError) as caught:
        Store(two_revisions)
    assert caught.value.context["node_id"] == "mechanical.planted"
    assert caught.value.context["count"] == "1"


def test_the_way_through_moves_it_aside_rather_than_serving_it(
    two_revisions: Path,
) -> None:
    planted = plant(two_revisions, "mechanical.planted")

    opened = Store(two_revisions, on_corrupt="truncate")

    assert opened.quarantined_node_files == ("mechanical.planted",)
    assert not planted.exists()
    assert planted.with_suffix(".json.orphan").exists(), "moved aside, not deleted"
    opened.close()


def test_a_quarantined_file_is_not_found_again_on_the_next_open(
    two_revisions: Path,
) -> None:
    plant(two_revisions, "mechanical.planted")
    Store(two_revisions, on_corrupt="truncate").close()

    reopened = Store(two_revisions)
    assert reopened.quarantined_node_files == ()
    reopened.close()


def test_every_planted_file_is_counted_not_only_the_first(two_revisions: Path) -> None:
    for name in ("mechanical.planted", "control.planted", "electrical.planted"):
        plant(two_revisions, name)

    with pytest.raises(CorruptRecordError) as caught:
        Store(two_revisions)
    assert caught.value.context["count"] == "3"


def test_a_temporary_file_left_by_a_killed_write_is_not_an_orphan(
    two_revisions: Path,
) -> None:
    """The store's own atomic write leaves one of these behind if it is killed."""
    (two_revisions / "nodes" / "mechanical.gearbox.json.tmp").write_text("{}")

    reopened = Store(two_revisions)
    assert reopened.quarantined_node_files == ()
    reopened.close()
