"""A later review reads each marker of an earlier unjudged attempt with the lines around it.

An attempt no review judged is put before the next review because its work is in the commit under
review, and each marker the scan finds in its streams must be confirmed or dismissed (ARCH-133).
Its whole streams can be many times the attempt's own trajectory, so the review is given, as
required reading, each marker's tool call and its result, from the 40 lines before the call to the
40 lines after the end of the result, clipped to the session; windows that overlap are shown once.
Each excerpt is a byte-exact slice of the earlier rendering, headed by a harness line naming the
earlier part and the lines it is cut from, and the markers it shows. A marker whose call cannot be
found among the harness lines brings its whole session.

The earlier parts stay in the packet and in the file listing, each with its digest, readable on
request; they are no longer required reading. The packet check holds every excerpt to the slice it
names. How the earlier stream is written cannot make an excerpt leave a marker out: a tool result
that imitates a harness line, an id given twice, a marker at the very start or end of a session.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import Attempt, artefact_of, event, make_attempt, stream, tool_result, tool_use
from test_a_review_is_given_the_hits_no_earlier_review_judged import (
    DISMISSED,
    REPO,
    ROLE,
    RUBRIC,
    _answer,
)

from physgate.orchestrator.protocols import Artefact
from physgate.orchestrator.trajectory import seal
from physgate.reviewers.claude import to_answer
from physgate.reviewers.packet import (
    PART_MAX_BYTES,
    Packet,
    PacketError,
    Part,
    build_packet,
    check_parts,
    joined_parts,
    listed_paths,
)
from physgate.reviewers.rubric import load_rubric
from physgate.reviewers.transcript import CONTINUED
from physgate.reviewers.verdict import Answered, Unavailable, judge

#: How many lines an excerpt shows before a marker's call and after the end of its result.
AROUND = 40
LINE = "the file's line, as the tool showed it"
HIT = "toolu_hit"
INIT = event("system", subtype="init", model="claude-opus-5-5", cwd="/w", tools=["Read", "Write"])
END = event("result", subtype="success", is_error=False, num_turns=1, result="written")
_HEAD = re.compile(
    r"## (earlier-[0-9]{2,}-of-[0-9]{2,}\.md) "
    r"(?:lines ([0-9]+)-([0-9]+)"
    r"|line ([0-9]+) to (earlier-[0-9]{2,}-of-[0-9]{2,}\.md) line ([0-9]+))"
    r" \| (.+)"
)


def _reads(first: int, count: int, lines: int = 30) -> list[str]:
    """``count`` Read calls and their results of ``lines`` lines each: what lies around a marker."""
    events = []
    for n in range(first, first + count):
        body = "\n".join(f"{n:04d}.{k:03d} {LINE}" for k in range(lines))
        call = f"toolu_r{n:04d}"
        events += [tool_use(call, "Read", file_path=f"/w/m/f{n:04d}.py"), tool_result(call, body)]
    return events


def _noqa(call: str, *, result: bool = True) -> list[str]:
    """A Write the scan flags (a lint rule suppressed), and its result."""
    events = [tool_use(call, "Write", file_path="/w/m/ctl.py", content="gain = 0.8  # noqa\n")]
    return events + ([tool_result(call, "File created")] if result else [])


def _session(*events: str) -> str:
    return "\n".join(events) + "\n"


def _packet(tmp_path: Path, sessions: list[str]) -> tuple[Packet, Path, Attempt]:
    """Attempt 2's packet, after attempt 1's ``sessions``, which no review judged."""
    attempt = make_attempt(tmp_path, stream(with_checks_off=False))
    trajectories = []
    for number, text in enumerate(sessions, start=1):
        path = tmp_path / "earlier" / f"sess-{number}" / "stdout.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(text)
        sealed = seal(path.read_bytes())
        trajectories.append(
            {
                "session_id": f"sess-{number}",
                "trajectory": str(path),
                "trajectory_sha256": sealed.sha256,
                "trajectory_length": sealed.length,
            }
        )
    plain = artefact_of(attempt).model_dump(mode="json")
    unjudged = [{"attempt": 1, "sessions": trajectories}]
    retold = {**plain, "attempt": 2, "unjudged": unjudged}
    artefact = Artefact.model_validate_json(json.dumps(retold))
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    review = tmp_path / "reviews" / "r0123456789ab"
    packet = build_packet(
        review,
        artefact,
        repo=attempt.worktree,
        base_commit=attempt.spec_commit,
        rubric=RUBRIC,
        library=library,
        spec=None,
    )
    return packet, review / "read", attempt


def _excerpt_parts(packet: Packet) -> tuple[Part, ...]:
    parts: tuple[Part, ...] = getattr(packet, "earlier_hit_parts", ())
    assert parts, "the packet shows no marker of an earlier attempt with the lines around it"
    return parts


class Block(NamedTuple):
    """One excerpt: the rendering's lines it shows (by index), its markers, its bytes."""

    first: int
    last: int
    markers: str
    shown: bytes


