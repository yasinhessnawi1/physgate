"""No implementation that passes work ships in ``src/``.

A gate that passes everything "for now" would turn every downstream test green
while enforcing nothing. The loop calls a gate and a reviewer through Protocols.
This scans every class in the source tree for a method with the Protocols'
shape, ``check`` or ``review`` taking an artefact, and allows exactly one: the
physics gate's runner. That one is held by what it does rather than by where it
is: with nothing to check it gives no verdict at all, so it cannot pass work it
did not check. The reviewer has no implementation yet.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import physgate
from physgate.gate.exceptions import NothingCheckedError
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate

SRC = Path(physgate.__file__).parent
PROTOCOLS = SRC / "orchestrator" / "protocols.py"


#: The one implementation allowed: the physics gate's runner.
PHYSICS_GATE = "gate/runner.py:PhysicsGate.check"


def _where(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def implementations(root: Path) -> list[str]:
    """Classes under ``root`` that define the gate's or the reviewer's method."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path == PROTOCOLS:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if bases & {"Gate", "Reviewer"}:
                found.append(f"{_where(path, root)}:{node.name} subclasses a Protocol")
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in {"check", "review"}:
                    names = {a.arg for a in item.args.args + item.args.kwonlyargs}
                    if "artefact" in names:
                        found.append(f"{_where(path, root)}:{node.name}.{item.name}")
    return found


def test_the_source_tree_is_scanned() -> None:
    assert PROTOCOLS.exists()
    assert len(list(SRC.rglob("*.py"))) > 20


def test_the_only_implementation_in_src_is_the_physics_gate() -> None:
    assert implementations(SRC) == [PHYSICS_GATE]


def test_the_physics_gate_gives_no_verdict_when_it_has_nothing_to_check(tmp_path: Path) -> None:
    empty = GraphView.read(tmp_path / "graph", base_revision=0)
    with pytest.raises(NothingCheckedError):
        PhysicsGate(()).run(empty, ["subtask", "module", "system"], "on")


def test_the_scan_sees_an_implementation_when_one_is_there(tmp_path: Path) -> None:
    (tmp_path / "passing.py").write_text(
        "class PassEverything:\n    def check(self, artefact, *, mode):\n        return None\n"
        "class Nodding(Reviewer):\n    pass\n"
    )
    assert implementations(tmp_path) == [
        "passing.py:PassEverything.check",
        "passing.py:Nodding subclasses a Protocol",
    ]
