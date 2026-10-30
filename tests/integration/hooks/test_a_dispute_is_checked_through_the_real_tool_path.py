"""Through the real binary: a dispute is written by the file tools alone.

A role's session writes ``.physgate/disputes/<node id>.<quantity>.json`` with the Write tool, and
the hook checks it before it exists, against the graph's journal: a well-formed dispute of a
quantity a cross node holds lands; one of another shape, or one from the session of the role that
owns completion, is refused and never exists. A command that names the directory is refused by
the hook. A command that reaches it without naming it (a path built as the command runs) is the
OS layer's to refuse: inside the layer none lands, and without it the same command lands one,
which shows the command works.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session
from os_layer_rig import layer_here, python

from physgate.hooks import graph
from physgate.orchestrator import dispute
from physgate.state.store import Store

pytestmark = pytest.mark.integration

DISPUTE = Path(graph.DISPUTES_DIR) / "sizing.bus.supply_voltage.json"
WELL_FORMED = json.dumps({"value": 24, "unit": "V", "reason": "the driver needs 24 V"})
BUS: dict[str, Any] = {
    "id": "sizing.bus",
    "kind": "component",
    "domain": "cross",
    "owner_role": "sizing",
    "quantities": {
        "supply_voltage": {"value": 12, "unit": "V", "source": "sizing", "written_by": "sizing"}
    },
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-10-30T00:00:00Z",
}


def _graph(worktree: Path) -> None:
    """The session's graph: one cross node sizing wrote, in the store its hooks read."""
    store = Store(worktree.parent / "outside" / "store")
    try:
        assert store.write_node(BUS, "sizing").accepted
    finally:
        store.close()


def _run(
    root: Path,
    *steps: dict[str, Any],
    role: str = "electrical",
    **fields: Any,  # noqa: ANN401 - the install request's own
) -> SessionRun:
    raw = json.dumps(list(steps)).replace("@W", str(root / "worktree"))
    script = Script(main=[*json.loads(raw), text("end")])
    return run_session(root, script, role=role, prepare=_graph, **fields)


def _write(content: str) -> dict[str, Any]:
    return tool("Write", file_path=f"@W/{DISPUTE}", content=content)


def _refusals(run: SessionRun) -> list[str]:
    return [
        e["reason"]
        for e in run.hook_log
        if e.get("decision") == "refuse" and e.get("hook") == "graph"
    ]


def test_a_well_formed_dispute_lands(tmp_path: Path) -> None:
    run = _run(tmp_path, _write(WELL_FORMED))
    assert _refusals(run) == []
    assert (run.worktree / DISPUTE).read_text() == WELL_FORMED


def test_a_dispute_of_another_shape_is_refused_and_never_exists(tmp_path: Path) -> None:
    run = _run(tmp_path, _write(json.dumps({"value": "24", "unit": "V", "reason": "r"})))
    (reason,) = _refusals(run)
    assert reason.startswith(graph.DISPUTE_REFUSED.format(detail=""))
    assert dispute.VALUE in run.told_after(1)
    assert not (run.worktree / DISPUTE).exists()


def test_a_dispute_from_the_completion_owners_session_is_refused_and_never_exists(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, _write(WELL_FORMED), role="integration")
    (reason,) = _refusals(run)
    assert "owns completion" in reason
    assert not (run.worktree / DISPUTE).exists()


def test_a_command_naming_the_disputes_directory_is_refused(tmp_path: Path) -> None:
    command = f"mkdir -p {graph.DISPUTES_DIR} && cat > {DISPUTE} <<'EOF'\n{WELL_FORMED}\nEOF"
    run = _run(tmp_path, tool("Bash", command=command))
    assert _refusals(run) == [graph.DISPUTE_SHELL]
    assert not (run.worktree / DISPUTE).exists()


#: A command that names nothing the hooks read: the path is joined as it runs.
BUILT = python(
    "import os\n"
    "d = os.path.join('.phys' + 'gate', 'disp' + 'utes')\n"
    "os.makedirs(d, exist_ok=True)\n"
    f"open(os.path.join(d, 'sizing.bus.supply_' + 'voltage.json'), 'w').write({WELL_FORMED!r})"
)


@pytest.mark.parametrize("layer", [True, False], ids=["inside the OS layer", "without it"])
def test_a_shell_command_cannot_write_a_dispute_inside_the_os_layer(
    tmp_path: Path, layer: bool
) -> None:
    if layer and not layer_here():
        pytest.skip("the OS layer cannot run here")
    run = _run(tmp_path, tool("Bash", command=BUILT), os_layer=layer)
    assert _refusals(run) == []  # the text hook saw nothing to refuse
    assert (run.worktree / DISPUTE).exists() is not layer
    if layer:
        # The file tools still write it inside the layer.
        again = _run(tmp_path / "file-tool", _write(WELL_FORMED), os_layer=True)
        assert (again.worktree / DISPUTE).read_text() == WELL_FORMED
