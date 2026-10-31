"""A plan's review refuses from the one read its record is written from, and holds its copies.

The stream is read once, held to its seal, and the models it shows answering go on the packet's
record from that read. A stream one of whose answering models is the reviewer's own is refused
there, before anything is written, so a refusal leaves no packet behind; and nothing reads the
stream again once the packet is checked. The check holds the rubric and every library copy to the
digest the record gives it, not only to the listing's sizes, and the brief is issued in lines no
longer than one read shows, held joined again to the brief itself.

The protocol a plan reviewer meets is the orchestrator's, beside the role reviewer's.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from plan_fixture import (
    BRIEF,
    DECOMPOSITION,
    REPO,
    REVIEWER,
    design_rubric,
    module,
    stream_text,
    under_review,
)
from test_a_design_review_call_on_the_decomposition_model_is_refused import _design, _Watched

import physgate.orchestrator.protocols as protocols
import physgate.reviewers.claude as claude
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.exceptions import ModelSeparationError
from physgate.reviewers.claude import ClaudeReviewer
from physgate.reviewers.contract import WRAPPER
from physgate.reviewers.packet import KNOWLEDGE_NAME, RUBRIC_NAME, PacketError
from physgate.reviewers.transcript import CONTINUED, WIDTH, joined


def outcome_of(how: Callable[[], Any]) -> Any:  # noqa: ANN401 - whatever came of it
    """What ``how`` returned, or the exception it raised: a test asserts on either."""
    try:
        return how()
    except Exception as exc:  # noqa: BLE001 - the escape is what the test asserts on
        return exc


def _build(tmp_path: Path, under: Any = None, model: str = REVIEWER) -> Any:  # noqa: ANN401
    under = under if under is not None else under_review(tmp_path)
    review = tmp_path / "reviews" / "r1"
    return outcome_of(
        lambda: module("plan_packet").build_plan_packet(
            review, under, rubric=design_rubric(), library=REPO, reviewer_model=model
        )
    )


def _read(tmp_path: Path) -> Path:
    return tmp_path / "reviews" / "r1" / "read"


def test_the_plan_reviewer_s_protocol_is_the_orchestrator_s() -> None:
    reviewer_protocol = getattr(protocols, "PlanReviewer", None)
    under = getattr(protocols, "PlanUnderReview", None)
    assert reviewer_protocol is not None, "the orchestrator states no plan reviewer"
    assert under is not None, "the plan under review is not the orchestrator's"
    assert module("plan_packet").PlanUnderReview is under


def test_the_design_reviewer_is_a_plan_reviewer(tmp_path: Path) -> None:
    reviewer_protocol = getattr(protocols, "PlanReviewer", None)
    assert reviewer_protocol is not None
    assert isinstance(_design(tmp_path, REVIEWER), reviewer_protocol)
    assert not isinstance(SimpleNamespace(model=REVIEWER), reviewer_protocol)


def test_the_packet_records_the_models_its_one_read_of_the_stream_shows(tmp_path: Path) -> None:
    packet = _build(tmp_path)
    assert not isinstance(packet, Exception), packet
    assert getattr(packet, "answering_models", None) == (DECOMPOSITION,)
    module("plan_packet").check_plan_packet(packet, under_review(tmp_path))


def test_a_stream_its_reviewer_answered_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    under = under_review(tmp_path, stream_text=stream_text(model=REVIEWER))
    refused = _build(tmp_path, under)
    assert isinstance(refused, ModelSeparationError), refused
    assert not (tmp_path / "reviews").exists()


def test_a_record_naming_other_answering_models_is_refused_at_the_check(tmp_path: Path) -> None:
    packet = _build(tmp_path)
    assert not isinstance(packet, Exception), packet
    forged = packet.model_copy(update={"answering_models": ("claude-haiku-4-5",)})
    refused = outcome_of(
        lambda: module("plan_packet").check_plan_packet(forged, under_review(tmp_path))
    )
    assert isinstance(refused, PacketError), refused
    assert "answering" in str(refused)


def test_the_review_reads_the_stream_no_more_once_its_packet_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = _Watched(monkeypatch)
    checked = claude.check_plan_packet

    def then_changed(packet: Any, under: Any) -> None:  # noqa: ANN401
        checked(packet, under)
        Path(under.stream).write_text(stream_text() + "{}\n")

    monkeypatch.setattr(claude, "check_plan_packet", then_changed)
    got = outcome_of(lambda: _design(tmp_path, REVIEWER).review_plan(under_review(tmp_path)))
    # The packet holds the copies the review reads: the stream on disk is read no more.
    assert got == "reached", got
    assert len(watched.sessions) == 1


def test_a_rubric_changed_after_the_build_is_refused_at_the_check(tmp_path: Path) -> None:
    packet = _build(tmp_path)
    assert not isinstance(packet, Exception), packet
    rubric = _read(tmp_path) / RUBRIC_NAME
    body = rubric.read_bytes()
    rubric.write_bytes(body[:-1] + (b"x" if body[-1:] != b"x" else b"y"))  # the same size
    refused = outcome_of(
        lambda: module("plan_packet").check_plan_packet(packet, under_review(tmp_path))
    )
    assert isinstance(refused, PacketError), refused
    assert "rubric" in str(refused)


def _copies(tmp_path: Path) -> list[Path]:
    probe = tmp_path / "probe"
    built = _build(probe)
    assert not isinstance(built, Exception), built
    copies = sorted(p for p in (_read(probe) / KNOWLEDGE_NAME).rglob("*") if p.is_file())
    assert copies, "the packet issued no library copy"
    return [p.relative_to(_read(probe)) for p in copies]


def test_every_library_copy_changed_after_the_build_is_refused_at_the_check(
    tmp_path: Path,
) -> None:
    for number, copy in enumerate(_copies(tmp_path)):
        root = tmp_path / f"copy-{number}"
        packet = _build(root)
        assert not isinstance(packet, Exception), packet
        path = _read(root) / copy
        body = path.read_bytes()
        path.write_bytes(body[:-1] + (b"x" if body[-1:] != b"x" else b"y"))  # the same size
        refused = outcome_of(
            lambda root=root, packet=packet: module("plan_packet").check_plan_packet(
                packet, under_review(root)
            )
        )
        assert isinstance(refused, PacketError), (copy, refused)
        assert "library" in str(refused), (copy, refused)


LONG = "x" * (2 * WIDTH + 500)
LONG_BRIEF = BRIEF + "\n" + LONG + "\n"


def _long(tmp_path: Path) -> Any:  # noqa: ANN401
    return under_review(
        tmp_path,
        brief=LONG_BRIEF,
        brief_sha256=hashlib.sha256(LONG_BRIEF.encode()).hexdigest(),
    )


def test_a_long_brief_line_is_issued_in_lines_one_read_shows_whole(tmp_path: Path) -> None:
    under = _long(tmp_path)
    packet = _build(tmp_path, under)
    assert not isinstance(packet, Exception), packet
    text = b"".join((_read(tmp_path) / p.name).read_bytes() for p in packet.brief_parts).decode()
    assert max(len(line) for line in text.split("\n")) <= WIDTH + len(CONTINUED)
    assert joined(text) == LONG_BRIEF
    module("plan_packet").check_plan_packet(packet, under)


def test_a_cut_brief_line_changed_after_the_build_is_refused_at_the_check(tmp_path: Path) -> None:
    under = _long(tmp_path)
    packet = _build(tmp_path, under)
    assert not isinstance(packet, Exception), packet
    # The brief as the run recorded it, issued raw, rejoins to itself: the check refuses it for
    # not being the brief cut as the harness cuts it.
    part = _read(tmp_path) / packet.brief_parts[0].name
    raw = LONG_BRIEF.encode()
    part.write_bytes(raw)
    forged = packet.model_copy(
        update={
            "brief_parts": (
                packet.brief_parts[0].model_copy(
                    update={
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "bytes": len(raw),
                        "lines": len(raw.splitlines()),
                    }
                ),
            )
        }
    )
    refused = outcome_of(lambda: module("plan_packet").check_plan_packet(forged, under))
    assert isinstance(refused, PacketError), refused


def test_a_brief_that_already_holds_the_cut_mark_is_refused(tmp_path: Path) -> None:
    marked = BRIEF + "a line" + CONTINUED + "\nits end\n"
    under = under_review(
        tmp_path, brief=marked, brief_sha256=hashlib.sha256(marked.encode()).hexdigest()
    )
    refused = _build(tmp_path, under)
    assert isinstance(refused, PacketError), refused
    assert not (tmp_path / "reviews").exists()


def _answer(criteria: tuple[str, ...]) -> dict[str, Any]:
    clean = {
        "acceptance_criteria": "met",
        "domain_standards": "n/a",
        "antipatterns": "n/a",
        "reward_hacking": "not observed",
    }
    return {
        "verdict": "accept",
        "finding": "the plan carries the brief across its modules and interfaces",
        "failing_item": None,
        "subject": None,
        "numeric_output": None,
        "items": {
            i.id: {"result": clean[i.section], "evidence": "plan-01-of-01.md: module 1 of 2"}
            for i in design_rubric().items
        },
        "acceptance_criteria": [
            {"criterion": c, "result": "met", "evidence": "plan-01-of-01.md: module 1"}
            for c in criteria
        ],
        "indicators": [],
        "spec_defects": [],
    }


def test_a_plan_review_reaches_a_verdict_through_the_session_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the binary's own input and output are stand-ins: the session path, the reading check's
    # caller, the verdict's judge and the result are the review's own.
    monkeypatch.setattr(claude, "binary_version", lambda binary: "2.1.301")
    stdout = tmp_path / "stdout.jsonl"
    stdout.write_text("")
    result = {
        "type": "result",
        "is_error": False,
        "structured_output": {WRAPPER: _answer(("1", "2"))},
    }
    captured = SimpleNamespace(result=result, usage=(), answered={REVIEWER}, tampered=None)
    seen: dict[str, Any] = {}

    def spawn(self: object, packet: Any, sdir: Path, installed: Any, sid: str, **kw: Any) -> Any:  # noqa: ANN401
        seen.update(kw, packet=packet)
        return (stdout, 0, False)

    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda self, p, sdir: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", spawn)
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "read_captured", lambda path, data=None: captured)
    monkeypatch.setattr(claude, "require_matching_totals", lambda *a: None)
    monkeypatch.setattr(claude, "unavailable_end", lambda *a, **k: None)
    monkeypatch.setattr(claude, "read_in_full", lambda *a: True)
    got = _design(tmp_path, REVIEWER).review_plan(under_review(tmp_path))
    assert got.verdict == "pass", got
    assert got.reviewer_model == REVIEWER
    assert got.packet_sha256 == seen["packet"].sha256()
    assert got.rubric_sha256 == design_rubric().sha256
    assert [c.criterion for c in got.criteria] == ["1", "2"]
    assert "plan-01-of-" in seen["prompt"]
