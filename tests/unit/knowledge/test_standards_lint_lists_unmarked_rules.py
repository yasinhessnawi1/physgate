"""``standards_lint`` (criterion 1's own "a script lists unmarked rules" rung)."""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.knowledge import standards_lint


def test_an_enforced_rule_and_a_judgement_only_rule_are_both_marked() -> None:
    text = (
        "# Title\n\n"
        "## 1. A rule with a named enforcement\n\n"
        "Body text.\n\n"
        "**Enforced:** gate check 1.\n\n"
        "## 2. A rule stated as judgement-only\n\n"
        "Body text.\n\n"
        "**Judgement-only.**\n"
    )
    assert standards_lint.unmarked_rules(text) == ()


def test_a_rule_naming_neither_marker_is_reported() -> None:
    text = (
        "# Title\n\n"
        "## 1. A rule with no marker at all\n\n"
        "Just prose, nothing naming an enforcement or judgement-only.\n\n"
        "## 2. A marked rule\n\n"
        "**Judgement-only.**\n"
    )
    assert standards_lint.unmarked_rules(text) == ("1. A rule with no marker at all",)


def test_judgement_only_with_trailing_text_still_counts_as_marked() -> None:
    text = (
        "## 1. A rule\n\n**Judgement-only** for one part of this rule; the rest is gate-checked.\n"
    )
    assert standards_lint.unmarked_rules(text) == ()


def test_a_file_with_no_numbered_heading_reports_nothing() -> None:
    assert standards_lint.unmarked_rules("# Title\n\nJust prose, no rule headings.\n") == ()


def test_standards_files_lists_every_domain_sorted(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    (root / "b_domain").mkdir(parents=True)
    (root / "a_domain").mkdir(parents=True)
    (root / "a_domain" / "standards.md").write_text("## 1. x\n\n**Judgement-only.**\n")
    (root / "b_domain" / "standards.md").write_text("## 1. y\n\n**Judgement-only.**\n")
    (root / "a_domain" / "skill.md").write_text("not a standards file")
    assert standards_lint.standards_files(root) == (
        root / "a_domain" / "standards.md",
        root / "b_domain" / "standards.md",
    )


def test_a_root_that_does_not_exist_yet_lists_no_files(tmp_path: Path) -> None:
    assert standards_lint.standards_files(tmp_path / "does-not-exist") == ()


def test_report_names_only_files_with_an_unmarked_rule(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    clean = root / "clean"
    dirty = root / "dirty"
    clean.mkdir(parents=True)
    dirty.mkdir(parents=True)
    (clean / "standards.md").write_text("## 1. x\n\n**Enforced:** check 1.\n")
    (dirty / "standards.md").write_text("## 1. y\n\nno marker here.\n")
    findings = standards_lint.report(root)
    assert set(findings) == {dirty / "standards.md"}
    assert findings[dirty / "standards.md"] == ("1. y",)


def test_the_real_promoted_library_has_no_unmarked_rule() -> None:
    """The actual mechanical gate criterion 1 asks for: run over the real library, not a fixture."""
    findings = standards_lint.report()
    assert findings == {}, (
        "every numbered rule in a promoted standards.md must name its enforcement "
        f"or be marked judgement-only; unmarked: {findings}"
    )


def test_main_exits_zero_and_prints_nothing_wrong_when_clean(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = standards_lint.main([])
    assert code == 0
    assert capsys.readouterr().out == "No unmarked rules found.\n"


def test_main_exits_nonzero_and_lists_the_file_when_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "knowledge"
    (root / "d").mkdir(parents=True)
    (root / "d" / "standards.md").write_text("## 1. unmarked\n\nno marker.\n")
    monkeypatch.chdir(tmp_path)
    code = standards_lint.main([])
    assert code == 1
    assert "1. unmarked" in capsys.readouterr().out
