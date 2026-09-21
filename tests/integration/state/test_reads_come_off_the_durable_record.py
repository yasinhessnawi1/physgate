"""Nothing a read returns comes from a cache of this handle's own writes.

This is the property that made the measured store worth promoting, and it is the
one a refactor is most likely to lose while every other test stays green. The
architecture runs agents as separate processes in separate worktrees and the
orchestrator reads what they committed, so a handle answering from its own write
log would be correct in every test and wrong in production.

Two forms. The first is the criterion as written: a second handle in the same
process. The second is a fresh interpreter, because the rule this exists to serve
is that the property is proven from the durable record and not only from the live
path, and a second handle in one process still shares an address space.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from physgate.state.protocol import canonical_json
from physgate.state.store import Store

pytestmark = pytest.mark.integration

WRITES = 200
DIGEST_SOURCE = """
import hashlib, json, sys
from physgate.state.store import Store
store = Store(sys.argv[1])
ids = sorted(p.stem for p in store.nodes_dir.glob("*.json"))
blob = {
    "head": store.head_revision(),
    "nodes": {i: store.read_node(i) for i in ids},
    "history": {i: store.history(i) for i in ids},
    "diff": [[c.revision, c.node_id, c.version, c.op] for c in store.diff(0)],
    "traverse": {i: store.traverse_constrains(i) for i in ids},
}
store.close()
text = json.dumps(blob, sort_keys=True, separators=(",", ":"))
print(hashlib.sha256(text.encode()).hexdigest())
print(len(ids), blob["head"], len(blob["diff"]))
"""


def digest(store: Store) -> str:
    """Everything the store can be asked, hashed."""
    ids = sorted(p.stem for p in store.nodes_dir.glob("*.json"))
    blob = {
        "head": store.head_revision(),
        "nodes": {i: store.read_node(i) for i in ids},
        "history": {i: store.history(i) for i in ids},
        "diff": [[c.revision, c.node_id, c.version, c.op] for c in store.diff(0)],
        "traverse": {i: store.traverse_constrains(i) for i in ids},
    }
    text = json.dumps(blob, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def node(node_id: str, updated: str, constrains: list[str]) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "component",
        "domain": node_id.split(".")[0],
        "owner_role": node_id.split(".")[0],
        "quantities": {
            "stall_current": {
                "value": 2.4,
                "unit": "A",
                "source": "datasheet",
                "written_by": "sizing",
            }
        },
        "requirements": ["REQ-014"],
        "constrains": constrains,
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": updated,
    }


@pytest.fixture
def populated(tmp_path: Path) -> Path:
    """A store directory with a few hundred writes and some rollbacks through it."""
    root = tmp_path / "graph"
    first = Store(root)
    ids = [f"electrical.node{i:03d}" for i in range(20)]
    for i, node_id in enumerate(ids):
        edges = [ids[(i + 1) % len(ids)], ids[(i + 7) % len(ids)]]
        assert first.write_node(node(node_id, "t0", edges), "electrical").accepted

    for n in range(WRITES):
        node_id = ids[n % len(ids)]
        edges = first.read_node(node_id)["constrains"]
        assert first.write_node(node(node_id, f"t{n + 1}", edges), "electrical").accepted

    first.rollback(ids[0], first.history(ids[0])[1])
    first.rollback(ids[3], first.history(ids[3])[0])

    # A refused write, so the record under test also covers something rejected.
    assert not first.write_node(node(ids[5], "intruder", []), "control").accepted

    first.close()
    return root


def test_a_second_handle_in_the_same_process_reads_back_everything(
    populated: Path,
) -> None:
    """Criterion as written: same process, second handle, identical answers."""
    first = Store(populated)
    second = Store(populated)

    assert first is not second
    assert digest(second) == digest(first)

    node_id = "electrical.node000"
    assert canonical_json(second.read_node(node_id)) == canonical_json(first.read_node(node_id))
    assert second.history(node_id) == first.history(node_id)
    assert second.diff(0) == first.diff(0)
    assert second.head_revision() == first.head_revision()

    first.close()
    second.close()


def test_the_two_handles_share_no_object(populated: Path) -> None:
    """Identical answers would be trivially true if they shared the indexes."""
    first = Store(populated)
    second = Store(populated)

    for name in ("_offsets", "_node_revs", "_head", "_journal"):
        assert getattr(first, name) is not getattr(second, name), name

    first.close()
    second.close()


def test_a_fresh_interpreter_reads_back_everything(populated: Path) -> None:
    """The durable record, proven from a process that shares no memory at all."""
    here = Store(populated)
    expected = digest(here)
    node_count = len(list(here.nodes_dir.glob("*.json")))
    head = here.head_revision()
    here.close()

    result = subprocess.run(
        [sys.executable, "-c", DIGEST_SOURCE, str(populated)],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.split()
    assert lines[0] == expected, result.stderr
    assert int(lines[1]) == node_count
    assert int(lines[2]) == head
    assert node_count == 20
    assert head == WRITES + 20 + 2


def test_the_fresh_interpreter_is_really_a_different_process(populated: Path) -> None:
    """A subprocess that silently failed would make the test above vacuous."""
    result = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        check=True,
    )
    import os

    assert int(result.stdout.strip()) != os.getpid()


def test_deleting_a_node_file_is_repaired_from_the_journal(populated: Path) -> None:
    """The journal is the authority; the files are derived from it."""
    victim = populated / "nodes" / "electrical.node004.json"
    original = victim.read_bytes()
    victim.unlink()

    repaired = Store(populated)
    assert victim.exists()
    assert victim.read_bytes() == original
    repaired.close()


def test_a_corrupted_node_file_is_repaired_from_the_journal(populated: Path) -> None:
    victim = populated / "nodes" / "electrical.node006.json"
    original = victim.read_bytes()
    victim.write_bytes(b"{ this is not json")

    repaired = Store(populated)
    assert victim.read_bytes() == original
    repaired.close()


def test_a_node_file_left_behind_at_an_older_revision_is_brought_forward(
    populated: Path,
) -> None:
    """A kill between the journal sync and the file replace lands here."""
    victim = populated / "nodes" / "electrical.node008.json"
    current = json.loads(victim.read_text())
    stale = {"rev": current["rev"] - 1, "version": 1, "payload": current["payload"]}
    victim.write_text(json.dumps(stale))

    repaired = Store(populated)
    assert json.loads(victim.read_text())["rev"] == current["rev"]
    repaired.close()
