"""A decision's review time runs from when this server showed its view to when it was written.

ARCH-130 measures the time a person takes to decide an item, and logs an item that takes over a
minute as a decomposition defect. The time is born where a record may be: the server that renders
an item's view stamps when, in memory, under an id of its own making; the page sends the id back
with its decision, never a time; and the decision route writes the stamp into the same decision
line, marking it ``decomposition_defect`` when the decision came over one minute after it. A
decision with no recorded view (the command line, an id this server does not hold, a server started
since, a stamp a stepped-back clock puts after the decision) has no review time: null, never zero.
The route table keeps its one action.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_a_decision_taken_in_the_ui_is_the_one_the_command_writes import (
    Page,
    _copy,
    _decision,
    _view,
)
from ui_rig import context_over, escalated_run, fake_ui, serving

from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    PersonDecision,
    QueueResolution,
    ShownItem,
    queue_listing,
    read_queue,
    record_decision,
    statuses_now,
)

T0 = datetime(2026, 10, 31, 9, 0, 0, 250000, tzinfo=UTC)


@dataclass
class Clock:
    """The server's one wall clock, set by the test before each request."""

    now: datetime = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("built")
    return {"run": escalated_run(base), "ui": fake_ui(base / "checkout")}


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    held = Clock()
    monkeypatch.setattr(queue_module, "utc_now", held)
    return held


@pytest.fixture
def run_dir(built: dict[str, Path], tmp_path: Path) -> Path:
    return _copy(built, tmp_path / "ui-root")


@pytest.fixture
def page(built: dict[str, Path], run_dir: Path) -> Iterator[Page]:
    context = replace(context_over(run_dir.parent, ui_root=built["ui"]), operator="yasin")
    with serving(context) as live:
        yield Page(live.port, live.token)


def _line(run_dir: Path) -> dict[str, Any]:
    (line,) = (run_dir / DECISIONS_NAME).read_bytes().splitlines()
    decided: dict[str, Any] = json.loads(line)
    return decided


def _listed(run_dir: Path) -> dict[str, Any]:
    decided = queue_listing(run_dir)["decided"]
    assert isinstance(decided, list) and len(decided) == 1
    entry: dict[str, Any] = decided[0]
    return entry


def _shown_then_decided(page: Page, clock: Clock, after: timedelta) -> tuple[int, bytes]:
    clock.now = T0
    view = _view(page)
    clock.now = T0 + after
    return page.decide({**_decision(view), "view_id": view.get("view_id")})


def test_review_time_runs_from_the_servers_shown_at_to_the_decision(
    page: Page, run_dir: Path, clock: Clock
) -> None:
    status, answer = _shown_then_decided(page, clock, timedelta(seconds=42))
    assert status == 201, answer
    line = _line(run_dir)
    assert line.get("shown_at") == "2026-10-31T09:00:00.250000Z"
    assert line["ts"] == "2026-10-31T09:00:42.250000Z"
    assert "decomposition_defect" not in line
    assert _listed(run_dir).get("review_time") == {"value": 42.0, "unit": "s"}
    # What the route answers is the line as written.
    assert json.loads(answer)["resolved"] == line


def test_an_item_over_one_minute_writes_a_decomposition_defect_line(
    page: Page, run_dir: Path, clock: Clock
) -> None:
    status, answer = _shown_then_decided(page, clock, timedelta(seconds=61))
    assert status == 201, answer
    line = _line(run_dir)
    assert (line.get("shown_at"), line.get("decomposition_defect")) == (
        "2026-10-31T09:00:00.250000Z",
        True,
    )
    assert _listed(run_dir).get("review_time") == {"value": 61.0, "unit": "s"}


def test_a_decision_one_minute_after_its_view_is_no_defect(
    page: Page, run_dir: Path, clock: Clock
) -> None:
    status, answer = _shown_then_decided(page, clock, timedelta(minutes=1))
    assert status == 201, answer
    line = _line(run_dir)
    assert (line.get("shown_at"), "decomposition_defect" in line) == (
        "2026-10-31T09:00:00.250000Z",
        False,
    )


@pytest.mark.parametrize("sent", ["none", "unknown", "another_view"])
def test_a_decision_with_no_recorded_view_has_no_review_time(
    page: Page, run_dir: Path, clock: Clock, sent: str
) -> None:
    clock.now = T0
    view = _view(page)
    request = _decision(view)
    if sent == "unknown":
        request["view_id"] = "A" * 22
    if sent == "another_view":
        # The id of a view of this item whose line was another: the digest it was shown with.
        request["view_id"] = view.get("view_id")
        request["shown"] = {**request["shown"], "item_sha256": "0" * 64}  # type: ignore[dict-item]
    clock.now = T0 + timedelta(seconds=5)
    status, answer = page.decide(request)
    if sent == "another_view":
        # The view is stale, so nothing is written at all.
        assert status == 409, answer
        assert (run_dir / DECISIONS_NAME).read_bytes() == b""
        assert view.get("view_id") is not None
        return
    assert status == 201, answer
    line = _line(run_dir)
    assert "shown_at" not in line and "decomposition_defect" not in line
    entry = _listed(run_dir)
    assert "review_time" not in entry


def test_a_view_shown_by_a_server_since_stopped_has_no_review_time(
    built: dict[str, Path], run_dir: Path, clock: Clock
) -> None:
    context = replace(context_over(run_dir.parent, ui_root=built["ui"]), operator="yasin")
    with serving(context) as first:
        view = _view(Page(first.port, first.token))
    assert view.get("view_id") is not None
    clock.now = T0 + timedelta(seconds=5)
    with serving(replace(context, views=type(context.views)())) as second:
        status, answer = Page(second.port, second.token).decide(
            {**_decision(view), "view_id": view["view_id"]}
        )
    assert status == 201, answer
    assert "shown_at" not in _line(run_dir)


