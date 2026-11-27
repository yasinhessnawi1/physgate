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
from pathlib import Path

from loop_fakes import Rig, plan, usage
from test_a_review_s_exposure_is_found_again_after_a_kill_past_its_end_record import (
    CLEAN,
    ENDED,
    STARTED,
    _dispatcher,
    _review_session,
)

from physgate.orchestrator.events import Halted, TokensUsed
from physgate.orchestrator.loop import Loop


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
