"""The sync is asserted, because no test in this suite can observe its absence.

Both append paths flush and then sync before returning, and the module docstrings
and the package readme both use the word *synced* when they say what durability
means here. Removing `os.fsync` from either path leaves every other test in this
suite green, and that is not a gap in those tests — it is what they can see.

A flush moves bytes out of the process into the kernel's page cache. A sync moves
them out of the page cache onto the device. **A killed process cannot tell the
two apart**: the page cache belongs to the kernel and outlives the process, so a
file written with a flush and no sync reads back perfectly after any `SIGKILL`.
Only losing the machine loses that data, and no test here can cut the power.

So the detector is the call itself. If the word in the docstring is *synced*,
the assertion is that the sync happened, on the descriptor that holds the record,
before the call returned.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest import mock

from helpers import node

from physgate.state.store import Store
from physgate.state.task_ledger import TaskLedger, TaskLine


def synced_descriptors(calls: Any) -> set[int]:
    """The file descriptors ``os.fsync`` was called on."""
    return {call.args[0] for call in calls if call.args}


def test_an_accepted_write_syncs_the_journal_before_it_returns(tmp_path: Path) -> None:
    root = tmp_path / "graph"
    store = Store(root)

    real_fsync = os.fsync
    with mock.patch("os.fsync", wraps=real_fsync) as spy:
        result = store.write_node(node(), "electrical")
        assert result.accepted
        calls_at_return = spy.call_count

    assert calls_at_return >= 2, (
        f"one accepted write performed {calls_at_return} syncs; "
        "the journal line and the node file each need one"
    )
    store.close()


def test_a_refused_write_syncs_nothing(tmp_path: Path) -> None:
    """A refusal writes nothing, so it has nothing to make durable."""
    root = tmp_path / "graph"
    store = Store(root)
    store.write_node(node(), "electrical")

    with mock.patch("os.fsync", wraps=os.fsync) as spy:
        assert not store.write_node(node(updated="x"), "control").accepted
        assert spy.call_count == 0

    store.close()


def test_the_journal_descriptor_is_the_one_that_is_synced(tmp_path: Path) -> None:
    """Syncing some other descriptor would satisfy a bare call count."""
    root = tmp_path / "graph"
    store = Store(root)
    journal_fd = store._journal.fileno()  # noqa: SLF001 - the descriptor is the assertion

    with mock.patch("os.fsync", wraps=os.fsync) as spy:
        store.write_node(node(), "electrical")
        assert journal_fd in synced_descriptors(spy.mock_calls)

    store.close()


def test_a_ledger_append_syncs_the_ledger_before_it_returns(tmp_path: Path) -> None:
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    ledger_fd = ledger._handle.fileno()  # noqa: SLF001 - the descriptor is the assertion

    with mock.patch("os.fsync", wraps=os.fsync) as spy:
        ledger.append(
            TaskLine(
                id="t-000",
                spec_path="specs/control.md",
                assigned_role="control",
                attempt_count=1,
            )
        )
        assert spy.call_count >= 1
        assert ledger_fd in synced_descriptors(spy.mock_calls)

    ledger.close()


def test_the_node_file_is_synced_before_it_replaces_the_old_one(tmp_path: Path) -> None:
    """The temporary file is synced before it replaces the old one.

    Otherwise the rename is atomic over content that never reached the
    device, which is an atomic swap to nothing.
    """
    root = tmp_path / "graph"
    store = Store(root)

    order: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def note_fsync(fd: int) -> None:
        order.append("fsync")
        real_fsync(fd)

    def note_replace(src: Any, dst: Any) -> None:
        order.append("replace")
        real_replace(src, dst)

    with mock.patch("os.fsync", note_fsync), mock.patch("os.replace", note_replace):
        store.write_node(node(), "electrical")

    assert "replace" in order, "the node file was never placed"
    assert order.index("fsync") < order.index("replace"), order
    store.close()
