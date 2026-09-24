"""A node identifier is checked wherever one is used, not only where one is written.

The graph keeps one file per node and names that file after the node, so an
identifier is a filesystem path in waiting and identifiers come from agents. The
rule was once enforced on the write path alone, which left every read, the
traversal, the history lookup and — worst — recovery building a path from
something nobody had checked.

The rule is enforced at more than one point on purpose, so weakening any single
one leaves the others doing the work. That means each point needs a test only it
can satisfy, or a mutation of it passes while the guard does nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import node

from physgate.state.exceptions import CorruptRecordError, MalformedNodeIdError
from physgate.state.store import Store

ESCAPING = ["../../secrets", "/etc/hosts", "a/b", "..", "electrical.motor/../.."]
ILLEGAL_WITHOUT_ESCAPING = ["NoDots", "Electrical.Motor", "has space.x", "", "electrical..motor"]


# --- the public entry points -------------------------------------------------


@pytest.mark.parametrize("bad", [*ESCAPING, *ILLEGAL_WITHOUT_ESCAPING])
def test_a_read_refuses_an_illegal_identifier(bad: str, store: Store) -> None:
    with pytest.raises(MalformedNodeIdError):
        store.read_node(bad)


@pytest.mark.parametrize("bad", ESCAPING)
def test_a_traversal_refuses_an_illegal_identifier(bad: str, store: Store) -> None:
    with pytest.raises(MalformedNodeIdError):
        store.traverse_constrains(bad)


@pytest.mark.parametrize("bad", ESCAPING)
def test_a_history_lookup_refuses_an_illegal_identifier(bad: str, store: Store) -> None:
    with pytest.raises(MalformedNodeIdError):
        store.history(bad)


def test_a_read_of_a_planted_file_outside_the_graph_is_refused(tmp_path: Path) -> None:
    """The escape is only interesting if the target exists, so one is planted."""
    root = tmp_path / "graph"
    store = Store(root)
    (tmp_path / "planted.json").write_text(json.dumps({"payload": {"id": "planted"}}))

    with pytest.raises(MalformedNodeIdError):
        store.read_node("../planted")

    store.close()


# --- the one function that builds a path -------------------------------------


@pytest.mark.parametrize("bad", ILLEGAL_WITHOUT_ESCAPING)
def test_the_path_builder_refuses_an_illegal_identifier(bad: str, store: Store) -> None:
    """The pattern rule, with the containment check unable to answer for it.

    These identifiers are illegal and do not escape the directory, so the
    containment check would pass every one. That is why they are the ones used
    here: what refuses them is the pattern, and nothing else.
    """
    with pytest.raises(MalformedNodeIdError, match="dotted identifier|not a string"):
        store._node_path(bad)  # noqa: SLF001 - the chokepoint is the subject


def test_the_path_builder_refuses_a_path_that_escapes_the_graph_directory(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The containment check, with the pattern rule unable to answer for it.

    It exists to catch a future loosening of the pattern, so it is tested with
    the pattern neutralised — otherwise the pattern answers and the check is
    decoration.
    """
    monkeypatch.setattr("physgate.state.store.validate_node_id", lambda node_id: str(node_id))
    with pytest.raises(MalformedNodeIdError, match="outside the graph directory"):
        store._node_path("../escape")  # noqa: SLF001 - the chokepoint is the subject


# --- recovery, which is the path that had no check at all --------------------


def test_recovery_refuses_a_journal_naming_a_path_outside_the_graph(
    tmp_path: Path,
) -> None:
    """The defect as it was first reported: the write happened on open."""
    root = tmp_path / "graph"
    Store(root).close()
    victim_dir = tmp_path / "victim"
    victim_dir.mkdir()
    victim = victim_dir / "config.json"
    victim.write_text('{"do not":"clobber me"}')

    escaping = node("electrical.motor_left")
    escaping["id"] = "../../victim/config"
    with (root / "journal.jsonl").open("ab") as handle:
        handle.write(
            json.dumps(
                {
                    "rev": 1,
                    "op": "create",
                    "node_id": "../../victim/config",
                    "version": 1,
                    "payload": escaping,
                }
            ).encode()
            + b"\n"
        )

    with pytest.raises(CorruptRecordError) as caught:
        Store(root)

    assert "node_id" in caught.value.context["reason"]
    assert victim.read_text() == '{"do not":"clobber me"}', "the file outside was written"