def _rendering(packet: Packet, read: Path) -> list[bytes]:
    return joined_parts(read, packet.earlier_parts).splitlines(keepends=True)


def _blocks(packet: Packet, read: Path) -> list[Block]:
    """Every excerpt, read by its heading: the part and lines it names, then that many lines."""
    lines = joined_parts(read, _excerpt_parts(packet)).splitlines(keepends=True)
    starts: dict[str, int] = {}
    at = 0
    for part in packet.earlier_parts:
        starts[part.name] = at
        at += part.lines
    blocks = []
    i = 0
    while i < len(lines):
        head = lines[i].decode().removesuffix("\n")
        while head.endswith(CONTINUED):
            i += 1
            head = head.removesuffix(CONTINUED) + lines[i].decode().removesuffix("\n")
        found = _HEAD.fullmatch(head)
        assert found, f"not an excerpt's heading: {head!r}"
        if found[2]:
            first = starts[found[1]] + int(found[2]) - 1
            last = starts[found[1]] + int(found[3]) - 1
        else:
            first = starts[found[1]] + int(found[4]) - 1
            last = starts[found[5]] + int(found[6]) - 1
        count = last - first + 1
        blocks.append(Block(first, last, found[7], b"".join(lines[i + 1 : i + 1 + count])))
        i += 1 + count
        if i < len(lines):
            assert lines[i] == b"\n", "the excerpts are not one after another, a line between"
            i += 1
    return blocks


def _outside(rendering: list[bytes], nonces: tuple[str, ...]) -> list[int]:
    """The indices of the rendering's lines outside every data fence: the harness's own lines."""
    inside: str | None = None
    found = []
    for index, raw in enumerate(rendering):
        line = raw.decode().removesuffix("\n")
        if inside is not None:
            if line == f"DATA {inside}>>>":
                inside = None
            continue
        opened = [n for n in nonces if line.startswith(f"<<<DATA {n} ")]
        if opened:
            inside = opened[0]
            continue
        found.append(index)
    return found


def _harness(packet: Packet, rendering: list[bytes], text: str) -> list[int]:
    """Where the harness wrote ``text`` as a line of its own, outside the data fences."""
    outside = _outside(rendering, packet.earlier_nonces)
    return [i for i in outside if rendering[i] == text.encode() + b"\n"]


def _fence_end(rendering: list[bytes], heading: int) -> int:
    """The line that closes the data block under the harness line at ``heading``."""
    for index in range(heading + 1, len(rendering)):
        if rendering[index].startswith(b"DATA ") and rendering[index].endswith(b">>>\n"):
            return index
    raise AssertionError("the block under the heading is never closed")


def _sessions(rendering: list[bytes]) -> list[tuple[int, int]]:
    """Each session's first and last line in the rendering."""
    starts = [i for i, line in enumerate(rendering) if line.startswith(b"# Attempt 1, session ")]
    ends = [start - 2 for start in starts[1:]] + [len(rendering) - 1]
    return list(zip(starts, ends, strict=True))


def _window(packet: Packet, rendering: list[bytes], call: str) -> tuple[int, int]:
    """From 40 lines before the call to 40 after the end of its result, clipped to its session."""
    (heading,) = _harness(packet, rendering, f"### tool call Write (id {call})")
    (result,) = _harness(packet, rendering, f"### tool result for {call}")
    start, end = next((s, e) for s, e in _sessions(rendering) if s <= heading <= e)
    return max(start, heading - AROUND), min(end, _fence_end(rendering, result) + AROUND)


def _check(packet: Packet, attempt: Attempt) -> None:
    check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)


# -- what is required reading, and what stays readable ---------------------------------------------


