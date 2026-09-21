"""The promoted store interface is the one the store comparison froze.

The pre-registered experiment fixed this surface before either implementation
existed and scored both against it. If the promoted Protocol drifts, every
number in that result file stops describing this code. So the comparison is a
test rather than a paragraph in a close-out: it reads the frozen file, parses
it, and fails if the call surface has moved.

It parses rather than imports. The frozen tree is deliberately outside the
linter's and the type checker's reach, and importing from it would need path
surgery that neither tool can follow.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from physgate.state import protocol as promoted

FROZEN = Path(__file__).resolve().parents[3] / "experiments" / "R-OP-01" / "src" / "protocol.py"
INTERFACE = "DesignStateStore"


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    msg = f"{name} not found"
    raise AssertionError(msg)


def _call_surface(tree: ast.Module, class_name: str) -> list[tuple[str, tuple[str, ...], int]]:
    """Method name, parameter names, and how many of them carry a default."""
    out = []
    for item in _class(tree, class_name).body:
        if isinstance(item, ast.FunctionDef):
            args = item.args
            names = tuple(a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs))
            out.append((item.name, names, len(args.defaults) + len(args.kw_defaults)))
    return out


def _annotations(tree: ast.Module, class_name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in _class(tree, class_name).body:
        if isinstance(item, ast.FunctionDef):
            for a in item.args.args:
                if a.annotation is not None:
                    out[f"{item.name}.{a.arg}"] = ast.unparse(a.annotation)
            if item.returns is not None:
                out[f"{item.name}.->"] = ast.unparse(item.returns)
    return out


def _constants(tree: ast.Module) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    out[t.id] = node.value.value
    return out


def _dataclass_fields(tree: ast.Module, name: str) -> list[str]:
    return [
        item.target.id
        for item in _class(tree, name).body
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
    ]


def test_the_frozen_interface_file_is_where_we_think_it_is() -> None:
    assert FROZEN.is_file(), FROZEN


def test_the_call_surface_is_identical_to_the_frozen_one() -> None:
    frozen = _call_surface(_module(FROZEN), INTERFACE)
    here = _call_surface(_module(Path(promoted.__file__)), INTERFACE)
    assert frozen, "parsed no methods at all"
    assert len(frozen) == 8, f"the frozen interface has {len(frozen)} methods, expected 8"
    assert here == frozen


def test_the_only_annotation_changes_are_the_bare_dict_being_parameterised() -> None:
    """A bare ``dict`` fails the strict type checker; the shape it names is unchanged."""
    frozen = _annotations(_module(FROZEN), INTERFACE)
    here = _annotations(_module(Path(promoted.__file__)), INTERFACE)
    assert set(frozen) == set(here)
    moved = {k: (frozen[k], here[k]) for k in frozen if frozen[k] != here[k]}
    assert moved == {
        "write_node.node": ("dict", "dict[str, Any]"),
        "read_node.->": ("dict", "dict[str, Any]"),
    }


def test_the_rejection_reason_vocabulary_is_unchanged() -> None:
    """These strings are what the frozen correctness score is counted in."""
    frozen = {k: v for k, v in _constants(_module(FROZEN)).items() if k.startswith("REJECT_")}
    here = {
        k: v
        for k, v in _constants(_module(Path(promoted.__file__))).items()
        if k.startswith("REJECT_")
    }
    assert frozen, "parsed no rejection reasons at all"
    assert here == frozen


def test_the_result_types_carry_the_same_fields() -> None:
    frozen_tree, here_tree = _module(FROZEN), _module(Path(promoted.__file__))
    for name in ("WriteResult", "NodeChange"):
        assert _dataclass_fields(here_tree, name) == _dataclass_fields(frozen_tree, name), name


def test_the_promoted_protocol_is_runtime_checkable() -> None:
    assert isinstance(promoted.DesignStateStore, type)
    assert hasattr(promoted.DesignStateStore, "_is_runtime_protocol")
