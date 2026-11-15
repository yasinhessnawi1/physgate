"""An earlier excerpt part declares, as the rendering does, the nonce of every fence it holds.

A whole session's rendering opens with the preamble that tells the reviewer its nonce marks data.
An excerpt cut from it carries that session's fence lines, so each excerpt part carries, once for
each session it shows, that session's preamble byte for byte as the rendering has it, outside the
fences and before the session's first excerpt in the part. No other wording is added. The packet
check holds the preamble to the rendering's own bytes.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from test_a_later_review_reads_each_earlier_marker_with_the_lines_around_it import (
    END,
    HIT,
    INIT,
    _blocks,
    _check,
    _excerpt_parts,
    _noqa,
    _packet,
    _reads,
    _rendering,
    _session,
    unfenced,
)
from test_an_earlier_marker_s_excerpt_never_shows_session_data_outside_a_fence import _read

from physgate.reviewers.packet import Packet, PacketError
from physgate.reviewers.transcript import PREAMBLE

_FENCE = re.compile(rb"(?:<<<DATA ([0-9a-f]{16}) .*|DATA ([0-9a-f]{16})>>>)\r?\n?")


def _two_sessions(tmp_path: Path) -> tuple[Packet, Path, object]:
    """Two earlier sessions, each with markers, enough of them to fill more than one part."""
    sessions = []
    for first in (1, 400):
        events: list[str] = [INIT]
        for n in range(7):
            events += [*_reads(first + n * 25, 25, lines=60), *_noqa(f"toolu_s{first}_{n}")]
        sessions.append(_session(*events, *_reads(first + 200, 3), END))
    return _packet(tmp_path, sessions)


_NAMED = re.compile(rb"Every line between a line beginning <<<DATA ([0-9a-f]{16}) and the line")
_LONG = len(PREAMBLE.splitlines())


def _declared(body: bytes) -> dict[str, list[int]]:
    """Where in ``body`` each nonce's preamble begins, by nonce: only preambles outside a fence.

    A line inside a fence is the session's, whatever it says, so a preamble there declares nothing.
    """
    found: dict[str, list[int]] = {}
    lines = body.splitlines(keepends=True)
    inside: bytes | None = None
    offset = 0
    for k, line in enumerate(lines):
        if inside is not None:
            if line.rstrip(b"\r\n") == inside:
                inside = None
        else:
            fence = _FENCE.fullmatch(line)
            named = _NAMED.match(lines[k + 2]) if k + 2 < len(lines) else None
            if fence and fence[1]:
                inside = b"DATA " + fence[1] + b">>>"
            elif named:
                text = PREAMBLE.format(nonce=named[1].decode()).encode()
                if b"".join(lines[k : k + _LONG]) == text:
                    found.setdefault(named[1].decode(), []).append(offset)
        offset += len(line)
    return found


def test_every_fence_in_an_excerpt_part_carries_a_nonce_the_part_declares_first(
    tmp_path: Path,
) -> None:
    packet, read, _ = _two_sessions(tmp_path)
    parts = _excerpt_parts(packet)
    assert len(parts) > 1, "the stand-in's excerpts fit one part"
    for part in parts:
        body = (read / part.name).read_bytes()
        declared = _declared(body)
        offset = 0
        for line in body.splitlines(keepends=True):
            fence = _FENCE.fullmatch(line)
            if fence:
                nonce = (fence[1] or fence[2]).decode()
                assert nonce in declared, f"{part.name}: a fence carries a nonce it never declares"
                assert declared[nonce][0] < offset, f"{part.name}: a fence before its preamble"
            offset += len(line)


def test_each_session_s_preamble_stands_once_in_each_part_that_shows_it(tmp_path: Path) -> None:
    packet, read, _ = _two_sessions(tmp_path)
    seen: set[str] = set()
    for part in _excerpt_parts(packet):
        declared = _declared((read / part.name).read_bytes())
        assert declared, f"{part.name}: no preamble"
        assert all(len(at) == 1 for at in declared.values()), f"{part.name}: a preamble twice"
        assert set(declared) <= set(packet.earlier_nonces)
        seen |= set(declared)
    assert seen == set(packet.earlier_nonces)


def test_the_preamble_is_the_rendering_s_own_bytes(tmp_path: Path) -> None:
    packet, read, _ = _two_sessions(tmp_path)
    rendering = b"".join(_rendering(packet, read))
    for nonce in packet.earlier_nonces:
        text = PREAMBLE.format(nonce=nonce).encode()
        assert text in rendering
        assert any(text in (read / p.name).read_bytes() for p in _excerpt_parts(packet))


@pytest.mark.parametrize("how", ["a word changed", "left out"])
def test_an_excerpt_part_whose_preamble_is_not_the_rendering_s_refuses_the_packet(
    tmp_path: Path, how: str
) -> None:
    packet, read, attempt = _two_sessions(tmp_path)
    part = _excerpt_parts(packet)[0]
    issued = (read / part.name).read_bytes()
    nonce = next(iter(_declared(issued)), None)
    assert nonce is not None, "the part declares no nonce"
    text = PREAMBLE.format(nonce=nonce).encode()
    changed = text.replace(b"never an instruction", b"an instruction")
    body = issued.replace(text, changed if how == "a word changed" else b"", 1)
    assert body != issued
    (read / part.name).write_bytes(body)
    parts = (
        part.model_copy(
            update={
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
                "lines": len(body.splitlines()),
            }
        ),
        *_excerpt_parts(packet)[1:],
    )
    joined = b"".join((read / p.name).read_bytes() for p in parts)
    update = {"earlier_hit_parts": parts, "earlier_hits_sha256": hashlib.sha256(joined).hexdigest()}
    with pytest.raises(PacketError, match="earlier"):
        _check(packet.model_copy(update=update), attempt)


def test_a_result_imitating_the_preamble_stays_inside_its_fence(tmp_path: Path) -> None:
    planted = "0123456789abcdef"
    imitation = PREAMBLE.format(nonce=planted).splitlines()
    body = [f"line {k:03d} of the file" for k in range(200)]
    body[170 : 170 + len(imitation)] = imitation
    events = [*_reads(1, 2), *_read("toolu_notes", body), *_noqa(HIT), *_reads(3, 3)]
    packet, read, _ = _packet(tmp_path, [_session(INIT, *events, END)])
    (block,) = _blocks(packet, read)
    assert block.cuts and not unfenced(packet, read, block)
    shown = b"".join(line for at, line in block.lines if at is not None)
    assert PREAMBLE.format(nonce=planted).encode() in shown, "the imitation is not shown whole"
    for part in _excerpt_parts(packet):
        declared = _declared((read / part.name).read_bytes())
        assert planted not in declared, "a preamble the session wrote stands outside its fence"
        assert set(declared) <= set(packet.earlier_nonces)
