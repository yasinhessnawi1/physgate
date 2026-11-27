"""A review killed between its token lines is read again at the resume; one fully back is not.

The loop writes a review's tokens once it is back, and then its verdict, why there is none, or the
halt its try ended the run on, at once. Its token lines alone are not the review back: a process
killed between them leaves the rest of its spend on no record. The next process reads such a review
as it reads any session left open, every stream its spawns wrote. A review whose tokens are followed
by the halt written with them is back, and is not read twice.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loop_fakes import KilledError, Rig, plan, usage
from test_a_review_s_exposure_is_found_again_after_a_kill_past_its_end_record import (
    CLEAN,
    ENDED,
    STARTED,
    EndedReviewer,
    _dispatcher,
    _review_session,
    _rig,
)
from test_a_session_end_s_findings_are_recorded_before_its_incidents_and_a_kill_writes_the_rest import (  # noqa: E501
    kinds,
    lines,
    outcome,
    taken_over,
)

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import Event, Halted, TokensUsed, read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.session_ends import open_sessions


def _tokens(loop: Loop, sid: str, message_id: str) -> None:
    loop._emit(  # noqa: SLF001 - the loop's own record of what a review spent
        TokensUsed(
            **loop._env(),  # noqa: SLF001
            attribution=f"reviewer:{sid}",
            message_id=message_id,
            usage=usage(3),
        )
    )


def _cut(loop: Loop, sid: str) -> None:
    _tokens(loop, sid, "rv1")


def _halted_with_them(loop: Loop, sid: str) -> None:
    _tokens(loop, sid, "rv1")
    _tokens(loop, sid, "rv2")
    loop._emit(  # noqa: SLF001 - the halt the loop writes with a review's tokens
        Halted(**loop._env(), reason="infrastructure_exhausted", detail=f"review session {sid}")  # noqa: SLF001
    )


def _left(tmp_path: Path, after: Callable[[Loop, str], None]) -> set[str]:
    run_dir, review_root = tmp_path / "run", tmp_path / "reviews"
    run_dir.mkdir()
    rig = Rig(run_dir)
    loop = rig.open()
    loop.start(plan("s1"))
    loop._spawned("rev-1", 4242, STARTED)  # noqa: SLF001 - the loop's own record of a spawn
    after(loop, "rev-1")
    loop.close()
    sdir = _review_session(review_root, "rev-1", 4242, STARTED, {"stdout.jsonl": CLEAN})
    (sdir / "ended.json").write_text(json.dumps(ENDED))
    return {x.session_id for x in _dispatcher(run_dir, review_root).stop_leftovers()}


def test_a_review_killed_after_its_first_token_line_is_read_again(tmp_path: Path) -> None:
    assert "rev-1" in _left(tmp_path, _cut), "a review cut in its token lines was taken as back"


def test_a_review_whose_tokens_are_followed_by_its_halt_is_not_read_again(tmp_path: Path) -> None:
    assert _left(tmp_path, _halted_with_them) == set(), "a review the loop recorded was read again"


def _message(message_id: str) -> str:
    spent = {
        "input_tokens": 3,
        "output_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    line = {"type": "assistant", "message": {"id": message_id, "usage": spent, "content": []}}
    return json.dumps(line) + "\n"


#: The review's stream as the binary writes it: two messages, then its result.
SPENT = (
    _message("rv1")
    + _message("rv2")
    + json.dumps({"type": "result", "subtype": "success", "session_id": "rev-sess-1"})
    + "\n"
)


@dataclass
class TwoMessages(EndedReviewer):
    """Its first review ends on disk having spent two messages, and answers with both."""

    def review(self, artefact: Any) -> Any:  # noqa: ANN401
        answered = super().review(artefact)
        if answered.session_id != "rev-sess-1":
            return answered
        spent = tuple(MessageUsage(message_id=m, usage=usage(3)) for m in ("rv1", "rv2"))
        return answered.model_copy(update={"usage": spent})


def _dies_after_the_review_s_first_token_line(loop: Loop) -> None:
    emit = loop._emit  # noqa: SLF001 - the loop's own writer
    written: list[Event] = []

    def emitting(event: Event) -> None:
        if isinstance(event, TokensUsed) and event.attribution.startswith("reviewer:"):
            if written:
                raise KilledError
            written.append(event)
        emit(event)

    loop._emit = emitting  # type: ignore[method-assign]  # noqa: SLF001


def test_a_review_killed_between_its_token_lines_is_counted_whole_after_the_take_over(
    tmp_path: Path,
) -> None:
    """The take-over reads the review's stream: each of its messages counted once, none lost."""
    rig = _rig(tmp_path, TwoMessages(stream=SPENT, mode="returns"))
    loop = rig.open()
    loop.start(plan("s1"))
    _dies_after_the_review_s_first_token_line(loop)
    assert outcome(loop.run) == "killed"
    loop.close()
    assert taken_over(rig) == "done"
    rows = lines(rig)
    read = [r for r in rows if r["kind"] == "leftover_read" and r["session_id"] == "rev-sess-1"]
    assert len(read) == 1, "the review cut in its token lines was not read at the take-over"
    events = read_events(rig.run_dir / "events.jsonl")
    account = TokenAccount.from_events(events)
    assert account.by_attribution()["reviewer:rev-sess-1"] == usage(6).model_copy(
        update={"output_tokens": 2}
    )
    assert open_sessions(events, rig.run_dir) == ()
    assert "merged" in kinds(rows)