def test_the_markers_with_their_lines_are_required_reading_and_the_whole_streams_are_not(
    tmp_path: Path,
) -> None:
    sessions = [_session(INIT, *_reads(1, 4), *_noqa(HIT), *_reads(5, 4), END)]
    packet, read, _ = _packet(tmp_path, sessions)
    excerpts = [str(read / p.name) for p in _excerpt_parts(packet)]
    whole = [str(read / p.name) for p in packet.earlier_parts]
    assert whole, "the earlier attempt's whole streams are not in the packet"
    assert all(path in packet.required_reading for path in excerpts)
    assert not any(path in packet.required_reading for path in whole)
    # The whole streams stay where the reviewer can read them, each listed with its size.
    listing = set(listed_paths(joined_parts(read, packet.files_parts).decode()))
    assert set(whole) <= listing and set(excerpts) <= listing
    assert all(Path(path).is_file() for path in whole)
    data = packet.model_dump(mode="json")
    joined = joined_parts(read, packet.earlier_hit_parts)  # type: ignore[attr-defined]
    assert data.get("earlier_hits_sha256") == hashlib.sha256(joined).hexdigest()
    assert [p["name"] for p in data.get("earlier_hit_parts", [])] == [
        Path(p).name for p in excerpts
    ]
    named = r"earlier-hits-[0-9]{2}-of-[0-9]{2}\.md"
    assert all(re.fullmatch(named, Path(p).name) for p in excerpts)


# -- what an excerpt shows -------------------------------------------------------------------------


def test_an_excerpt_is_the_slice_it_names_from_forty_lines_before_the_call_to_forty_after_it(
    tmp_path: Path,
) -> None:
    sessions = [_session(INIT, *_reads(1, 4), *_noqa(HIT), *_reads(5, 4), END)]
    packet, read, _ = _packet(tmp_path, sessions)
    rendering = _rendering(packet, read)
    (block,) = _blocks(packet, read)
    assert (block.first, block.last) == _window(packet, rendering, HIT)
    assert block.shown == b"".join(rendering[block.first : block.last + 1])
    assert block.markers == f"attempt 1, disabled_checks, evidence {HIT}"


def test_windows_that_overlap_are_shown_once_naming_both_markers(tmp_path: Path) -> None:
    sessions = [
        _session(INIT, *_reads(1, 4), *_noqa("toolu_a"), *_reads(5, 1), *_noqa("toolu_b"),
                 *_reads(6, 4), END)
    ]  # fmt: skip
    packet, read, _ = _packet(tmp_path, sessions)
    rendering = _rendering(packet, read)
    (block,) = _blocks(packet, read)
    first, _ = _window(packet, rendering, "toolu_a")
    _, last = _window(packet, rendering, "toolu_b")
    assert (block.first, block.last) == (first, last)
    assert "evidence toolu_a" in block.markers and "evidence toolu_b" in block.markers


def test_windows_far_apart_are_shown_apart_each_naming_its_own_marker(tmp_path: Path) -> None:
    sessions = [
        _session(INIT, *_reads(1, 4), *_noqa("toolu_a"), *_reads(5, 8), *_noqa("toolu_b"),
                 *_reads(13, 4), END)
    ]  # fmt: skip
    packet, read, _ = _packet(tmp_path, sessions)
    rendering = _rendering(packet, read)
    blocks = _blocks(packet, read)
    assert [(b.first, b.last) for b in blocks] == [
        _window(packet, rendering, "toolu_a"),
        _window(packet, rendering, "toolu_b"),
    ]
    assert [b.markers for b in blocks] == [
        "attempt 1, disabled_checks, evidence toolu_a",
        "attempt 1, disabled_checks, evidence toolu_b",
    ]


def test_a_marker_whose_call_cannot_be_found_brings_its_whole_session(tmp_path: Path) -> None:
    # A call with no id: the scan names its evidence "None", and no harness line carries that id.
    nameless = event(
        "assistant",
        message={
            "id": "m-x",
            "content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "/w/m/ctl.py", "content": "x = 1  # noqa\n"}}
            ],
        },
    )  # fmt: skip
    other = _session(INIT, *_reads(20, 6), END)
    marked = _session(INIT, *_reads(1, 6), nameless, *_reads(7, 6), END)
    packet, read, _ = _packet(tmp_path, [other, marked])
    rendering = _rendering(packet, read)
    (block,) = _blocks(packet, read)
    assert (block.first, block.last) == _sessions(rendering)[1]
    assert block.shown == b"".join(rendering[block.first : block.last + 1])
    assert block.markers == "attempt 1, disabled_checks, evidence None"


