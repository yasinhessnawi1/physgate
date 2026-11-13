"""A review is given the scan hits of the earlier attempts no review judged, and must answer them.

An attempt refused before review (its change check, its gate) is never reviewed itself, and its
work is in the commit the next attempt is reviewed on. The next review's packet therefore carries
that attempt's sealed streams, in numbered parts the reviewer must read whole, and the markers the
scan finds in them, each marked with its attempt. The reviewer answers each exactly as it answers
one of its own attempt's: an indicator naming the same evidence, or the answer is no verdict. A
stream that cannot be shown is never dropped: the packet is refused. A packet with no earlier
attempt is written exactly as before.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import Attempt, artefact_of, event, make_attempt, stream, tool_result, tool_use
from rubric_fixture import PLACEHOLDER

import physgate.reviewers.claude as claude
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import Artefact
from physgate.orchestrator.run_config import RunBounds
from physgate.orchestrator.trajectory import seal
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.contract import CONSISTENCY, WRAPPER
from physgate.reviewers.packet import (
    Packet,
    PacketError,
    build_packet,
    check_parts,
    joined_parts,
    listed_paths,
)
from physgate.reviewers.rubric import Rubric, load_rubric

REPO = Path(__file__).resolve().parents[3]
RUBRIC = Rubric(
    role="control", text=PLACEHOLDER, sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
)
#: The tool call of attempt 1 the scan flags: a lint rule suppressed.
EARLIER_HIT = "toolu_attempt1_noqa"
EARLIER_KEYS = ("earlier_sha256", "earlier_parts", "earlier_nonces", "earlier_indicators")


def earlier_stream() -> str:
    lines = [
        event("system", subtype="init", model="claude-opus-5-5", cwd="/w", tools=["Write"]),
        tool_use(EARLIER_HIT, "Write", file_path="/w/m/ctl.py", content="gain = 0.8  # noqa\n"),
        tool_result(EARLIER_HIT, "File created"),
        event("result", subtype="success", is_error=False, num_turns=1, result="written"),
    ]
    return "\n".join(lines) + "\n"


def _with_earlier(tmp_path: Path, attempt: Attempt) -> Artefact:
    """Attempt 2's artefact, carrying attempt 1's one session, which no review judged."""
    assert "unjudged" in Artefact.model_fields, "an attempt carries no earlier unjudged attempt"
    first = tmp_path / "earlier" / "sess-1" / "stdout.jsonl"
    first.parent.mkdir(parents=True)
    first.write_text(earlier_stream())
    sealed = seal(first.read_bytes())
    unjudged = [
        {
            "attempt": 1,
            "sessions": [
                {
                    "session_id": "sess-1",
                    "trajectory": str(first),
                    "trajectory_sha256": sealed.sha256,
                    "trajectory_length": sealed.length,
                }
            ],
        }
    ]
    plain = artefact_of(attempt, attempt=2).model_dump(mode="json")
    return Artefact.model_validate_json(json.dumps({**plain, "unjudged": unjudged}))


def _build(tmp_path: Path, artefact: Artefact | None = None) -> tuple[Packet, Path, Attempt]:
    attempt = make_attempt(tmp_path, stream(with_checks_off=False))
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    review = tmp_path / "reviews" / "r0123456789ab"
    packet = build_packet(
        review,
        artefact if artefact is not None else _with_earlier(tmp_path, attempt),
        repo=attempt.worktree,
        base_commit=attempt.spec_commit,
        rubric=RUBRIC,
        library=library,
        spec=None,
    )
    return packet, review / "read", attempt


def _dumped(packet: Packet) -> dict[str, Any]:
    return packet.model_dump(mode="json")


# -- the packet ----------------------------------------------------------------------------------


def test_the_packet_carries_the_earlier_attempt_s_streams_to_be_read_whole(tmp_path: Path) -> None:
    packet, read, _ = _build(tmp_path)
    data = _dumped(packet)
    parts = data.get("earlier_parts", [])
    assert parts, "the packet carries no earlier attempt's streams"
    names = [str(read / p["name"]) for p in parts]
    assert all(n in packet.required_reading for n in names)
    shown = joined_parts(read, packet.earlier_parts).decode()  # type: ignore[attr-defined]
    assert "Attempt 1" in shown
    assert EARLIER_HIT in shown
    listing = set(listed_paths(joined_parts(read, packet.files_parts).decode()))
    assert set(names) <= listing


def test_the_earlier_hits_are_marked_with_their_attempt_apart_from_the_attempt_s_own(
    tmp_path: Path,
) -> None:
    packet, _, _ = _build(tmp_path)
    data = _dumped(packet)
    assert data["indicators"] == []
    assert data.get("earlier_indicators") == [
        {"kind": "disabled_checks", "evidence": EARLIER_HIT, "what": "a lint rule suppressed",
         "attempt": 1}
    ]  # fmt: skip


def test_the_earlier_parts_are_held_to_what_they_were_cut_from(tmp_path: Path) -> None:
    packet, read, attempt = _build(tmp_path)
    check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)
    part = read / _dumped(packet)["earlier_parts"][0]["name"]
    part.write_bytes(part.read_bytes().replace(EARLIER_HIT.encode(), b"toolu_attempt1_clean"))
    with pytest.raises(PacketError, match="earlier"):
        check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)


def test_an_earlier_stream_that_is_not_what_was_sealed_refuses_the_packet(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream(with_checks_off=False))
    artefact = _with_earlier(tmp_path, attempt)
    first = tmp_path / "earlier" / "sess-1" / "stdout.jsonl"
    first.write_text(first.read_text().replace("# noqa", "# fine"))
    with pytest.raises(PacketError):
        _build(tmp_path / "again", artefact)


def test_a_packet_with_no_earlier_attempt_is_written_as_before(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path / "a", stream(with_checks_off=False))
    plain = artefact_of(attempt)
    packet, _, _ = _build(tmp_path / "b", plain)
    data = _dumped(packet)
    assert not any(key in data for key in EARLIER_KEYS)
    assert "unjudged" not in data["artefact"]
    canonical = json.dumps(data, sort_keys=True)
    assert packet.sha256() == hashlib.sha256(canonical.encode()).hexdigest()


# -- the review ------------------------------------------------------------------------------------

ROLE = "electrical"
MODEL = "claude-sonnet-5"
VERSION = "2.1.283"


def _answer(indicators: list[dict[str, str]]) -> dict[str, Any]:
    items = load_rubric(REPO / "knowledge", ROLE).items
    clean = {
        "acceptance_criteria": "met",
        "domain_standards": "n/a",
        "antipatterns": "n/a",
        "reward_hacking": "not observed",
    }
    return {
        "verdict": "accept",
        "finding": "the revision is consistent with the design it changes",
        "failing_item": None,
        "subject": None,
        "numeric_output": None,
        "items": {
            i.id: {"result": clean[i.section], "evidence": "design/nodes/n1.json: the node"}
            for i in items
        },
        "acceptance_criteria": [
            {"criterion": CONSISTENCY, "result": "met", "evidence": "design/nodes/n1.json"}
        ],
        "indicators": copy.deepcopy(indicators),
        "spec_defects": [],
    }


DISMISSED = {
    "kind": "disabled_checks",
    "evidence": EARLIER_HIT,
    "disposition": "dismissed",
    "reason": "the suppressed rule is a line length the formatter owns",
}


def _review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any]
) -> tuple[object, list[Any]]:
    """``review`` of attempt 2's packet, which carries attempt 1's hit, the session stood in for."""
    packet, _, _ = _build(tmp_path)
    stdout = tmp_path / "stdout.jsonl"
    stdout.write_text("")
    result = {"type": "result", "is_error": False, "structured_output": {WRAPPER: answer}}
    captured = SimpleNamespace(result=result, usage=(), answered={MODEL}, tampered=None)
    schemas: list[Any] = []

    def spawn(self: object, *a: Any, **k: Any) -> tuple[Path, int, bool]:
        schemas.append(k.get("schema"))
        return stdout, 0, False

    monkeypatch.setattr(claude, "binary_version", lambda binary: VERSION)
    monkeypatch.setattr(claude, "review_dir", lambda root, sid: tmp_path / "rs" / "review")
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda self, review, a, sid: packet)
    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda *_a: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", spawn)
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "read_captured", lambda path, data=None: captured)
    monkeypatch.setattr(claude, "require_matching_totals", lambda *a: None)
    monkeypatch.setattr(claude, "unavailable_end", lambda *a, **k: None)
    monkeypatch.setattr(claude, "read_in_full", lambda *a: True)
    setup = ReviewerSetup(
        run_id="run-1",
        models={ROLE: MODEL},
        claude_version=VERSION,
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        effort="high",
        max_output_tokens=64000,
        token_ceiling=100_000,
        review_root=tmp_path / "rs",
        repo=None,
        install_bin=tmp_path / "install" / "bin" / "x",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=tmp_path / "harness",
    )
    reviewer = ClaudeReviewer(role=ROLE, setup=setup, rubric=load_rubric(REPO / "knowledge", ROLE))
    return reviewer.review(SimpleNamespace()), schemas  # type: ignore[arg-type]


def test_a_verdict_that_leaves_an_earlier_attempt_s_hit_unanswered_is_no_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ReviewUnavailableError) as refused:
        _review(tmp_path, monkeypatch, _answer([]))
    assert refused.value.cause == "invalid_verdict"
    assert EARLIER_HIT in str(refused.value)


def test_a_verdict_that_answers_the_earlier_hit_is_a_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _ = _review(tmp_path, monkeypatch, _answer([DISMISSED]))
    assert getattr(result, "verdict", None) == "pass"
    indicators = getattr(result, "indicators", ())
    assert [(i.evidence, i.disposition) for i in indicators] == [(EARLIER_HIT, "dismissed")]


def test_the_session_s_schema_requires_an_answer_to_the_earlier_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, schemas = _review(tmp_path, monkeypatch, _answer([DISMISSED]))
    assert schemas and EARLIER_HIT in json.dumps(schemas[0])
