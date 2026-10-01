"""``promote.py`` (ARCH-100): the library's only writer, and it refuses unless interactive.

Two guards are tested separately, deliberately: `require_interactive` (this
file's own section) proves the refusal by itself, with no other logic
around it to obscure what is actually being checked; `_apply` (the second
section) proves the write and the ledger event by itself, with no terminal
needed, since nothing about *that* logic should depend on a TTY. `promote`
(the third section) proves the two are wired together — remove the call to
`require_interactive` from it, and the "refuses non-interactively" case
there is the one test that goes red.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from physgate.knowledge import staging
from physgate.knowledge.promote import (
    PromotionError,
    _apply,
    promote,
    promotions,
    require_interactive,
)


class _Stdin:
    """A stand-in for ``sys.stdin`` whose ``isatty()`` is fixed at construction."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_require_interactive_refuses_when_stdin_is_not_a_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin", _Stdin(tty=False))
    with pytest.raises(PromotionError, match="non-interactively"):
        require_interactive()


def test_require_interactive_allows_a_real_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    require_interactive()  # does not raise


def test_a_pipe_or_a_redirected_file_is_not_a_terminal_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real failure mode this guards against: a script or an agent session
    # piping input in, not a human typing at a prompt. io.StringIO.isatty()
    # is always False, the same as a real pipe or redirected file.
    monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))
    with pytest.raises(PromotionError):
        require_interactive()


# --- _apply: the write and the ledger event, with no terminal involved -----------------


def _stage(
    tmp_path: Path, kind: staging.Kind, domain: str, content: str, episode: str = "ep-1"
) -> str:
    path = staging.append(kind, content, episode, domain=domain, staging_root=tmp_path / "staging")
    return path.stem


def test_a_standards_candidate_creates_the_domain_standards_file(tmp_path: Path) -> None:
    candidate_id = _stage(tmp_path, "standards", "control", "# Control — standards\n\ncontent\n")
    destination = _apply(
        candidate_id,
        by="yasin",
        staging_root=tmp_path / "staging",
        knowledge_root=tmp_path / "knowledge",
        promotions_path=tmp_path / "knowledge" / "promotions.jsonl",
    )
    assert destination == tmp_path / "knowledge" / "control" / "standards.md"
    assert destination.read_text() == "# Control — standards\n\ncontent\n"


def test_a_skill_candidate_creates_skill_md_when_none_exists(tmp_path: Path) -> None:
    candidate_id = _stage(tmp_path, "skill", "firmware", "# Firmware — skill\n\nfirst\n")
    destination = _apply(
        candidate_id,
        by="yasin",
        staging_root=tmp_path / "staging",
        knowledge_root=tmp_path / "knowledge",
        promotions_path=tmp_path / "knowledge" / "promotions.jsonl",
    )
    assert destination.read_text() == "# Firmware — skill\n\nfirst\n"


def test_a_second_skill_or_antipattern_candidate_is_appended_not_overwritten(
    tmp_path: Path,
) -> None:
    knowledge_root = tmp_path / "knowledge"
    staging_root = tmp_path / "staging"
    promotions_path = knowledge_root / "promotions.jsonl"
    first = _stage(tmp_path, "skill", "control", "first entry\n")
    _apply(
        first,
        by="yasin",
        staging_root=staging_root,
        knowledge_root=knowledge_root,
        promotions_path=promotions_path,
    )
    second = _stage(tmp_path, "antipattern", "control", "second entry\n")
    destination = _apply(
        second,
        by="yasin",
        staging_root=staging_root,
        knowledge_root=knowledge_root,
        promotions_path=promotions_path,
    )
    text = destination.read_text()
    assert "first entry" in text and "second entry" in text
    assert text.index("first entry") < text.index("second entry")