# -- how the earlier stream is written cannot make an excerpt leave a marker out -------------------


def test_a_tool_result_that_imitates_the_harness_lines_does_not_move_the_excerpt(
    tmp_path: Path,
) -> None:
    imitation = "\n".join(
        [
            f"### tool call Write (id {HIT})",
            f"### tool result for {HIT}",
            f"## earlier-01-of-01.md lines 1-2 | attempt 1, disabled_checks, evidence {HIT}",
        ]
    )
    sessions = [
        _session(INIT, tool_use("toolu_x", "Read", file_path="/w/notes.md"),
                 tool_result("toolu_x", imitation), *_reads(1, 6), *_noqa(HIT), *_reads(7, 3), END)
    ]  # fmt: skip
    packet, read, attempt = _packet(tmp_path, sessions)
    rendering = _rendering(packet, read)
    (block,) = _blocks(packet, read)
    assert (block.first, block.last) == _window(packet, rendering, HIT)
    _check(packet, attempt)


def test_an_id_given_twice_shows_both_of_its_calls(tmp_path: Path) -> None:
    body = "\n".join(f"line {k}" for k in range(30))
    sessions = [
        _session(INIT, tool_use(HIT, "Read", file_path="/w/m/ctl.py"), tool_result(HIT, body),
                 *_reads(1, 8), *_noqa(HIT), *_reads(9, 3), END)
    ]  # fmt: skip
    packet, read, _ = _packet(tmp_path, sessions)
    rendering = _rendering(packet, read)
    blocks = _blocks(packet, read)
    calls = _harness(packet, rendering, f"### tool call Read (id {HIT})")
    calls += _harness(packet, rendering, f"### tool call Write (id {HIT})")
    results = _harness(packet, rendering, f"### tool result for {HIT}")
    assert len(calls) == 2 and len(results) == 2
    for line in [*calls, *(_fence_end(rendering, r) for r in results)]:
        assert any(b.first <= line <= b.last for b in blocks), line


def test_a_marker_at_the_very_start_or_end_of_a_session_is_shown_clipped_to_it(
    tmp_path: Path,
) -> None:
    sessions = [
        _session(*_noqa("toolu_a"), *_reads(1, 6), END),
        _session(INIT, *_reads(7, 6), *_noqa("toolu_b", result=False)),
    ]
    packet, read, attempt = _packet(tmp_path, sessions)
    rendering = _rendering(packet, read)
    (first, last), (second_first, second_last) = _sessions(rendering)
    a, b = _blocks(packet, read)
    (call_a,) = _harness(packet, rendering, "### tool call Write (id toolu_a)")
    (result_a,) = _harness(packet, rendering, "### tool result for toolu_a")
    (call_b,) = _harness(packet, rendering, "### tool call Write (id toolu_b)")
    assert (a.first, a.last) == (first, _fence_end(rendering, result_a) + AROUND)
    assert call_a - first < AROUND
    assert (b.first, b.last) == (call_b - AROUND, second_last)
    assert second_first < b.first
    _check(packet, attempt)


# -- the check -------------------------------------------------------------------------------------


def _tampered(packet: Packet, read: Path) -> Packet:
    """The packet with its first excerpt part changed by one line, its record changed to match."""
    part = _excerpt_parts(packet)[0]
    path = read / part.name
    body = path.read_bytes().replace(b"file's line", b"file's LINE", 1)
    assert body != path.read_bytes()
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    parts = (part.model_copy(update={"sha256": digest}), *_excerpt_parts(packet)[1:])
    joined = joined_parts(read, parts)
    update = {"earlier_hit_parts": parts, "earlier_hits_sha256": hashlib.sha256(joined).hexdigest()}
    return packet.model_copy(update=update)


def test_an_excerpt_that_is_not_the_slice_it_names_refuses_the_packet(tmp_path: Path) -> None:
    sessions = [_session(INIT, *_reads(1, 4), *_noqa(HIT), *_reads(5, 4), END)]
    packet, read, attempt = _packet(tmp_path, sessions)
    _check(packet, attempt)
    original = (read / _excerpt_parts(packet)[0].name).read_bytes()
    retold = _tampered(packet, read)
    with pytest.raises(PacketError, match="earlier"):
        _check(retold, attempt)
    # Changed on disk only, the part is not the one the record names.
    with pytest.raises(PacketError, match="earlier"):
        _check(packet, attempt)
    (read / _excerpt_parts(packet)[0].name).write_bytes(original)
    _check(packet, attempt)


