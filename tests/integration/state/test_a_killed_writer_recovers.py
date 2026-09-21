"""A process killed mid-write leaves a store that opens, recovers and loses nothing.

This is the architecture's requirement that killing a session mid-task loses no
project state, applied to the two files that hold it. A child replays a seeded
workload, acknowledging each operation durably; the parent kills it; a fresh
process opens the store and is judged against everything that was acknowledged.

The consistency definition is the one the pre-registered store comparison used,
kept word for word so the result is comparable with the published five-of-five:

1. the store opens without raising;
2. every acknowledged write is readable at the revision it was acknowledged at
   or a later one, and no acknowledged write is lost;
3. no node holds a payload that was never written — each node's current payload
   is one of the payloads the generator produced for it;
4. every version chain is intact: versions 1..k, no gaps, no duplicates, one head.

**The kill is anchored to acknowledgements, not to a clock, and that is a
correction.** The experiment's runner waited for a fixed number of
acknowledgements and then slept a seeded fraction of a second. Both of its
published runs killed every seed mid-write, and their five-of-five is sound. But
the anchor decays: re-running that procedure on today's faster machine, two seeds
in five finished the entire workload before the kill landed, and a crash test
that does not crash reports five of five while proving nothing. The observable
that would have caught it — whether the child was still alive — was recorded by
the experiment and never asserted on. It is asserted here, per seed.
"""

from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

import generator
import pytest
from crash_child import Acknowledgement

from physgate.state.protocol import canonical_json
from physgate.state.store import Store
from physgate.state.task_ledger import TaskLedger

pytestmark = pytest.mark.integration

HERE = Path(__file__).resolve().parent
SEEDS = (1, 2, 3, 4, 5)
TOTAL_OPS = 1230
POLL_SECONDS = 0.001


def acknowledgements(path: Path) -> list[Acknowledgement]:
    """Every complete acknowledgement line. A torn final line is not one."""
    if not path.exists():
        return []
    out: list[Acknowledgement] = []
    for raw in path.read_bytes().splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break
        out.append(Acknowledgement.model_validate_json(raw))
    return out


def kill_target(seed: int) -> int:
    """A seeded acknowledgement count, comfortably inside the workload.

    Seeded so the run is reproducible, and expressed in operations rather than
    seconds so it does not move when the machine does.
    """
    return random.Random(10_000 + seed).randint(250, 900)


