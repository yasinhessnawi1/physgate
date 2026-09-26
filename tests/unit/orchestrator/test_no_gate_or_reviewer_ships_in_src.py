"""No implementation that passes work ships in ``src/``.

A gate that passes everything "for now" would turn every downstream test green
while enforcing nothing. The loop calls a gate and a reviewer through Protocols,
and nothing under ``src/`` implements either until the physics gate and the
reviewer register their own. This scans every class in the source tree for a
method with the Protocols' shape: ``check`` or ``review`` taking an artefact.
"""

from __future__ import annotations

import ast
from pathlib import Path

import physgate

SRC = Path(physgate.__file__).parent
PROTOCOLS = SRC / "orchestrator" / "protocols.py"


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
                found.append(f"{path.name}:{node.name} subclasses a Protocol")
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in {"check", "review"}:
                    names = {a.arg for a in item.args.args + item.args.kwonlyargs}
                    if "artefact" in names:
                        found.append(f"{path.name}:{node.name}.{item.name}")
    return found


def test_the_source_tree_is_scanned() -> None:
    assert PROTOCOLS.exists()
    assert len(list(SRC.rglob("*.py"))) > 20


def test_no_class_in_src_implements_the_gate_or_the_reviewer() -> None:
    assert implementations(SRC) == []


def test_the_scan_sees_an_implementation_when_one_is_there(tmp_path: Path) -> None:
    (tmp_path / "passing.py").write_text(
        "class PassEverything:\n    def check(self, artefact, *, mode):\n        return None\n"
        "class Nodding(Reviewer):\n    pass\n"
    )
    assert implementations(tmp_path) == [
        "passing.py:PassEverything.check",
        "passing.py:Nodding subclasses a Protocol",
    ]
