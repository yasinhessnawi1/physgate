"""Through the real binary: a node file changed behind the store is rebuilt from the journal.

The shell layer is not wired, as in the bypass suite's sentinel-alone arm, so a
command that rewrites a graph node file runs. The sentinel sees the file no
longer holds what the journal says, puts the journal's version back, records
the incident and refuses every call after it. The journal is the authority; a
session ends with the node file as the journal says it is.

The command also writes a marker in the worktree, which proves it ran: a node
file left unchanged by a command that never ran would prove nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session

from physgate.hooks import sentinel
from physgate.hooks.journal_view import heads
from physgate.hooks.registry import REGISTRY
from physgate.state import node_file_body
from physgate.state.store import Store

pytestmark = pytest.mark.integration

NODE = Path("outside/store/nodes/electrical.motor.json")
#: Inert: valid JSON, no command, nothing that runs; only not what the journal says.
INERT = '{"payload":{"id":"electrical.motor"},"rev":1,"version":1}'


def _node() -> dict[str, object]:
    return {
        "id": "electrical.motor",
        "kind": "component",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {
            "stall_current": {
                "value": 2.4,
                "unit": "A",
                "source": "datasheet",
                "written_by": "electrical",
            }
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-09-25T00:00:00Z",
    }


def _store(worktree: Path) -> None:
    store = Store(worktree.parent / "outside" / "store")
    try:
        assert store.write_node(_node(), "electrical").accepted
    finally:
        store.close()


def _run(root: Path, command: str) -> SessionRun:
    return run_session(
        root,
        Script(main=[tool("Bash", command=command, description="x"), text("end")]),
        prepare=_store,
        registry={k: v for k, v in REGISTRY.items() if k != "shell_paths"},
    )


def test_with_the_parser_off_a_rewritten_node_file_is_rebuilt_from_the_journal(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        f"printf '%s' '{INERT}' > ../{NODE} && echo ran > ran.txt",
    )
    assert (run.worktree / "ran.txt").read_text() == "ran\n", "the command did not run"
    store = tmp_path / "outside" / "store"
    (rev, version, payload) = heads(str(store))["electrical.motor"]
    assert (tmp_path / NODE).read_bytes() == node_file_body(rev, version, payload).encode()
    reopened = Store(store)
    try:
        assert reopened.repaired_node_files == 0, "the session left the node file changed"
        assert reopened.read_node("electrical.motor") == _node()
    finally:
        reopened.close()
    events = [e for e in run.hook_log if e.get("hook") == "sentinel"]
    # The incident once, then the dispatcher's refusal of that call and of every
    # later one: the session stays halted after the file is put back.
    decisions = [e["decision"] for e in events]
    assert decisions[:2] == ["node mismatch", "refuse"], run.hook_log
    assert set(decisions[2:]) <= {"refuse"}, run.hook_log
    assert events[0]["paths"] == [str(tmp_path / NODE)]
    assert events[0]["restored"] == [str(tmp_path / NODE)]
    assert [e for e in run.hook_log if e.get("hook") == "shell_paths"] == []
    assert sentinel.NODE_MISMATCH.split("{paths}")[0] in run.told_after(1)


def test_with_the_parser_off_a_deleted_node_file_is_rebuilt_from_the_journal(
    tmp_path: Path,
) -> None:
    # A node file the journal names and the session removed: the sentinel finds it
    # missing, writes the journal's version back, and the session stays halted.
    run = _run(tmp_path, f"rm ../{NODE} && echo ran > ran.txt")
    assert (run.worktree / "ran.txt").read_text() == "ran\n", "the command did not run"
    store = tmp_path / "outside" / "store"
    (rev, version, payload) = heads(str(store))["electrical.motor"]
    assert (tmp_path / NODE).read_bytes() == node_file_body(rev, version, payload).encode()
    reopened = Store(store)
    try:
        assert reopened.repaired_node_files == 0, "the session left the node file missing"
        assert reopened.read_node("electrical.motor") == _node()
    finally:
        reopened.close()
    events = [e for e in run.hook_log if e.get("hook") == "sentinel"]
    decisions = [e["decision"] for e in events]
    assert decisions[:2] == ["node mismatch", "refuse"], run.hook_log
    assert set(decisions[2:]) <= {"refuse"}, run.hook_log
    assert events[0]["paths"] == [str(tmp_path / NODE)]
    assert events[0]["restored"] == [str(tmp_path / NODE)]
    assert sentinel.NODE_MISMATCH.split("{paths}")[0] in run.told_after(1)
