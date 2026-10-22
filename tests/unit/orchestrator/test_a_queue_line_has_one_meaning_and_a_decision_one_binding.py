"""A queue line has one meaning to every reader, and a decision acts only on what it was bound to.

Every reader of the items and the decisions file goes through one parser, which reads only the
one form the writer writes: a key given twice (of which the parser keeps the last), keys in
another order, an escape for a plain character, or space around the record would give the line's
digest other bytes than any reader sees, and is refused. A decision line's free text, which every
reader shows, is exactly its verb and note, which the run acts on. Every reader holds the files to
the rules the decision function holds them to under its lock: never through a link, one name.

At take, the item as listed must be the item the run's own record builds, so a person who was
shown another session's stream, or another finding, approves nothing. A stream that is named and
was never sealed can be neither scanned nor held, and refuses rather than reads as clean; a view
that showed no trajectory showed none that held.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, FakeReviewer
from test_a_queue_decision_acts_at_a_boundary import (
    NO_VERDICT,
    _of,
    _resume,
    _rig,
    _start,
    decide,
)

from physgate.orchestrator.events import DecisionTaken, Incident
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    QUEUE_NAME,
    QueueResolution,
    ShownItem,
    _require_bindable,
    item_sha256,
    read_queue,
)

TS = "2026-10-21T10:00:00.000000Z"


def _escalated(tmp_path: Path, **kw: Any) -> Any:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}), **kw)
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    return rig


def _refused(run_dir: Path, why: str) -> None:
    """Reading the queue is refused, for ``why``: the reason names which rule refused it."""
    with pytest.raises(QueueError) as caught:
        read_queue(run_dir)
    assert why in " ".join(caught.value.context.values()), caught.value.context


def _line(**fields: Any) -> bytes:
    return QueueResolution(**fields).model_dump_json().encode() + b"\n"


# -- one parser, one form ----------------------------------------------------------------------


def _non_canonical(line: bytes, form: str) -> bytes:
    body = line.removesuffix(b"\n")
    if form == "a key twice":
        # The parser keeps the last value; the start of the line says something else.
        return body[:-1] + b',"resolved_by":"someone else"}\n'
    if form == "keys reordered":
        data = json.loads(body)
        return (
            json.dumps(dict(reversed(list(data.items()))), separators=(",", ":")).encode() + b"\n"
        )
    if form == "an escaped letter":
        return body.replace(b'"resolved_by":"y', b'"resolved_by":"\\u0079', 1) + b"\n"
    if form == "a carriage return":
        return body + b"\r\n"
    if form == "a space after":
        return body + b" \n"
    raise AssertionError(form)


FORMS = ["a key twice", "keys reordered", "an escaped letter", "a carriage return", "a space after"]


@pytest.mark.parametrize("form", FORMS)
def test_a_decision_line_in_another_form_than_the_writers_is_refused(
    tmp_path: Path, form: str
) -> None:
    rig = _escalated(tmp_path)
    line = _line(item_id="run-1-s1", ts=TS, decision="approve: x", resolved_by="y")
    assert read_queue(rig.run_dir).decisions == ()
    (rig.run_dir / DECISIONS_NAME).write_bytes(_non_canonical(line, form))
    _refused(rig.run_dir, "the one form")
    # The same line in the writer's form reads.
    (rig.run_dir / DECISIONS_NAME).write_bytes(line)
    assert len(read_queue(rig.run_dir).decisions) == 1


@pytest.mark.parametrize("form", ["a key twice", "keys reordered", "a carriage return"])
def test_an_item_line_in_another_form_than_the_writers_is_refused(
    tmp_path: Path, form: str
) -> None:
    rig = _escalated(tmp_path)
    items = rig.run_dir / QUEUE_NAME
    line = items.read_bytes()
    if form == "a key twice":
        forged = line.removesuffix(b"}\n") + b',"triggering_finding":"nothing to see"}\n'
    elif form == "keys reordered":
        data = json.loads(line)
        forged = json.dumps(dict(reversed(list(data.items()))), separators=(",", ":")).encode()
        forged += b"\n"
    else:
        forged = line.removesuffix(b"\n") + b"\r\n"
    items.write_bytes(forged)
    _refused(rig.run_dir, "the one form")


SHOWN = "a" * 64


@pytest.mark.parametrize(
    ("fields", "why"),
    [
        ({"decision": "approve", "verb": "reject", "note": "no", "shown_sha256": SHOWN},
         "exactly its verb"),
        ({"decision": "reject: no", "verb": "approve", "note": "no", "shown_sha256": SHOWN},
         "exactly its verb"),
        ({"decision": "approve", "verb": "approve"}, "names the digest"),
        ({"decision": "x", "note": "a note"}, "belongs to a decision with a verb"),
        ({"decision": "x", "shown_sha256": SHOWN}, "belongs to a decision with a verb"),
        ({"decision": "reject", "verb": "reject", "shown_sha256": SHOWN}, "carries its note"),
    ],
    ids=["text approves, verb rejects", "text rejects, verb approves", "verb, no view",
         "note, no verb", "view, no verb", "reject, no note"],
)  # fmt: skip
def test_a_decision_line_says_one_thing(fields: dict[str, Any], why: str) -> None:
    with pytest.raises(ValueError, match=why):
        QueueResolution(item_id="run-1-s1", ts=TS, resolved_by="y", **fields)


@pytest.mark.parametrize("how", ["a link", "a second name"])
def test_every_reader_holds_the_queue_files_to_the_decision_functions_rules(
    tmp_path: Path, how: str
) -> None:
    rig = _escalated(tmp_path)
    items = rig.run_dir / QUEUE_NAME
    elsewhere = tmp_path / "elsewhere.jsonl"
    elsewhere.write_bytes(items.read_bytes())
    if how == "a link":
        items.unlink()
        items.symlink_to(elsewhere)
    else:
        os.link(items, tmp_path / "second-name.jsonl")
    _refused(rig.run_dir, "one name" if how == "a second name" else "link")


# -- the item the run's record builds ----------------------------------------------------------


@pytest.mark.parametrize("what", ["the stream it links", "the finding it shows"])
def test_an_approve_on_an_item_the_record_does_not_build_merges_nothing(
    tmp_path: Path, what: str
) -> None:
    # s0 merges with a clean stream; s1's review reaches no verdict. Its item line is rewritten
    # before a person reads it: to link s0's stream, whose seal holds, or to say another
    # finding. Its consequence, commit and diff are untouched, and its digest is the one shown.
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={2: NO_VERDICT}))
    loop = _start(rig, "s0", "s1")
    loop.run()
    loop.close()
    items = run_dir / QUEUE_NAME
    line = items.read_bytes()
    if what == "the stream it links":
        assert line.count(b"sessions/sess-2/stdout.jsonl") == 1
        items.write_bytes(line.replace(b"sessions/sess-2/", b"sessions/sess-1/"))
    else:
        assert line.count(b"no verdict") >= 1
        items.write_bytes(line.replace(b"no verdict", b"a clean verdict"))
    view = read_queue(run_dir)
    assert view.items[0].consequence is not None
    decide(run_dir, "approve", item_id="run-1-s1")
    _, kind = _resume(rig)
    assert kind == "halted"
    assert [i.cause for i in _of(run_dir, Incident)] == ["queue_item_mismatch"]
    assert [m[0] for m in rig.merger.merges] == ["s0"]
    assert _of(run_dir, DecisionTaken) == []


# -- nothing missing reads as clean ------------------------------------------------------------


def test_a_view_that_showed_no_trajectory_binds_no_approve() -> None:
    rig_item: Any = type("Item", (), {"item_id": "run-1-s1", "source": "review_unavailable"})()
    record = QueueResolution(
        item_id="run-1-s1",
        ts=TS,
        decision="approve",
        resolved_by="y",
        verb="approve",
        shown_sha256="a" * 64,
    )
    with pytest.raises(QueueError, match="held its seal"):
        _require_bindable(rig_item, record, ShownItem(item_sha256="a" * 64, trajectories=()))


def test_a_stream_named_and_never_sealed_is_not_a_stream_the_scan_found_clean(
    tmp_path: Path,
) -> None:
    # A session that names its stream and carries no seal: nothing can say what it held.
    rig = _rig(
        tmp_path / "run",
        dispatcher=FakeDispatcher(),  # notional streams: named, never sealed
        reviewer=FakeReviewer(unavailable={1: NO_VERDICT}),
    )
    loop = _start(rig, "s1")
    assert loop.run().kind == "halted"
    (incident,) = _of(rig.run_dir, Incident)
    assert incident.cause == "trajectory_tampered" and "has no seal" in incident.detail
    assert read_queue(rig.run_dir).items == ()


def test_a_forged_bound_approve_on_an_unsealed_stream_merges_nothing(tmp_path: Path) -> None:
    # Reviews reject all three attempts, whose streams are named and never sealed. The decision
    # function refuses an approve on that view; a line appended past it, in its form, with the
    # right digest, is held by the loop to the same rule and merges nothing.
    rig = _rig(
        tmp_path / "run", dispatcher=FakeDispatcher(), reviewer=FakeReviewer(verdicts=["fail"] * 3)
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    view = read_queue(rig.run_dir)
    (item,) = view.items
    assert item.consequence is not None and item.consequence.on_approve == "merge_attempt"
    with pytest.raises(QueueError, match="held its seal"):
        decide(rig.run_dir, "approve")
    (rig.run_dir / DECISIONS_NAME).write_bytes(
        _line(
            item_id=item.item_id,
            ts=TS,
            decision="approve",
            resolved_by="forged",
            verb="approve",
            shown_sha256=item_sha256((rig.run_dir / QUEUE_NAME).read_bytes().removesuffix(b"\n")),
        )
    )
    _, kind = _resume(rig)
    assert kind == "halted"
    assert [i.cause for i in _of(rig.run_dir, Incident)] == ["trajectory_tampered"]
    assert rig.merger.merges == []