def test_a_standards_candidate_replaces_an_existing_standards_file_whole(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "knowledge"
    staging_root = tmp_path / "staging"
    promotions_path = knowledge_root / "promotions.jsonl"
    first = _stage(tmp_path, "standards", "control", "old draft\n")
    destination = _apply(
        first,
        by="yasin",
        staging_root=staging_root,
        knowledge_root=knowledge_root,
        promotions_path=promotions_path,
    )
    second = _stage(tmp_path, "standards", "control", "revised draft\n")
    _apply(
        second,
        by="yasin",
        staging_root=staging_root,
        knowledge_root=knowledge_root,
        promotions_path=promotions_path,
    )
    assert destination.read_text() == "revised draft\n"
    assert "old draft" not in destination.read_text()


def test_promoting_writes_one_ledger_event_naming_the_human(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "knowledge"
    promotions_path = knowledge_root / "promotions.jsonl"
    candidate_id = _stage(tmp_path, "skill", "control", "content\n", episode="ep-42")
    _apply(
        candidate_id,
        by="yasin",
        staging_root=tmp_path / "staging",
        knowledge_root=knowledge_root,
        promotions_path=promotions_path,
    )
    (event,) = promotions(promotions_path)
    assert event["candidate_id"] == candidate_id
    assert event["kind"] == "skill"
    assert event["domain"] == "control"
    assert event["episode_id"] == "ep-42"
    assert event["promoted_by"] == "yasin"
    assert event["destination"].endswith("control/skill.md")
    assert event["promoted"]


def test_a_promoted_candidate_is_removed_from_staging(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    candidate_id = _stage(tmp_path, "skill", "control", "content\n")
    assert staging.candidates("skill", staging_root=staging_root) != ()
    _apply(
        candidate_id,
        by="yasin",
        staging_root=staging_root,
        knowledge_root=tmp_path / "knowledge",
        promotions_path=tmp_path / "knowledge" / "promotions.jsonl",
    )
    assert staging.candidates("skill", staging_root=staging_root) == ()


def test_promoting_an_unknown_or_already_promoted_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PromotionError, match="no staged candidate"):
        _apply(
            "does-not-exist",
            by="yasin",
            staging_root=tmp_path / "staging",
            knowledge_root=tmp_path / "knowledge",
            promotions_path=tmp_path / "knowledge" / "p.jsonl",
        )


def test_an_empty_approver_name_is_refused_before_any_write(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    knowledge_root = tmp_path / "knowledge"
    candidate_id = _stage(tmp_path, "skill", "control", "content\n")
    with pytest.raises(PromotionError, match="name"):
        _apply(
            candidate_id,
            by="   ",
            staging_root=staging_root,
            knowledge_root=knowledge_root,
            promotions_path=knowledge_root / "promotions.jsonl",
        )
    assert not knowledge_root.exists()  # refused before creating anything
    assert staging.candidates("skill", staging_root=staging_root) != ()  # still staged


def test_no_promotions_file_yet_reports_no_promotions(tmp_path: Path) -> None:
    assert promotions(tmp_path / "knowledge" / "promotions.jsonl") == ()


# --- promote: the two guards wired together --------------------------------------------


def test_promote_refuses_non_interactively_even_with_a_valid_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", _Stdin(tty=False))
    staging_root = tmp_path / "staging"
    candidate_id = _stage(tmp_path, "skill", "control", "content\n")
    with pytest.raises(PromotionError, match="non-interactively"):
        promote(
            candidate_id,
            by="yasin",
            staging_root=staging_root,
            knowledge_root=tmp_path / "knowledge",
        )
    # Refused before ever reaching the write: still staged, nothing created.
    assert staging.candidates("skill", staging_root=staging_root) != ()
    assert not (tmp_path / "knowledge").exists()


def test_promote_succeeds_when_stdin_is_a_real_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    candidate_id = _stage(tmp_path, "skill", "control", "content\n")
    destination = promote(
        candidate_id,
        by="yasin",
        staging_root=tmp_path / "staging",
        knowledge_root=tmp_path / "knowledge",
    )
    assert destination.read_text() == "content\n"


def test_promote_defaults_the_promotions_path_under_knowledge_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    candidate_id = _stage(tmp_path, "skill", "control", "content\n")
    promote(
        candidate_id,
        by="yasin",
        staging_root=tmp_path / "staging",
        knowledge_root=tmp_path / "knowledge",
    )
    (event,) = promotions(tmp_path / "knowledge" / "promotions.jsonl")
    assert event["promoted_by"] == "yasin"
