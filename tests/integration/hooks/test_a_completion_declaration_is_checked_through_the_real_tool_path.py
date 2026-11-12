"""Through the real binary: the completion declaration is written by the file tools alone.

Integration's session writes ``.physgate/completion/declaration.json`` with the Write tool, and the
hook checks it before it exists: a well-formed one lands; one of another shape, or one from any
other role's session, is refused and never exists. A command that names the directory is refused
by the hook. A command that reaches it without naming it (a path built as the command runs) is the
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

pytestmark = pytest.mark.integration

DECLARATION = Path(graph.COMPLETION_DIR) / graph.DECLARATION_NAME
WELL_FORMED = json.dumps({"complete": ["s1", "s2"]})


def _run(
    root: Path,
    *steps: dict[str, Any],
    role: str = "integration",
    **fields: Any,  # noqa: ANN401 - the install request's own
) -> SessionRun:
    raw = json.dumps(list(steps)).replace("@W", str(root / "worktree"))
    script = Script(main=[*json.loads(raw), text("end")])
    return run_session(root, script, role=role, **fields)


def _write(content: str) -> dict[str, Any]:
    return tool("Write", file_path=f"@W/{DECLARATION}", content=content)


def _refusals(run: SessionRun) -> list[str]:
    return [
        e["reason"]
        for e in run.hook_log
        if e.get("decision") == "refuse" and e.get("hook") == "graph"
    ]


def test_integrations_well_formed_declaration_lands(tmp_path: Path) -> None:
    run = _run(tmp_path, _write(WELL_FORMED))
    assert _refusals(run) == []
    assert (run.worktree / DECLARATION).read_text() == WELL_FORMED


def test_a_declaration_of_another_shape_is_refused_and_never_exists(tmp_path: Path) -> None:
    run = _run(tmp_path, _write('{"complete": "s1"}'))
    (reason,) = _refusals(run)
    assert reason.startswith(graph.DECLARATION_REFUSED.format(detail=""))
    assert "one JSON object with one key" in run.told_after(1)
    assert not (run.worktree / DECLARATION).exists()


def test_a_declaration_from_another_roles_session_is_refused_and_never_exists(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, _write(WELL_FORMED), role="electrical")
    (reason,) = _refusals(run)
    assert "integration role" in reason and "electrical role" in reason
    assert not (run.worktree / DECLARATION).exists()


def test_a_command_naming_the_completion_directory_is_refused(tmp_path: Path) -> None:
    command = f"mkdir -p {graph.COMPLETION_DIR} && cat > {DECLARATION} <<'EOF'\n{WELL_FORMED}\nEOF"
    run = _run(tmp_path, tool("Bash", command=command))
    assert _refusals(run) == [graph.DECLARATION_SHELL]
    assert not (run.worktree / DECLARATION).exists()


#: A command that names nothing the hooks read: the path is joined as it runs.
BUILT = python(
    "import os\n"
    "d = os.path.join('.phys' + 'gate', 'compl' + 'etion')\n"
    "os.makedirs(d, exist_ok=True)\n"
    f"open(os.path.join(d, 'declar' + 'ation.json'), 'w').write({WELL_FORMED!r})"
)


@pytest.mark.parametrize("layer", [True, False], ids=["inside the OS layer", "without it"])
def test_a_shell_command_cannot_write_the_completion_declaration_inside_the_os_layer(
    tmp_path: Path, layer: bool
) -> None:
    if layer and not layer_here():
        pytest.skip("the OS layer cannot run here")
    run = _run(tmp_path, tool("Bash", command=BUILT), os_layer=layer)
    assert _refusals(run) == []  # the text hook saw nothing to refuse
    assert (run.worktree / DECLARATION).exists() is not layer
    if layer:
        # The file tools still write it inside the layer.
        again = _run(tmp_path / "file-tool", _write(WELL_FORMED), os_layer=True)
        assert (again.worktree / DECLARATION).read_text() == WELL_FORMED
