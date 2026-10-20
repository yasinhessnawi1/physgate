"""An identifier or a path that ends in a newline is not the one the run could have written.

``re.match`` with a pattern ending in ``$`` accepts a final newline, because ``$`` also matches
before one. Every validator uses ``fullmatch``, and a scan of the source holds that:
no compiled pattern ending in ``$`` is read with ``.match``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from physgate.orchestrator.common import _full_model_string
from physgate.orchestrator.exceptions import RunStateError  # noqa: F401
from physgate.orchestrator.git import GitError
from physgate.orchestrator.merge import _safe
from physgate.series.reader import RecordRefusedError, record_path
from physgate.series.writer import SeriesWriterError, _name

SRC = Path(__file__).resolve().parents[3] / "src" / "physgate"


def test_a_subtask_id_with_a_trailing_newline_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RecordRefusedError):
        record_path(tmp_path, "s1\n", 1, "sess", "rec")


def test_a_session_id_with_a_trailing_newline_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RecordRefusedError):
        record_path(tmp_path, "s1", 1, "sess\n", "rec")


def test_a_record_id_with_a_trailing_newline_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RecordRefusedError):
        record_path(tmp_path, "s1", 1, "sess", "rec\n")


def test_a_plain_identifier_is_still_accepted(tmp_path: Path) -> None:
    assert record_path(tmp_path, "s1", 1, "sess", "rec").name == "rec.json"


def test_a_branch_or_run_name_with_a_trailing_newline_is_refused() -> None:
    with pytest.raises(GitError):
        _safe("run-1\n", "a run id")
    assert _safe("run-1", "a run id") == "run-1"


def test_a_series_name_with_a_trailing_newline_is_refused() -> None:
    with pytest.raises(SeriesWriterError):
        _name("rail\n", "a series name")
    assert _name("rail", "a series name") == "rail"


def test_a_model_string_with_a_trailing_newline_is_refused() -> None:
    with pytest.raises(ValueError, match="full model string"):
        _full_model_string("claude-sonnet-5\n")
    assert _full_model_string("claude-sonnet-5") == "claude-sonnet-5"


def _anchored_patterns(tree: ast.Module) -> set[str]:
    """Names bound to ``re.compile`` of a pattern that ends in ``$`` (or is built from one)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if ast.unparse(call.func) != "re.compile" or not call.args:
            continue
        text = ast.unparse(call.args[0])
        if "$" in text or "NAME_PATTERN" in text:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


def test_no_pattern_that_ends_in_a_dollar_is_read_with_match() -> None:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        anchored = _anchored_patterns(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "match":
                continue
            target = node.func.value
            if isinstance(target, ast.Name) and target.id in anchored:
                found.append(f"{path.relative_to(SRC)}:{node.lineno} {target.id}.match")
            if ast.unparse(target) == "re" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and str(first.value).endswith("$"):
                    found.append(f"{path.relative_to(SRC)}:{node.lineno} re.match")
    assert found == []


def test_the_reader_reads_no_pattern_it_reads_with_match() -> None:
    text = (SRC / "series" / "reader.py").read_text()
    # Its patterns are read through a variable, which the scan above cannot follow.
    assert "pattern.match(" not in text
