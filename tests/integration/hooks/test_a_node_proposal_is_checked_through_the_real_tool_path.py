"""Through the real binary: a node reaches the graph only as a checked proposal.

Criterion 4: a proposal for a node another role owns is refused before anything
changes, with the store's cross-role reason, and the owner's legal proposal
lands. Criterion 5: a bare-number quantity is refused with the schema's error in
the hook's message. The store, a real one built before the session, is
byte-identical afterwards in every case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session

from physgate.hooks import graph
from physgate.state.protocol import REJECT_CROSS_ROLE, REJECT_MISSING_UNIT
from physgate.state.store import Store

pytestmark = pytest.mark.integration


def _node(node_id: str, owner: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    base: dict[str, Any] = {
        "id": node_id,
        "kind": "component",
        "domain": owner,
        "owner_role": owner,
        "quantities": {
            "stall_current": {"value": 2.4, "unit": "A", "source": "datasheet", "written_by": owner}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-09-25T00:00:00Z",
    }
    base.update(fields)
    return base


def _store(worktree: Path) -> None:
    store = Store(worktree.parent / "outside" / "store")
    try:
        for payload in (_node("electrical.motor", "electrical"), _node("control.loop", "control")):
            assert store.write_node(payload, payload["owner_role"]).accepted
    finally:
        store.close()


def _run(root: Path, *steps: dict[str, Any]) -> tuple[SessionRun, dict[str, bytes]]:
    raw = json.dumps(list(steps)).replace("@W", str(root / "worktree"))
    run = run_session(
        root,
        Script(main=[*json.loads(raw), text("end")]),
        prepare=_store,
        store_root=str(root / "outside" / "store"),
    )
    store = root / "outside" / "store"
    return run, {str(p): p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()}


def _proposal(name: str, payload: object) -> dict[str, Any]:
    return tool(
        "Write",
        file_path=f"@W/{graph.PROPOSALS_DIR}/{name}",
        content=payload if isinstance(payload, str) else json.dumps(payload),
    )


def _graph_refusals(run: SessionRun) -> list[str]:
    return [
        e["reason"]
        for e in run.hook_log
        if e.get("decision") == "refuse" and e.get("hook") == "graph"
    ]


def _unchanged(tmp_path: Path, after: dict[str, bytes]) -> None:
    fresh = tmp_path / "fresh"
    (fresh / "worktree").mkdir(parents=True)
    _store(fresh / "worktree")
    expected = {
        p.replace(str(fresh), str(tmp_path)): Path(p).read_bytes()
        for p in map(str, sorted((fresh / "outside" / "store").rglob("*")))
        if Path(p).is_file()
    }
    assert after == expected


def test_a_proposal_for_another_roles_node_is_refused_and_nothing_changes(tmp_path: Path) -> None:
    run, store = _run(tmp_path, _proposal("control.loop.json", _node("control.loop", "electrical")))
    (reason,) = _graph_refusals(run)
    assert REJECT_CROSS_ROLE in reason and "owned by the control role" in reason
    assert REJECT_CROSS_ROLE in run.told_after(1)
    assert not (run.worktree / graph.PROPOSALS_DIR / "control.loop.json").exists()
    _unchanged(tmp_path, store)


def test_the_owners_legal_proposal_lands(tmp_path: Path) -> None:
    payload = _node("electrical.motor", "electrical", quantities={})
    run, store = _run(tmp_path, _proposal("electrical.motor.json", payload))
    assert _graph_refusals(run) == []
    written = run.worktree / graph.PROPOSALS_DIR / "electrical.motor.json"
    assert json.loads(written.read_text()) == payload
    _unchanged(tmp_path, store)


def test_a_bare_number_is_refused_with_the_schema_error(tmp_path: Path) -> None:
    payload = {**_node("electrical.driver", "electrical"), "quantities": {"stall_current": 2.4}}
    run, store = _run(tmp_path, _proposal("electrical.driver.json", payload))
    (reason,) = _graph_refusals(run)
    assert REJECT_MISSING_UNIT in reason and "stall_current" in reason
    assert "stall_current" in run.told_after(1)
    assert not (run.worktree / graph.PROPOSALS_DIR / "electrical.driver.json").exists()
    _unchanged(tmp_path, store)


def test_a_proposal_written_through_the_shell_is_refused(tmp_path: Path) -> None:
    command = (
        f"mkdir -p {graph.PROPOSALS_DIR} && cat > {graph.PROPOSALS_DIR}/control.loop.json <<'EOF'\n"
        + json.dumps(_node("control.loop", "electrical"))
        + "\nEOF\n"
    )
    run, store = _run(tmp_path, tool("Bash", command=command, description="x"))
    assert _graph_refusals(run) == [graph.SHELL_WRITE]
    assert not (run.worktree / graph.PROPOSALS_DIR).exists()
    _unchanged(tmp_path, store)
