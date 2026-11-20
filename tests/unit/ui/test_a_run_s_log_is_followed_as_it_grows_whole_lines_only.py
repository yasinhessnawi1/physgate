"""A page follows a running run's log as it grows: from a line on, whole lines only.

The log is appended by another process while the page reads it, so a read can meet a line the
writer has only half written. The route a page follows the log by reads it through the same
reader as the whole-log route, which stops before a final line without its newline, and serves
the lines from the one the page asks for, rendered as the whole-log route renders them. So what
it serves is always a suffix of what the whole-log route serves at that moment: never more, never
a key that route leaves out, never a torn line.

The page asks again from the last line it holds, which comes back too: that overlap, compared
byte for byte, is how it knows the log it follows is the one it read before, and a log that
shrank or was replaced is read again from the start. Nothing is written into the run.
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

import pytest
from ui_rig import Live, context_over, fake_ui, real_runs, serving, snapshot

RUN = "run-on"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("built")
    return {"runs": real_runs(base), "ui": fake_ui(base / "checkout")}


def _world(built: dict[str, Path], tmp_path: Path) -> tuple[Path, list[bytes]]:
    """A root holding a copy of the run, and the copy's log as its lines (newlines kept)."""
    root = tmp_path / "root"
    shutil.copytree(
        built["runs"] / RUN, root / RUN, symlinks=True, ignore=shutil.ignore_patterns("worktrees")
    )
    lines = (root / RUN / "events.jsonl").read_bytes().splitlines(keepends=True)
    assert len(lines) > 4, "the fixture run's log is too short to follow"
    return root, lines


def _tail(live: Live, start: int) -> dict[str, object]:
    status, _, body = live.request("GET", f"/api/runs/0/{RUN}/events/from/{start}")
    assert status == 200, body[:300]
    answer = json.loads(body)
    assert isinstance(answer, dict)
    return answer


def _whole(live: Live) -> str:
    status, _, body = live.request("GET", f"/api/runs/0/{RUN}/events")
    assert status == 200, body[:300]
    return body.decode()


def test_from_the_first_line_it_serves_exactly_what_the_whole_log_route_serves(
    built: dict[str, Path], tmp_path: Path
) -> None:
    root, lines = _world(built, tmp_path)
    with serving(context_over(root, ui_root=built["ui"])) as live:
        whole = _whole(live)
        answer = _tail(live, 0)
    assert answer["lines"] == whole
    assert answer["count"] == len(lines) == len(whole.splitlines())
    assert answer["from"] == 0


def test_from_any_line_it_serves_the_whole_log_route_s_lines_from_that_one_on(
    built: dict[str, Path], tmp_path: Path
) -> None:
    root, lines = _world(built, tmp_path)
    with serving(context_over(root, ui_root=built["ui"])) as live:
        whole = _whole(live).splitlines(keepends=True)
        for start in range(len(lines) + 2):
            answer = _tail(live, start)
            assert answer["lines"] == "".join(whole[start:]), start
            assert answer["count"] == len(lines)
            served = [json.loads(line)["seq"] for line in str(answer["lines"]).splitlines()]
            assert served == list(range(start, len(lines)))


def test_a_half_written_last_line_is_never_served_and_its_completion_is_served_once(
    built: dict[str, Path], tmp_path: Path
) -> None:
    root, lines = _world(built, tmp_path)
    log = root / RUN / "events.jsonl"
    last = lines[-1]
    half = len(last) // 2
    log.write_bytes(b"".join(lines[:-1]) + last[:half])
    with serving(context_over(root, ui_root=built["ui"])) as live:
        before = _tail(live, 0)
        assert before["count"] == len(lines) - 1
        text = str(before["lines"])
        assert text.endswith("\n")
        assert last[:half].decode() not in text
        # The page asks again from the last line it holds: that line comes back, nothing after it.
        held = len(lines) - 2
        again = _tail(live, held)
        assert again["lines"] == text.splitlines(keepends=True)[held]
        # The writer finishes the line: it is served, once, after the overlap.
        with log.open("ab") as handle:
            handle.write(last[half:])
        after = _tail(live, held)
        served = str(after["lines"]).splitlines(keepends=True)
        assert after["count"] == len(lines)
        assert served[0] == text.splitlines(keepends=True)[held]
        assert len(served) == 2
        assert json.loads(served[1])["seq"] == len(lines) - 1
        assert str(after["lines"]) == "".join(_whole(live).splitlines(keepends=True)[held:])


def test_a_log_written_byte_by_byte_while_it_is_followed_is_only_ever_served_in_whole_lines(
    built: dict[str, Path], tmp_path: Path
) -> None:
    """The writer appends the run's last lines in small pieces while the page asks again and again.

    Every answer ends in a newline and every line in it parses; followed from the last line held,
    with the overlap checked each time, the lines gathered are the final log's, each once.
    """
    root, lines = _world(built, tmp_path)
    log = root / RUN / "events.jsonl"
    kept = 2
    log.write_bytes(b"".join(lines[:kept]))
    rest = b"".join(lines[kept:])
    done = threading.Event()

    def write() -> None:
        with log.open("ab", buffering=0) as handle:
            for at in range(0, len(rest), 7):
                handle.write(rest[at : at + 7])
        done.set()

    with serving(context_over(root, ui_root=built["ui"])) as live:
        held = str(_tail(live, 0)["lines"]).splitlines(keepends=True)
        writer = threading.Thread(target=write)
        writer.start()
        asked = 0
        while not done.is_set() or len(held) < len(lines):
            answer = _tail(live, len(held) - 1)
            text = str(answer["lines"])
            assert text.endswith("\n")
            served = text.splitlines(keepends=True)
            for line in served:
                json.loads(line)
            assert served[0] == held[-1], "the overlap is the line the page holds"
            held += served[1:]
            asked += 1
            assert asked < 100_000
        writer.join()
        assert "".join(held) == _whole(live)
    assert [json.loads(line)["seq"] for line in held] == list(range(len(lines)))


def test_a_log_the_reader_refuses_is_refused_here_as_by_the_whole_log_route(
    built: dict[str, Path], tmp_path: Path
) -> None:
    root, lines = _world(built, tmp_path)
    log = root / RUN / "events.jsonl"
    log.write_bytes(b"".join(lines[:3]) + b'{"kind": "not a line"}\n' + b"".join(lines[3:]))
    with serving(context_over(root, ui_root=built["ui"])) as live:
        whole_status, _, whole_body = live.request("GET", f"/api/runs/0/{RUN}/events")
        tail_status, _, tail_body = live.request("GET", f"/api/runs/0/{RUN}/events/from/4")
    assert whole_status == tail_status == 422
    assert json.loads(tail_body)["error"] == json.loads(whole_body)["error"]


def test_following_the_log_writes_nothing_into_the_run(
    built: dict[str, Path], tmp_path: Path
) -> None:
    root, lines = _world(built, tmp_path)
    before = snapshot(root)
    with serving(context_over(root, ui_root=built["ui"])) as live:
        for start in (0, len(lines) - 1, len(lines) + 5):
            _tail(live, start)
    assert snapshot(root) == before


@pytest.mark.parametrize("start", ["-1", "01", "1.0", "1e3", "a", "1234567890"])
def test_a_line_that_is_not_a_plain_count_is_no_route(
    built: dict[str, Path], tmp_path: Path, start: str
) -> None:
    root, _ = _world(built, tmp_path)
    with serving(context_over(root, ui_root=built["ui"])) as live:
        status, _, _ = live.request("GET", f"/api/runs/0/{RUN}/events/from/{start}")
    assert status == 404
