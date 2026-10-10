"""The graph's change list, its state at a revision and a node's history, read without writing.

Opening a store runs recovery, which rewrites node files, so a reader that shows a run's graph
reads the journal alone. Each of these readers is held to the store itself, opened on a copy,
for every revision: the change list to ``Store.diff``, the graph at a revision to
``Store.history`` and ``payload_at``, a node's history to the same two. The change list is also
held to the raw journal lines, parsed here, because the store and the reader share their
selection: a fault in it would agree with itself.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers import node, quantity
from ui_rig import real_runs

from physgate.state.exceptions import CorruptRecordError, MalformedNodeIdError
from physgate.state.store import (
    JOURNAL_NAME,
    RevisionNotFoundError,
    Store,
    graph_at,
    journal_diff,
    node_history,
)


def _small_graph(root: Path) -> Path:
    """Creates, writes, an interface node and a rollback: every op the journal can hold."""
    store = Store(root)
    try:
        writes: list[tuple[dict[str, Any], str]] = [
            (node("electrical.motor_left"), "electrical"),
            (node("iface.electrical.bus", kind="interface", owner_role="electrical"), "electrical"),
            (node("control.loop_gain", owner_role="control"), "control"),
            (
                node("electrical.motor_left", quantities={"stall_current": quantity(2.6)}),
                "electrical",
            ),
            (
                node(
                    "control.loop_gain",
                    owner_role="control",
                    constrains=["electrical.motor_left"],
                ),
                "control",
            ),
            (
                node("electrical.motor_left", quantities={"stall_current": quantity(3.1)}),
                "electrical",
            ),
        ]
        for payload, role in writes:
            assert store.write_node(payload, role).accepted
        store.rollback("electrical.motor_left", store.history("electrical.motor_left")[0])
        assert store.write_node(
            node("electrical.driver", constrains=["electrical.motor_left"]), "electrical"
        ).accepted
    finally:
        store.close()
    return root


@pytest.fixture(scope="module")
def run_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The graph store of a run the real loop made."""
    return real_runs(tmp_path_factory.mktemp("real")) / "run-on" / "store"


