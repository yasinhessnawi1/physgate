"""A proposal that touches a declared quantity is refused at apply as a repair, not as a halt.

The hook refuses such a proposal as the session writes it. One that reaches the commit by a
route the hook does not see is read at apply, and refused there for the same two reasons
(``declared_forged``: a declared quantity added, or the reserved source without the decision;
``declared_fixed``: one changed or dropped), in a message that names the quantity and says that
declared parts are fixed by a person. The refusal is a ``ProposalRefusedError``, which the
change check turns into a refusal the session repairs: only a write that reaches the store
past these checks is an incident.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.orchestrator.apply import ProposalRefusedError, read_proposals
from physgate.state.protocol import REJECT_MISSING_UNIT
from physgate.state.store import Store

RESERVED = "declared by the person"
MOTOR = "electrical.motor"
ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _declared(value: float = 0.4) -> dict[str, Any]:
    return {
        "value": value,
        "unit": "kg",
        "source": RESERVED,
        "written_by": "electrical",
        "declared": {"item_id": "run-1-parts-1", "decision_sha256": "a" * 64, "operator": "yasin"},
    }


def _plain(value: float = 2.4) -> dict[str, Any]:
    return {"value": value, "unit": "A", "source": "datasheet", "written_by": "electrical"}


def _node(node_id: str, quantities: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "component",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": quantities,
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-11-12T10:00:00.000000Z",
    }


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    graph = Store(root)
    try:
        assert graph.declare(_node(MOTOR, {"mass": _declared()}), ["run-1-parts-1"]).accepted
        assert graph.write_node(_node("electrical.driver", {"i": _plain()}), "electrical").accepted
    finally:
        graph.close()
    return root


def _proposed(tmp_path: Path, store: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "m.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    base = _git(repo, "rev-parse", "HEAD")
    path = repo / ".physgate" / "proposals" / f"{payload['id']}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "proposal")
    commit = _git(repo, "rev-parse", "HEAD")
    return read_proposals(repo, base, commit, store, role="electrical")


def _refusal(tmp_path: Path, store: Path, payload: dict[str, Any]) -> ProposalRefusedError:
    try:
        read = _proposed(tmp_path, store, payload)
    except ProposalRefusedError as refused:
        return refused
    raise AssertionError(f"read, not refused: {[p['id'] for p in read]}")


def test_a_declared_quantity_as_it_stands_and_a_role_s_own_are_read(
    tmp_path: Path, store: Path
) -> None:
    ok = _node(MOTOR, {"mass": _declared(), "own": _plain(1.0)})
    assert [p["id"] for p in _proposed(tmp_path, store, ok)] == [MOTOR]


def test_a_changed_declared_quantity_is_declared_fixed_and_says_who_fixes_it(
    tmp_path: Path, store: Path
) -> None:
    refused = _refusal(tmp_path, store, _node(MOTOR, {"mass": _declared(0.9)}))
    assert refused.reason == "declared_fixed"
    assert "mass" in str(refused) and "fixed by a person" in str(refused)


def test_a_dropped_declared_quantity_is_declared_fixed(tmp_path: Path, store: Path) -> None:
    refused = _refusal(tmp_path, store, _node(MOTOR, {"own": _plain()}))
    assert refused.reason == "declared_fixed"
    assert "mass" in str(refused) and "fixed by a person" in str(refused)


def test_an_added_declared_quantity_is_declared_forged(tmp_path: Path, store: Path) -> None:
    refused = _refusal(tmp_path, store, _node("electrical.driver", {"mass": _declared()}))
    assert refused.reason == "declared_forged"
    assert "mass" in str(refused) and "fixed by a person" in str(refused)


@pytest.mark.parametrize("source", [RESERVED, "Declared", "user-declared"])
def test_the_reserved_source_without_the_record_is_declared_forged(
    tmp_path: Path, store: Path, source: str
) -> None:
    bare = {"value": 1.0, "unit": "A", "source": source, "written_by": "electrical"}
    refused = _refusal(tmp_path, store, _node("electrical.driver", {"i": bare}))
    assert refused.reason == "declared_forged" and "i" in str(refused)


def test_a_bare_number_keeps_its_old_reason(tmp_path: Path, store: Path) -> None:
    refused = _refusal(tmp_path, store, _node("electrical.driver", {"i": 2.4}))
    assert refused.reason == REJECT_MISSING_UNIT