def test_a_view_stamped_after_the_decision_by_a_stepped_back_clock_writes_none(
    page: Page, run_dir: Path, clock: Clock
) -> None:
    status, answer = _shown_then_decided(page, clock, timedelta(seconds=-3))
    assert status == 201, answer
    line = _line(run_dir)
    assert line["ts"] == "2026-10-31T08:59:57.250000Z"
    assert "shown_at" not in line and "decomposition_defect" not in line
    assert "review_time" not in _listed(run_dir)


def test_a_decision_on_the_command_line_has_no_review_time(run_dir: Path, clock: Clock) -> None:
    # Bound to the view the command printed, as ``queue resolve`` binds it: no server showed it.
    view = read_queue(run_dir)
    item_id = view.items[0].item_id
    record_decision(
        run_dir,
        item_id,
        person=PersonDecision(verb="approve", note=None),
        resolved_by="yasin",
        shown=ShownItem(
            item_sha256=view.digests[item_id], trajectories=statuses_now(run_dir, item_id)
        ),
    )
    line = _line(run_dir)
    assert line["verb"] == "approve" and "shown_at" not in line
    entry = _listed(run_dir)
    assert "review_time" not in entry


@pytest.mark.parametrize("field", ["shown_at", "ts", "decided_ts"])
def test_the_page_never_sends_a_time(page: Page, run_dir: Path, field: str) -> None:
    view = _view(page)
    status, answer = page.decide({**_decision(view), field: "2026-10-31T09:00:00.000000Z"})
    assert status == 400, answer
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""


@pytest.mark.parametrize("view_id", ["", "short", "A" * 23, "A" * 21 + "/", 22])
def test_a_view_id_the_server_could_not_have_made_is_refused(
    page: Page, run_dir: Path, view_id: object
) -> None:
    status, answer = page.decide({**_decision(_view(page)), "view_id": view_id})
    assert status == 400, answer
    assert b"view" in answer
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""


# -- the line is held to its own times ------------------------------------------------------------


BOUND = {
    "item_id": "run-esc-s1",
    "kind": "resolution",
    "decision": "approve",
    "resolved_by": "yasin",
    "verb": "approve",
    "shown_sha256": "a" * 64,
}


def _refusal(fields: dict[str, Any]) -> str | None:
    try:
        QueueResolution.model_validate(fields)
    except ValueError as exc:
        return str(exc)
    return None


@pytest.mark.parametrize(
    ("fields", "said"),
    [
        # Over a minute, and not marked.
        (
            {"ts": "2026-10-31T09:01:00.250001Z", "shown_at": "2026-10-31T09:00:00.250000Z"},
            "exactly when",
        ),
        # Marked, and not over a minute.
        (
            {
                "ts": "2026-10-31T09:01:00.250000Z",
                "shown_at": "2026-10-31T09:00:00.250000Z",
                "decomposition_defect": True,
            },
            "exactly when",
        ),
        # Marked, with no view.
        ({"ts": "2026-10-31T09:05:00.000000Z", "decomposition_defect": True}, "exactly when"),
        # Shown after it was decided.
        (
            {"ts": "2026-10-31T09:00:00.000000Z", "shown_at": "2026-10-31T09:00:00.000001Z"},
            "shown before",
        ),
    ],
)
def test_a_decision_line_whose_mark_disagrees_with_its_times_is_refused(
    fields: dict[str, Any], said: str
) -> None:
    why = _refusal({**BOUND, **fields})
    assert why is not None and said in why, why


def test_a_view_stamp_belongs_to_a_decision_taken_on_a_view() -> None:
    free = {"item_id": "x", "kind": "resolution", "decision": "ok", "resolved_by": "yasin"}
    why = _refusal(
        {**free, "ts": "2026-10-31T09:00:10.000000Z", "shown_at": "2026-10-31T09:00:00.000000Z"}
    )
    assert why is not None and "belongs to a decision with a verb" in why, why
    fine = {**BOUND, "ts": "2026-10-31T09:00:10.000000Z", "shown_at": "2026-10-31T09:00:00.000000Z"}
    assert _refusal(fine) is None
    late = {**fine, "ts": "2026-10-31T09:02:00.000000Z", "decomposition_defect": True}
    assert _refusal(late) is None
    # Left out where absent, so every line written before review time keeps its bytes.
    bare = QueueResolution.model_validate({**BOUND, "ts": "2026-10-31T09:00:10.000000Z"})
    assert "shown_at" not in bare.model_dump_json()
    assert "decomposition_defect" not in bare.model_dump_json()


def test_the_register_holds_its_limit_dropping_the_oldest_and_matches_whole(clock: Clock) -> None:
    from physgate.ui.views import MAX_VIEWS, VIEW_ID_PATTERN, ViewRegister

    assert MAX_VIEWS == 4096
    views = ViewRegister(limit=2)
    run, digest = Path("/runs/r"), "a" * 64
    first = views.shown(run, "i1", digest)
    clock.now = T0 + timedelta(seconds=1)
    second = views.shown(run, "i2", digest)
    assert re.fullmatch(VIEW_ID_PATTERN, first) and first != second
    assert views.shown_at(first, run, "i1", digest) == T0
    views.shown(run, "i3", digest)
    assert views.shown_at(first, run, "i1", digest) is None  # the oldest, dropped
    assert views.shown_at(second, run, "i2", digest) == T0 + timedelta(seconds=1)
    for other in ((Path("/runs/s"), "i2", digest), (run, "i1", digest), (run, "i2", "b" * 64)):
        assert views.shown_at(second, *other) is None
    assert views.shown_at(None, run, "i2", digest) is None