@pytest.fixture(params=["small", "run"])
def graph(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    if request.param == "small":
        return _small_graph(tmp_path / "graph")
    copied = tmp_path / "graph"
    source: Path = request.getfixturevalue("run_store")
    shutil.copytree(source, copied, symlinks=True)
    return copied


@pytest.fixture
def on_a_copy(graph: Path, tmp_path: Path) -> Iterator[Store]:
    """The store itself, opened on a copy so the original is never written."""
    copy = tmp_path / "copy"
    shutil.copytree(graph, copy, symlinks=True)
    store = Store(copy)
    yield store
    store.close()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def _raw(root: Path) -> list[dict[str, Any]]:
    """The journal's lines, parsed here and nowhere else."""
    return [json.loads(raw) for raw in (root / JOURNAL_NAME).read_text().splitlines()]


def test_the_change_list_between_any_two_revisions_is_the_store_s_own(
    graph: Path, on_a_copy: Store
) -> None:
    head = on_a_copy.head_revision()
    # The run the real loop made writes three nodes; the small graph writes eight
    # revisions with every op. Fewer than three pairs of revisions would prove nothing.
    assert head >= 3, "a graph this small proves nothing about a change list"
    compared = 0
    for since in range(0, head + 2):
        whole = on_a_copy.diff(since)
        assert journal_diff(graph, since) == whole
        for until in range(0, head + 1):
            assert journal_diff(graph, since, until) == [c for c in whole if c.revision <= until]
            compared += 1
    assert compared == (head + 2) * (head + 1)


def test_the_change_list_is_what_the_journal_holds_line_for_line(graph: Path) -> None:
    lines = _raw(graph)
    head = len(lines)
    for since in range(0, head + 1):
        for until in range(since, head + 1):
            got = [
                (c.revision, c.node_id, c.version, c.op) for c in journal_diff(graph, since, until)
            ]
            want = [
                (e["rev"], e["node_id"], e["version"], e["op"])
                for e in lines
                if since < e["rev"] <= until
            ]
            assert got == want


def test_every_op_the_journal_holds_is_in_the_change_list(tmp_path: Path) -> None:
    graph = _small_graph(tmp_path / "graph")
    assert [c.op for c in journal_diff(graph, 0)] == [
        "create",
        "create",
        "create",
        "write",
        "write",
        "write",
        "rollback",
        "create",
    ]


def test_the_change_list_refuses_what_the_store_refuses(graph: Path, on_a_copy: Store) -> None:
    head = on_a_copy.head_revision()
    with pytest.raises(RevisionNotFoundError):
        on_a_copy.diff(-1)
    with pytest.raises(RevisionNotFoundError):
        journal_diff(graph, -1)
    for until in (-1, head + 1):
        with pytest.raises(RevisionNotFoundError):
            journal_diff(graph, 0, until)
    assert journal_diff(graph, head + 5) == on_a_copy.diff(head + 5) == []


def test_the_graph_at_any_revision_is_the_store_s(graph: Path, on_a_copy: Store) -> None:
    head = on_a_copy.head_revision()
    ids = sorted({c.node_id for c in on_a_copy.diff(0)})
    for revision in range(0, head + 1):
        want: dict[str, tuple[int, dict[str, Any]]] = {}
        for node_id in ids:
            earlier = [r for r in on_a_copy.history(node_id) if r <= revision]
            if earlier:
                want[node_id] = (earlier[-1], on_a_copy.payload_at(earlier[-1]))
        got = graph_at(graph, revision)
        assert list(got) == sorted(want)
        assert {n: (line.rev, line.payload) for n, line in got.items()} == want
    at_head = graph_at(graph, head)
    assert {n: line.payload for n, line in at_head.items()} == {
        n: on_a_copy.read_node(n) for n in ids
    }
    assert graph_at(graph, 0) == {}


def test_the_graph_at_a_revision_the_journal_lacks_is_refused(graph: Path) -> None:
    head = len(_raw(graph))
    for revision in (-1, head + 1):
        with pytest.raises(RevisionNotFoundError):
            graph_at(graph, revision)


def test_a_node_s_history_is_the_store_s(graph: Path, on_a_copy: Store) -> None:
    ids = sorted({c.node_id for c in on_a_copy.diff(0)})
    assert ids
    for node_id in ids:
        history = node_history(graph, node_id)
        assert [line.rev for line in history] == on_a_copy.history(node_id)
        assert [line.payload for line in history] == [
            on_a_copy.payload_at(r) for r in on_a_copy.history(node_id)
        ]
        assert [line.version for line in history] == list(range(1, len(history) + 1))
    assert node_history(graph, "electrical.never_written") == []
    with pytest.raises(MalformedNodeIdError):
        node_history(graph, "../escape")


def test_reading_writes_nothing_and_trusts_no_node_file(graph: Path) -> None:
    some_file = next((graph / "nodes").iterdir())
    some_file.write_text('{"tampered": true}')
    (graph / "nodes" / "stranger.json").write_text("{}")
    before = _snapshot(graph)
    journal_diff(graph, 0)
    graph_at(graph, len(_raw(graph)))
    node_history(graph, _raw(graph)[0]["node_id"])
    assert _snapshot(graph) == before


def test_a_journal_line_the_store_could_not_have_written_is_refused_by_every_reader(
    graph: Path,
) -> None:
    lines = _raw(graph)
    forged = {**lines[0], "rev": len(lines) + 1}  # a second create of a node already seen
    with (graph / JOURNAL_NAME).open("ab") as handle:
        handle.write(json.dumps(forged).encode() + b"\n")
    with pytest.raises(CorruptRecordError):
        journal_diff(graph, 0)
    with pytest.raises(CorruptRecordError):
        graph_at(graph, 0)
    with pytest.raises(CorruptRecordError):
        node_history(graph, lines[0]["node_id"])


def test_an_absent_journal_is_an_empty_graph(tmp_path: Path) -> None:
    assert journal_diff(tmp_path / "absent", 0) == []
    assert graph_at(tmp_path / "absent", 0) == {}
    assert node_history(tmp_path / "absent", "electrical.motor_left") == []
    with pytest.raises(RevisionNotFoundError):
        graph_at(tmp_path / "absent", 1)
