"""A promotion reads, writes and records exactly what it checked, with no window for a link.

Each check-then-use pair in promotion is exercised with the swap a racing writer
would make, placed in the window between the check and the use:

- the staged candidate is replaced by a link to another candidate after it was
  found and before it is read;
- the destination's directory is replaced by a link to somewhere outside the
  library after the destination was checked and before it is written;
- the destination is changed after it was written and before its digest is taken;
- the promotion record is a link to a file elsewhere.

In every case the promotion is refused, or records exactly the bytes it wrote,
and nothing outside the library is touched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from rubric_fixture import PLACEHOLDER

from physgate.knowledge import promote as promotion
from physgate.knowledge import staging
from physgate.knowledge.promote import PromotionError, _apply, rubric_path

OTHER = PLACEHOLDER.replace("Used by the test suite only.", "A substituted version.")


def _apply_in(root: Path, candidate_id: str) -> Path:
    return _apply(
        candidate_id,
        by="a person",
        staging_root=root / staging.STAGING_ROOT,
        knowledge_root=root / "knowledge",
        promotions_path=root / "knowledge" / "promotions.jsonl",
        rubric_staging_root=root / staging.RUBRIC_STAGING_ROOT,
    )


def _stage(root: Path, text: str = PLACEHOLDER) -> Path:
    return staging.append(
        "rubric", text, "e1", domain="control", staging_root=root / staging.RUBRIC_STAGING_ROOT
    )


def test_a_staged_file_swapped_for_a_link_after_it_was_found_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _stage(tmp_path)
    decoy = _stage(tmp_path, OTHER)
    outside = tmp_path / "outside.json"
    decoy.rename(outside)
    swapped: list[Path] = []
    real_is_file = Path.is_file

    def racing_is_file(self: Path) -> bool:
        found = real_is_file(self)
        if self == staged and not swapped:
            staged.unlink()
            staged.symlink_to(outside)
            swapped.append(self)
        return found

    monkeypatch.setattr(Path, "is_file", racing_is_file)
    with pytest.raises(PromotionError, match="link"):
        _apply_in(tmp_path, staged.stem)
    assert swapped, "the swap never happened, so the test saw nothing"
    assert not rubric_path(tmp_path / "knowledge", "control").exists()


def test_a_directory_swapped_for_a_link_after_the_check_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _stage(tmp_path)
    destination = rubric_path(tmp_path / "knowledge", "control")
    destination.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    real_check = promotion._refuse_links
    swapped: list[Path] = []

    def racing_check(dest: Path, root: Path) -> None:
        real_check(dest, root)
        destination.parent.rmdir()
        destination.parent.symlink_to(outside)
        swapped.append(dest)

    monkeypatch.setattr(promotion, "_refuse_links", racing_check)
    with pytest.raises(PromotionError, match="link"):
        _apply_in(tmp_path, staged.stem)
    assert swapped, "the swap never happened, so the test saw nothing"
    assert list(outside.iterdir()) == []


def test_the_digest_is_of_the_bytes_written_not_of_a_later_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _stage(tmp_path)
    destination = rubric_path(tmp_path / "knowledge", "control")
    real_read_bytes = Path.read_bytes

    def racing_read_bytes(self: Path) -> bytes:
        if self == destination:
            return OTHER.encode()
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", racing_read_bytes)
    _apply_in(tmp_path, staged.stem)
    line: dict[str, Any] = json.loads((tmp_path / "knowledge" / "promotions.jsonl").read_text())
    written = (PLACEHOLDER.rstrip() + "\n").encode()
    assert line["sha256"] == hashlib.sha256(written).hexdigest()


def test_a_promotion_record_that_is_a_link_is_refused(tmp_path: Path) -> None:
    staged = _stage(tmp_path)
    elsewhere = tmp_path / "elsewhere.jsonl"
    elsewhere.write_text("")
    record = tmp_path / "knowledge" / "promotions.jsonl"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.symlink_to(elsewhere)
    with pytest.raises(PromotionError, match="link"):
        _apply_in(tmp_path, staged.stem)
    assert elsewhere.read_text() == ""


def test_a_live_rubric_that_is_a_link_is_never_loaded(tmp_path: Path) -> None:
    from physgate.reviewers.rubric import RubricError, load_rubric

    staged = _stage(tmp_path)
    destination = _apply_in(tmp_path, staged.stem)
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_bytes(destination.read_bytes())
    destination.unlink()
    destination.symlink_to(elsewhere)
    with pytest.raises(RubricError, match="link"):
        load_rubric(tmp_path / "knowledge", "control")
