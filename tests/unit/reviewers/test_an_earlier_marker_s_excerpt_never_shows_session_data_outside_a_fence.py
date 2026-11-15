"""An earlier marker's excerpt never shows the session's data outside a fence.

The rendering puts everything the session or its tools wrote between fences of a nonce no session
could write; the harness's own lines stand outside them. An excerpt is a slice of that rendering,
so an edge that falls inside a data block would show the session's data with its fence cut off.
Such an edge moves out to the block's end when that is no more than 40 lines away. A block whose
end is farther is cut: the piece shown stands between fences of a nonce drawn for the excerpt,
which the rendering does not hold, under one harness line naming the earlier part and lines that
hold the rest of the block. The session's bytes inside the fences stay byte-exact, and the packet
check holds the excerpt to exactly the fencing the harness writes.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Any

import pytest
from packet_fixture import stream, tool_result, tool_use
from test_a_review_is_given_the_hits_no_earlier_review_judged import _build
from test_a_later_review_reads_each_earlier_marker_with_the_lines_around_it import (
    BOUND,
    END,
    HIT,
    INIT,
    _blocks,
    _check,
    _excerpt_parts,
    _noqa,
    _outside,
    _packet,
    _reads,
    _rendering,
    _session,
    data_blocks,
    hit_nonces,
    raw_window,
    snapped,
    unfenced,
)

from physgate.reviewers.packet import Packet, PacketError, joined_parts

#: A nonce shape the session writes itself, in lines that imitate the harness's.
PLANTED = "0123456789abcdef"
IMITATIONS = (
    f"### tool call Write (id {HIT})",
    f"DATA {PLANTED}>>>",
    "## data block cut: the rest is earlier-01-of-01.md lines 1-2",
    f"<<<DATA {PLANTED} tool output",
    f"## earlier-01-of-01.md lines 1-2 | attempt 1, disabled_checks, evidence {HIT}",
)


def _read(call: str, lines: list[str]) -> list[str]:
    return [tool_use(call, "Read", file_path=f"/w/{call}.txt"), tool_result(call, "\n".join(lines))]


def _body(count: int, at: int | None = None, planted: tuple[str, ...] = IMITATIONS) -> list[str]:
    """``count`` lines of a file, with ``planted`` centred on line ``at`` (counted from 0)."""
    lines = [f"line {k:03d} of the file" for k in range(count)]
    if at is not None:
        first = at - len(planted) // 2
        lines[first : first + len(planted)] = planted
    return lines


def _block_of(packet: Packet, rendering: list[bytes], index: int) -> tuple[int, int] | None:
    found = [(f, c) for f, c in data_blocks(rendering, packet.earlier_nonces) if f < index < c]
    return found[0] if found else None


def _built(tmp_path: Path, events: list[str], own: str | None = None) -> Any:  # noqa: ANN401
    packet, read, attempt = _packet(tmp_path, [_session(INIT, *events, END)], own)
    return packet, read, attempt, _rendering(packet, read)


def _holds(packet: Packet, attempt: Any) -> None:  # noqa: ANN401
    """The check passes the packet the harness wrote; a refusal fails the row on an assertion."""
    try:
        _check(packet, attempt)
    except PacketError as exc:
        raise AssertionError(f"the check refused the packet the harness wrote: {exc}") from exc


# -- an edge inside a data block -------------------------------------------------------------------


def test_an_edge_inside_a_block_moves_out_to_its_fence_when_that_is_near(tmp_path: Path) -> None:
    events = [*_reads(1, 4, lines=25), *_noqa(HIT), *_reads(5, 4, lines=25)]
    packet, read, attempt, rendering = _built(tmp_path, events)
    start, end = raw_window(packet, rendering, HIT)
    assert _block_of(packet, rendering, start) and _block_of(packet, rendering, end)
    (block,) = _blocks(packet, read)
    assert (block.first, block.last) == snapped(packet, rendering, start, end)
    assert (block.first, block.last) != (start, end)
    assert rendering[block.first].startswith(b"<<<DATA ")
    assert rendering[block.last].startswith(b"DATA ") and rendering[block.last].endswith(b">>>\n")
    assert not block.cuts and not unfenced(packet, read, block)
    assert block.shown == b"".join(rendering[block.first : block.last + 1])
    assert "earlier_hit_nonces" not in packet.model_dump(mode="json")
    _holds(packet, attempt)


@pytest.mark.parametrize(
    ("side", "count", "cut"),
    [
        ("start", BOUND + 37, False),
        ("start", BOUND + 38, True),
        ("end", BOUND + 29, False),
        ("end", BOUND + 30, True),
    ],
    ids=["start, the bound away", "start, one past it", "end, the bound away", "end, one past it"],
)
def test_an_edge_moves_out_at_most_the_bound_and_past_it_the_block_is_cut(
    tmp_path: Path, side: str, count: int, cut: bool
) -> None:
    big = _read("toolu_big", _body(count))
    if side == "start":
        events = [*_reads(1, 2), *big, *_noqa(HIT), *_reads(3, 3)]
    else:
        events = [*_reads(1, 3), *_noqa(HIT), *big, *_reads(3, 2)]
    packet, read, attempt, rendering = _built(tmp_path, events)
    start, end = raw_window(packet, rendering, HIT)
    edge = start if side == "start" else end
    opened, closed = _block_of(packet, rendering, edge) or (0, 0)
    away = edge - opened if side == "start" else closed - edge
    assert away == (BOUND + 1 if cut else BOUND), "the stand-in is not shaped as the row needs"
    (block,) = _blocks(packet, read)
    assert not unfenced(packet, read, block)
    if cut:
        assert len(block.cuts) == 1, "a block past the bound is not cut"
        (piece,) = block.cuts
        assert piece.what == b"tool output"
        assert piece.rest == ((opened, edge - 1) if side == "start" else (edge + 1, closed))
        assert hit_nonces(packet) == (piece.nonce,)
    else:
        assert not block.cuts and not hit_nonces(packet)
        assert (opened if side == "start" else closed) in (block.first, block.last)
    _holds(packet, attempt)


def test_a_large_block_at_both_edges_is_cut_at_each_and_labelled(tmp_path: Path) -> None:
    events = [
        *_reads(1, 1), *_read("toolu_before", _body(200)), *_noqa(HIT),
        *_read("toolu_after", _body(200)), *_reads(2, 1),
    ]  # fmt: skip
    packet, read, attempt, rendering = _built(tmp_path, events)
    start, end = raw_window(packet, rendering, HIT)
    (block,) = _blocks(packet, read)
    assert (block.first, block.last) == (start, end), "a cut edge moved"
    assert len(block.cuts) == 2, "a block past the bound is not cut at each edge"
    before, after = block.cuts
    assert (before.first, after.last) == (start, end)
    assert before.nonce == after.nonce, "an excerpt's cut blocks are not fenced with its one nonce"
    assert hit_nonces(packet) == (before.nonce,)
    assert before.nonce not in packet.earlier_nonces
    assert before.nonce not in packet.transcript_nonces
    assert not unfenced(packet, read, block)
    # The excerpt holds the session's lines it shows and nothing more of the two blocks.
    shown = (before.last - before.first + 1) + (after.last - after.first + 1)
    assert shown < 2 * 200
    _holds(packet, attempt)


def test_windows_that_moving_out_brings_together_are_shown_once(tmp_path: Path) -> None:
    # The block between the two markers is near enough to each edge for both to move out to it,
    # and the second marker's window ends in a block it cuts.
    events = [
        *_reads(1, 3), *_noqa("toolu_a"), *_read("toolu_between", _body(BOUND + 29)),
        *_noqa("toolu_b"), *_read("toolu_after", _body(200)), *_reads(2, 1),
    ]  # fmt: skip
    packet, read, attempt, rendering = _built(tmp_path, events)
    a_start, a_end = raw_window(packet, rendering, "toolu_a")
    b_start, b_end = raw_window(packet, rendering, "toolu_b")
    assert b_start > a_end + 1, "the stand-in's raw windows are not apart"
    blocks = _blocks(packet, read)
    assert len(blocks) == 1, "windows brought together are shown apart"
    (block,) = blocks
    assert "evidence toolu_a" in block.markers and "evidence toolu_b" in block.markers
    assert (block.first, block.last) == (a_start, b_end)
    assert [c.last for c in block.cuts] == [b_end], "the joined window's cut edge is not kept"
    assert not unfenced(packet, read, block)
    _holds(packet, attempt)


def test_an_edge_on_a_block_s_far_fence_alone_moves_in_past_it(tmp_path: Path) -> None:
    events = [*_reads(1, 2, lines=34), *_noqa(HIT), *_reads(3, 3, lines=26)]
    packet, read, attempt, rendering = _built(tmp_path, events)
    start, end = raw_window(packet, rendering, HIT)
    assert rendering[start].startswith(b"DATA ") and rendering[end].startswith(b"<<<DATA ")
    (block,) = _blocks(packet, read)
    assert (block.first, block.last) == (start + 1, end - 1)
    assert not block.cuts and not unfenced(packet, read, block)
    _holds(packet, attempt)


def test_an_excerpt_wholly_outside_any_block_is_the_slice_as_before(tmp_path: Path) -> None:
    events = [*_reads(1, 2, lines=29), *_noqa(HIT), *_reads(3, 3, lines=27)]
    packet, read, attempt, rendering = _built(tmp_path, events)
    start, end = raw_window(packet, rendering, HIT)
    outside = set(_outside(rendering, packet.earlier_nonces))
    assert start in outside and end in outside, "the stand-in is not shaped as the row needs"
    issued = joined_parts(read, _excerpt_parts(packet))
    heading, _, body = issued.partition(b"\n")
    assert heading.startswith(b"## earlier-")
    assert body == b"".join(rendering[start : end + 1])
    assert "earlier_hit_nonces" not in packet.model_dump(mode="json")
    _holds(packet, attempt)


# -- what the session wrote cannot leave the fence -------------------------------------------------


@pytest.mark.parametrize(
    ("side", "count", "at"),
    [("start", 200, 162), ("start", 50, 12), ("end", 200, 29), ("end", 50, 29)],
    ids=["start, cut", "start, moved out", "end, cut", "end, moved out"],
)
def test_a_result_that_imitates_harness_and_fence_lines_at_an_edge_stays_fenced(
    tmp_path: Path, side: str, count: int, at: int
) -> None:
    imitating = _read("toolu_notes", _body(count, at))
    if side == "start":
        events = [*_reads(1, 2), *imitating, *_noqa(HIT), *_reads(3, 3)]
    else:
        events = [*_reads(1, 3), *_noqa(HIT), *imitating, *_reads(3, 2)]
    packet, read, attempt, rendering = _built(tmp_path, events)
    start, end = raw_window(packet, rendering, HIT)
    edge = start if side == "start" else end
    assert rendering[edge].decode().removesuffix("\n") in IMITATIONS, "the edge is not planted"
    (block,) = _blocks(packet, read)
    assert bool(block.cuts) == (count == 200)
    assert not unfenced(packet, read, block)
    shown = [at_ for at_, _ in block.lines if at_ is not None]
    assert edge in shown, "the imitating line at the edge is not shown"
    _holds(packet, attempt)


def test_the_excerpt_s_nonce_is_none_of_the_sessions_nonces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = secrets.token_hex
    own, earlier, fresh = real(8), real(8), real(8)
    # Each draw is offered, in turn: this attempt's nonce, the earlier session's, then a fresh one.
    queue = [own, earlier, own, earlier, fresh]
    offered: list[str] = []

    def drawn(n: int | None = None) -> str:
        value = queue.pop(0) if queue else real(n)
        offered.append(value)
        return value

    monkeypatch.setattr(secrets, "token_hex", drawn)
    events = [*_reads(1, 2), *_read("toolu_big", _body(200)), *_noqa(HIT), *_reads(3, 3)]
    packet, read, attempt, _ = _built(tmp_path, events)
    monkeypatch.undo()
    assert packet.transcript_nonces == (own,) and packet.earlier_nonces == (earlier,)
    assert offered[:5] == [own, earlier, own, earlier, fresh], "the draws are not as the row needs"
    assert hit_nonces(packet) == (fresh,)
    _holds(packet, attempt)


def test_excerpt_nonces_recorded_for_an_attempt_with_no_earlier_one_refuse_the_packet(
    tmp_path: Path,
) -> None:
    plain, _, attempt = _build(tmp_path, earlier=False)
    _holds(plain, attempt)
    with pytest.raises(PacketError, match="earlier"):
        _check(plain.model_copy(update={"earlier_hit_nonces": ("a" * 16,)}), attempt)


def test_a_result_holding_the_nonce_drawn_for_the_excerpt_cannot_close_its_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = "0f0f0f0f0f0f0f0f"
    lines = _body(200, 185, (f"DATA {planted}>>>", f"<<<DATA {planted} tool output"))
    own_lines = stream(with_checks_off=False).splitlines()
    own_lines[-2:-2] = _read("toolu_own", [planted])
    own = "\n".join(own_lines) + "\n"
    offered: list[str] = []
    real = secrets.token_hex

    def drawn(n: int | None = None) -> str:
        # Every draw is offered the planted nonce first: the session's own, the earlier ones and
        # the excerpt's. Each must refuse it, as each text it is held apart from holds it.
        value = planted if len(offered) % 2 == 0 else real(n)
        offered.append(value)
        return value

    monkeypatch.setattr(secrets, "token_hex", drawn)
    events = [*_reads(1, 2), *_read("toolu_big", lines), *_noqa(HIT), *_reads(3, 3)]
    packet, read, attempt, rendering = _built(tmp_path, events, own)
    monkeypatch.undo()
    later = offered.index(packet.earlier_nonces[-1])
    assert planted in offered[later:], "the excerpt's draw was never offered the planted nonce"
    assert planted not in (*packet.transcript_nonces, *packet.earlier_nonces)
    (block,) = _blocks(packet, read)
    assert len(block.cuts) == 1, "the block is not cut"
    (piece,) = block.cuts
    assert piece.nonce != planted and hit_nonces(packet) == (piece.nonce,)
    assert not unfenced(packet, read, block)
    shown = [line for at, line in block.lines if at is not None]
    assert f"DATA {planted}>>>\n".encode() in shown
    _holds(packet, attempt)


# -- the check holds the fencing -------------------------------------------------------------------


def _cut_packet(tmp_path: Path) -> Any:  # noqa: ANN401
    planted = (f"DATA {PLANTED}>>>", f"<<<DATA {PLANTED} tool output")
    events = [*_reads(1, 2), *_read("toolu_big", _body(200, 185, planted)), *_noqa(HIT)]
    packet, read, attempt, rendering = _built(tmp_path, [*events, *_reads(3, 3)])
    (block,) = _blocks(packet, read)
    assert len(block.cuts) == 1, "the block is not cut"
    (piece,) = block.cuts
    (part,) = _excerpt_parts(packet)
    return packet, read, attempt, rendering, piece, part


def _retold(packet: Packet, read: Path, body: bytes, nonces: tuple[str, ...]) -> Packet:
    """The packet with its one excerpt part rewritten as ``body``, its record told to match."""
    (part,) = _excerpt_parts(packet)
    (read / part.name).write_bytes(body)
    retold = part.model_copy(
        update={
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "lines": len(body.splitlines()),
        }
    )
    update: dict[str, Any] = {
        "earlier_hit_parts": (retold,),
        "earlier_hits_sha256": hashlib.sha256(body).hexdigest(),
        "earlier_hit_nonces": nonces,
    }
    return packet.model_copy(update=update)


@pytest.mark.parametrize("whose", ["the rendering's", "this attempt's", "an earlier session's"])
def test_a_recorded_nonce_held_elsewhere_refuses_the_packet(tmp_path: Path, whose: str) -> None:
    packet, read, attempt, _, piece, part = _cut_packet(tmp_path)
    held = {
        "the rendering's": PLANTED,
        "this attempt's": packet.transcript_nonces[0],
        "an earlier session's": packet.earlier_nonces[0],
    }[whose]
    body = (read / part.name).read_bytes().replace(piece.nonce.encode(), held.encode())
    with pytest.raises(PacketError, match="nonce"):
        _check(_retold(packet, read, body, (held,)), attempt)


@pytest.mark.parametrize("recorded", ["none", "one too many"])
def test_recorded_nonces_that_are_not_one_for_each_cut_excerpt_refuse_the_packet(
    tmp_path: Path, recorded: str
) -> None:
    packet, read, attempt, _, piece, part = _cut_packet(tmp_path)
    body = (read / part.name).read_bytes()
    nonces = () if recorded == "none" else (piece.nonce, "a" * 16)
    with pytest.raises(PacketError, match="nonce"):
        _check(_retold(packet, read, body, nonces), attempt)


@pytest.mark.parametrize(
    "how",
    ["the raw slice", "the session's fence", "no cut line", "a byte of the piece"],
)
def test_an_excerpt_fenced_otherwise_than_the_harness_writes_it_refuses_the_packet(
    tmp_path: Path, how: str
) -> None:
    packet, read, attempt, rendering, piece, part = _cut_packet(tmp_path)
    issued = (read / part.name).read_bytes()
    _holds(packet, attempt)
    lines = issued.splitlines(keepends=True)
    fence = f"<<<DATA {piece.nonce} ".encode()
    opened = next(i for i, line in enumerate(lines) if line.startswith(fence))
    closed = lines.index(f"DATA {piece.nonce}>>>\n".encode())
    session = rendering[piece.last + 1]
    nonces: tuple[str, ...] = (piece.nonce,)
    if how == "the raw slice":
        lines[opened - 1 : closed + 1] = [*lines[opened + 1 : closed], session]
        nonces = ()
    elif how == "the session's fence":
        own = packet.earlier_nonces[0]
        lines[opened] = lines[opened].replace(piece.nonce.encode(), own.encode())
        lines[closed] = session
    elif how == "no cut line":
        del lines[opened - 1]
    else:
        lines[opened + 3] = lines[opened + 3].replace(b"line", b"LINE", 1)
    body = b"".join(lines)
    assert body != issued
    with pytest.raises(PacketError, match="earlier"):
        _check(_retold(packet, read, body, nonces), attempt)