def test_an_excerpt_part_left_out_of_the_record_refuses_the_packet(tmp_path: Path) -> None:
    sessions = [_session(INIT, *_reads(1, 4), *_noqa(HIT), *_reads(5, 4), END)]
    packet, _, attempt = _packet(tmp_path, sessions)
    _excerpt_parts(packet)
    bare = packet.model_copy(update={"earlier_hit_parts": (), "earlier_hits_sha256": None})
    with pytest.raises(PacketError, match="earlier"):
        _check(bare, attempt)


def test_earlier_parts_cut_at_other_lines_refuse_the_packet(tmp_path: Path) -> None:
    sessions = [
        _session(INIT, *_reads(1, 12, lines=60), *_noqa(HIT), *_reads(13, 12, lines=60), END)
    ]
    packet, read, attempt = _packet(tmp_path, sessions)
    _excerpt_parts(packet)
    first, second = packet.earlier_parts[0], packet.earlier_parts[1]
    one = (read / first.name).read_bytes().splitlines(keepends=True)
    two = (read / second.name).read_bytes()
    moved = [b"".join(one[:-1]), one[-1] + two]
    (read / first.name).write_bytes(moved[0])
    (read / second.name).write_bytes(moved[1])
    recut = tuple(
        part.model_copy(
            update={
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
                "lines": len(body.splitlines()),
            }
        )
        for part, body in zip((first, second), moved, strict=True)
    )
    retold = packet.model_copy(update={"earlier_parts": (*recut, *packet.earlier_parts[2:])})
    with pytest.raises(PacketError, match="earlier"):
        _check(retold, attempt)


# -- every marker is still judged ------------------------------------------------------------------


def test_with_the_excerpts_every_earlier_marker_must_still_be_answered(tmp_path: Path) -> None:
    sessions = [
        _session(INIT, *_reads(1, 4), *_noqa("toolu_a"), *_reads(5, 8), *_noqa("toolu_b"),
                 *_reads(13, 4), END)
    ]  # fmt: skip
    packet, _, _ = _packet(tmp_path, sessions)
    _excerpt_parts(packet)
    hits = to_answer(packet)
    assert [(h.evidence, h.attempt) for h in hits] == [("toolu_a", 1), ("toolu_b", 1)]
    items = load_rubric(REPO / "knowledge", ROLE).items
    one = {**DISMISSED, "evidence": "toolu_a", "attempt": 1}
    assert isinstance(judge(_answer([one]), hits, items), Unavailable)
    assert isinstance(judge(_answer([one, {**one, "evidence": "toolu_b"}]), hits, items), Answered)


# -- the size, on stand-ins shaped like the recorded cases -----------------------------------------


@pytest.mark.parametrize(
    ("hits", "reads"),
    [(11, 300), (14, 410)],
    ids=["eleven markers", "fourteen markers in some sixty-four parts"],
)
def test_the_required_earlier_reading_is_at_most_one_part_a_marker(
    tmp_path: Path, hits: int, reads: int
) -> None:
    events: list[str] = [INIT]
    gap = reads // hits
    for n in range(hits):
        events += [*_reads(1 + n * gap, gap, lines=60), *_noqa(f"toolu_hit{n:02d}")]
    events += [*_reads(1 + hits * gap, reads - hits * gap + 1, lines=60), END]
    packet, read, attempt = _packet(tmp_path, [_session(*events)])
    excerpts = _excerpt_parts(packet)
    rendering = _rendering(packet, read)
    blocks = _blocks(packet, read)
    for block in blocks:
        assert block.shown == b"".join(rendering[block.first : block.last + 1])
    required = sum(p.bytes for p in excerpts)
    whole = sum(p.bytes for p in packet.earlier_parts)
    assert len(packet.earlier_indicators) == hits
    assert required <= hits * PART_MAX_BYTES
    assert required * 4 < whole
    _check(packet, attempt)
    sizes: dict[str, Any] = {
        "markers": hits,
        "earlier_parts": len(packet.earlier_parts),
        "earlier_bytes": whole,
        "excerpt_parts": len(excerpts),
        "excerpt_bytes": required,
        "excerpts": len(blocks),
    }
    print("earlier-reading sizes", json.dumps(sizes))
