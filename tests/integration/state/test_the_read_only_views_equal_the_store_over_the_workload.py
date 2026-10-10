"""The read-only change list, graph-at-revision and history equal the store's, on the workload.

The seeded workload the store comparison froze is replayed into a store, then read twice: by
the store itself, opened on a copy, and by the read-only readers on the original, which must
not change a byte of it. Five seeds, each with creates, writes, rollbacks and refused writes
(which mint no revision). The revisions compared are drawn from a seeded generator and always
include the edges: zero, one, the head and one before it.
"""

from __future__ import annotations

import copy
import random
import shutil
from collections.abc import Iterator
from pathlib import Path

import generator
import pytest

from physgate.state.store import Store, graph_at, journal_diff, node_history

pytestmark = pytest.mark.integration

SEEDS = (1, 2, 3, 4, 5)


def _replay(root: Path, seed: int) -> None:
    work = generator.build(seed)
    store = Store(root)
    try:
        for op in work.ops:
            if op.kind == "rollback":
                store.rollback(op.node_id, store.history(op.node_id)[op.to_ordinal - 1])
            else:
                store.write_node(copy.deepcopy(op.payload), op.actor_role)  # type: ignore[arg-type]
    finally:
        store.close()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture(params=SEEDS, ids=[f"seed{s}" for s in SEEDS])
def replayed(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[tuple[Path, Store, int]]:
    seed: int = request.param
    original = tmp_path / "graph"
    _replay(original, seed)
    shutil.copytree(original, tmp_path / "copy")
    store = Store(tmp_path / "copy")
    yield original, store, seed
    store.close()


def test_the_read_only_views_are_the_store_s_and_write_nothing(
    replayed: tuple[Path, Store, int],
) -> None:
    original, store, seed = replayed
    head = store.head_revision()
    assert head > 1000, "the workload did not replay"
    ops = {c.op for c in store.diff(0)}
    assert ops == {"create", "write", "rollback"}, ops
    before = _snapshot(original)
    pick = random.Random(seed)

    edges = [0, 1, head - 1, head]
    pairs = [(a, b) for a in edges for b in edges if a <= b]
    for _ in range(40):
        low, high = sorted(pick.sample(range(head + 1), 2))
        pairs.append((low, high))
    for since, until in pairs:
        want = [c for c in store.diff(since) if c.revision <= until]
        assert journal_diff(original, since, until) == want, (since, until)
    assert journal_diff(original, 0) == store.diff(0)

    ids = sorted({c.node_id for c in store.diff(0)})
    for revision in [0, 1, head, *pick.sample(range(head + 1), 8)]:
        at = graph_at(original, revision)
        for node_id in ids:
            earlier = [r for r in store.history(node_id) if r <= revision]
            if not earlier:
                assert node_id not in at
                continue
            assert at[node_id].rev == earlier[-1]
            assert at[node_id].payload == store.payload_at(earlier[-1])
        assert len(at) == sum(1 for n in ids if store.history(n)[0] <= revision)

    for node_id in pick.sample(ids, 15):
        history = node_history(original, node_id)
        assert [line.rev for line in history] == store.history(node_id)
        assert [line.payload for line in history] == [
            store.payload_at(r) for r in store.history(node_id)
        ]

    assert _snapshot(original) == before
