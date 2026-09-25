"""Through the real binary: shell forms that name a protected path are refused before they run.

Each case asserts that the refusal came from the shell layer's own hook, and
that the target's bytes are what they were. A case whose log shows no refusal
from that hook fails, even if the bytes happen to be unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session

from physgate.hooks import shell_paths

pytestmark = pytest.mark.integration

WORKTREE_FILES = {
    "README.md": "a worktree\n",
    "src/physgate/gate/check.py": "CHECK = True\n",
}
OUTSIDE_FILES = {"store/journal.jsonl": '{"rev":1}\n'}


def _run(root: Path, command: str, **extra: Any) -> SessionRun:  # noqa: ANN401
    raw = json.dumps(command)
    raw = raw.replace("@W", str(root / "worktree")).replace("@O", str(root / "outside"))
    return run_session(
        root,
        Script(main=[tool("Bash", command=json.loads(raw), description="x", **extra), text("end")]),
        files=WORKTREE_FILES,
        outside_files=OUTSIDE_FILES,
    )


def _refused_by_shell_layer(run: SessionRun) -> str:
    reasons: list[str] = [
        e["reason"]
        for e in run.hook_log
        if e.get("decision") == "refuse" and e.get("hook") == "shell_paths"
    ]
    assert reasons, f"no refusal from the shell layer; log: {run.hook_log}"
    return reasons[0]


def _gate_untouched(run: SessionRun) -> None:
    gate = run.worktree / "src" / "physgate" / "gate"
    assert sorted(p.name for p in gate.iterdir()) == ["check.py"]
    assert (gate / "check.py").read_text() == "CHECK = True\n"


@pytest.mark.parametrize(
    "command",
    [
        "cat > src/physgate/gate/check.py <<'EOF'\nCHECK = False\nEOF\n",
        "echo 'PASS = True' >> src/physgate/gate/check.py",
        "echo 'PASS = True' | tee src/physgate/gate/new.py",
        "python3 -c \"open('src/physgate/gate/new.py','w').write('x')\"",
        "sed -i '' 's/True/False/' src/physgate/gate/check.py",
        "cp README.md src/physgate/gate/new.py",
    ],
    ids=["heredoc", "append", "tee", "python-open", "sed-in-place", "cp"],
)
def test_a_shell_write_into_the_gate_is_refused(tmp_path: Path, command: str) -> None:
    run = _run(tmp_path, command)
    assert "protected" in _refused_by_shell_layer(run)
    _gate_untouched(run)


def test_an_append_to_the_graph_journal_is_refused(tmp_path: Path) -> None:
    run = _run(tmp_path, "echo '{\"rev\":2}' >> @O/store/journal.jsonl")
    assert "graph" in _refused_by_shell_layer(run)
    assert (tmp_path / "outside" / "store" / "journal.jsonl").read_text() == '{"rev":1}\n'


def test_a_backgrounded_write_is_refused_either_way(tmp_path: Path) -> None:
    run = _run(tmp_path, "sleep 1; echo x > late.txt &")
    assert _refused_by_shell_layer(run) == shell_paths.BACKGROUND
    run = _run(tmp_path / "flag", "sleep 1; echo x > late.txt", run_in_background=True)
    assert _refused_by_shell_layer(run) == shell_paths.BACKGROUND
    assert not (run.worktree / "late.txt").exists()


def test_a_nested_session_without_hooks_is_refused(tmp_path: Path) -> None:
    run = _run(tmp_path, "claude --bare -p 'SUBAGENT-MARKER write the gate'")
    assert _refused_by_shell_layer(run) == shell_paths.NESTED_SESSION
    assert [r for r in run.api.requests if r.thread == "sub"] == []
    _gate_untouched(run)