def run_until_killed(seed: int, root: Path) -> tuple[bool, int, int]:
    """Replay ``seed`` in a child and kill it at its acknowledgement target.

    Returns:
        Whether the child was still running when the signal was sent, the target,
        and how many acknowledgements had landed.
    """
    root.mkdir(parents=True, exist_ok=True)
    ack_path = root / "acks.jsonl"
    ack_path.touch()
    target = kill_target(seed)

    child = subprocess.Popen(
        [sys.executable, str(HERE / "crash_child.py"), str(seed), str(root), str(ack_path)],
        cwd=HERE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        while True:
            if child.poll() is not None:
                break
            with ack_path.open("rb") as handle:
                landed = sum(1 for _ in handle)
            if landed >= target:
                break
            time.sleep(POLL_SECONDS)
    finally:
        alive = child.poll() is None
        if alive:
            os.kill(child.pid, signal.SIGKILL)
        child.wait()

    return alive, target, len(acknowledgements(ack_path))


def version_chains(root: Path) -> dict[str, list[int]]:
    """Every node's version sequence, read straight out of the journal."""
    chains: dict[str, list[int]] = {}
    for raw in (root / "journal.jsonl").read_bytes().splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break
        entry = json.loads(raw)
        chains.setdefault(entry["node_id"], []).append(entry["version"])
    return chains


@pytest.mark.parametrize("seed", SEEDS)
def test_a_store_killed_mid_write_recovers_consistently(seed: int, tmp_path: Path) -> None:
    root = tmp_path / "graph"
    alive, target, landed = run_until_killed(seed, root)

    # The correction: the run is only evidence if the child was actually killed.
    assert alive, f"seed {seed} finished before the signal; this run proves nothing"
    assert landed >= target, f"killed too early: {landed} acknowledgements, target {target}"
    assert landed < TOTAL_OPS, f"seed {seed} acknowledged the whole workload"

    acks = acknowledgements(root / "acks.jsonl")
    work = generator.build(seed)

    # 1. it opens.
    recovered = Store(root)

    # 2. nothing acknowledged is lost.
    accepted = [a for a in acks if a.accepted and a.revision is not None]
    assert accepted, "the child acknowledged no accepted write"
    by_node: dict[str, list[int]] = {}
    for ack in accepted:
        assert ack.revision is not None
        by_node.setdefault(ack.node_id, []).append(ack.revision)
    for node_id, revisions in by_node.items():
        held = set(recovered.history(node_id))
        assert not [r for r in revisions if r not in held], f"{node_id} lost a revision"

    # 3. no node holds a payload that was never written.
    for node_id in sorted(by_node):
        allowed = {canonical_json(p) for p in work.legal_payloads[node_id]}
        assert canonical_json(recovered.read_node(node_id)) in allowed, node_id

    # 4. every version chain is 1..k.
    for node_id, versions in version_chains(root).items():
        assert versions == list(range(1, len(versions) + 1)), f"{node_id}: {versions[:8]}"

    assert recovered.head_revision() >= max(a.revision or 0 for a in accepted)
    recovered.close()


@pytest.mark.parametrize("seed", SEEDS)
def test_the_task_ledger_survives_the_same_kill(seed: int, tmp_path: Path) -> None:
    """The second append-only file, judged the same way.

    Its length must equal the number of appends the child acknowledged, and a
    torn final line must be dropped rather than counted.
    """
    root = tmp_path / "graph"
    alive, _target, _landed = run_until_killed(seed, root)
    assert alive, f"seed {seed} finished before the signal; this run proves nothing"

    acks = acknowledgements(root / "acks.jsonl")
    assert acks, "the child acknowledged nothing"
    acknowledged_lines = acks[-1].ledger_lines

    ledger = TaskLedger(root / "ledger.jsonl")
    assert len(ledger) >= acknowledged_lines, "an acknowledged ledger line was lost"
    assert len(ledger) <= acknowledged_lines + 1, "more lines survived than were written"
    assert [entry.id for entry in ledger.read_all()] == sorted(
        entry.id for entry in ledger.read_all()
    ), "the ledger is out of order"
    ledger.close()


def files_behind_the_journal(root: Path) -> list[str]:
    """Node files whose revision is older than the journal's head for that node.

    This is the state a kill between the journal sync and the file replace
    leaves, and it is the state recovery exists to repair.
    """
    heads: dict[str, int] = {}
    for raw in (root / "journal.jsonl").read_bytes().splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break
        entry = json.loads(raw)
        heads[entry["node_id"]] = entry["rev"]
    behind = []
    for node_id, rev in heads.items():
        path = root / "nodes" / f"{node_id}.json"
        if not path.exists() or json.loads(path.read_text()).get("rev") != rev:
            behind.append(node_id)
    return behind


@pytest.mark.parametrize("seed", SEEDS)
def test_whatever_the_kill_left_behind_is_repaired(seed: int, tmp_path: Path) -> None:
    """Report what the signal actually reached, and repair it if it reached anything.

    Measured across these five seeds: it reaches nothing. The window between the
    journal line being synced and the node file being replaced is tens of
    microseconds wide, and a signal lands in it about as often as it splits a
    write. So this test is written to be meaningful either way — it records how
    many files were behind, and asserts they are all brought forward — and the
    recovery branches themselves are proven by fixtures that reproduce each state
    directly, in the durable-record tests. Deterministic where it can be,
    probabilistic where it must be, and never claiming the probabilistic half
    covered something it did not reach.
    """
    root = tmp_path / "graph"
    alive, _target, _landed = run_until_killed(seed, root)
    assert alive, f"seed {seed} finished before the signal; this run proves nothing"

    behind = files_behind_the_journal(root)

    recovered = Store(root)
    assert files_behind_the_journal(root) == [], (
        f"recovery left {len(behind)} file(s) behind the journal"
    )
    for node_id in behind:
        assert recovered.read_node(node_id) is not None
    recovered.close()


def test_the_kill_target_is_seeded_and_inside_the_workload() -> None:
    targets = {seed: kill_target(seed) for seed in SEEDS}
    assert targets == {seed: kill_target(seed) for seed in SEEDS}, "not reproducible"
    for seed, target in targets.items():
        assert 250 <= target <= 900, (seed, target)
        assert target < TOTAL_OPS
