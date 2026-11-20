"""An authoring session's spend carries the tokens of cut responses its count leaves out.

The raw arm's record counts a session's tokens as the run's account counts them, and records
apart the tokens of responses the binary cut short whose totals leave them out
(``tokens_not_in_binary_totals``): in no count, their billing unknown. The authoring session's
summary and the pool's provenance line of each session copy the spend from that record, so they
carry that figure too, and a spend that is a lower bound reads as one. A session with none keeps
its lines' bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role import author_session

RULE = "an author session's spend carries the cut tokens it leaves out"


def _record(cut_off: int) -> dict[str, Any]:
    return {
        "session_id": "a-1",
        "end": "ended",
        "tokens": 400,
        "tokens_not_in_binary_totals": cut_off,
        "cap": 1000,
        "wall_clock_s": 12.0,
        "held_out_seen": None,
    }


def test_the_session_summary_carries_the_cut_tokens() -> None:
    assert author_session._spent(_record(70)).get("tokens_not_in_binary_totals") == 70, RULE
    assert "tokens_not_in_binary_totals" not in author_session._spent(_record(0))


def test_the_pool_s_provenance_line_carries_the_cut_tokens(tmp_path: Path) -> None:
    kept = tmp_path / "kept"
    kept.mkdir()
    for n, cut_off in enumerate((70, 0)):
        pool = tmp_path / f"pool-{n}"
        author_session._note_session(pool, kept, _record(cut_off))
        (line,) = (json.loads(x) for x in (pool / author_session.SESSIONS).read_text().splitlines())
        if cut_off:
            assert line.get("tokens_not_in_binary_totals") == cut_off, RULE
        else:
            assert "tokens_not_in_binary_totals" not in line
