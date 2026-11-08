"""The tier machinery has one home each, and nothing outside the evaluation reaches it.

The task schema, the scan and digest of a tier, and the seeded split live in
``physgate.evaluation.tiers``; the bootstrap, the gap and the Wilson interval live in
``physgate.evaluation.gaps``. Their old modules under ``per_role`` are gone rather than
left as aliases: an alias nothing on this branch calls is code no test exercises. Read
from the source alone, so no row needs the evaluation's numerical libraries.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src" / "physgate"
EVALUATION = SRC / "evaluation"
PER_ROLE = EVALUATION / "per_role"
HOMES = ("physgate.evaluation.tiers", "physgate.evaluation.gaps")

#: Each moved module: where it was under ``per_role``, and where it lives now.
MOVED = {
    "task.py": "tiers/task.py",
    "base.py": "tiers/base.py",
    "heldout.py": "tiers/heldout.py",
    "authoring.py": "tiers/authoring.py",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _imported(tree: ast.Module) -> list[tuple[str, str]]:
    """Every module this tree imports from, with the name each import binds."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, a.asname or a.name.split(".")[0]) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found += [(node.module, a.asname or a.name) for a in node.names]
    return found


def _in_a_home(module: str) -> bool:
    return any(module == home or module.startswith(home + ".") for home in HOMES)


@pytest.mark.parametrize("old", sorted(MOVED))
def test_the_old_module_under_per_role_is_gone(old: str) -> None:
    assert not (PER_ROLE / old).exists(), f"per_role/{old} is still there"


@pytest.mark.parametrize("old", sorted(MOVED))
def test_the_module_lives_in_its_new_home(old: str) -> None:
    assert (EVALUATION / MOVED[old]).is_file(), f"{MOVED[old]} is missing"


def test_no_per_role_module_passes_on_a_name_it_takes_from_tiers_or_gaps() -> None:
    passed_on: list[str] = []
    for path in sorted(PER_ROLE.rglob("*.py")):
        tree = _tree(path)
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        exported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                exported |= {
                    c.value
                    for c in ast.walk(node.value)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                }
        for module, bound in _imported(tree):
            if _in_a_home(module) and (bound not in used or bound in exported):
                passed_on.append(f"{path.relative_to(SRC)}: {bound} from {module}")
    assert passed_on == []


def test_no_module_outside_the_evaluation_imports_tiers_or_gaps() -> None:
    reaching = [
        f"{path.relative_to(SRC)}: {module}"
        for path in sorted(SRC.rglob("*.py"))
        if path.relative_to(SRC).parts[0] != "evaluation"
        for module, _ in _imported(_tree(path))
        if _in_a_home(module)
    ]
    assert reaching == []
