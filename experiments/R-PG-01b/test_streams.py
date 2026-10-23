"""Tests of streams.py (§5.5) and smoke.py (L10): invented streams, and the pinned binary's own.

Run explicitly, in the run checkout: ``uv run --frozen pytest -q experiments/R-PG-01b``.

The binary's tests run real review sessions of the pinned binary through the run commit's
reviewer, against the checkout's scripted endpoint, with a dummy token and no model call: the
endpoint answers the binary's token count for the invented sheet with the count a test names
(25,000, then 25,001), and the scripted reviewer reads the sheet as the test plans: whole, as a
page counted above the limit, a whole read repeated, a page repeated, and a read of a path that
does not exist before the right one. They need the binary 2.1.301 (``PHYSGATE_CLAUDE_BIN``);
where there is none they are skipped, unless ``RPB_REQUIRE_BINARY=1`` makes its absence a
failure, as on the run machine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import smoke  # noqa: E402
import streams as S  # noqa: E402
import testsupport as T  # noqa: E402

N = 20
LAST = "R9.99"


def numbered(first: int, last: int, last_row: bool = True) -> str:
    """The text a whole or part read returns: ``N\\t`` lines, the last row where it falls."""
    lines = []
    for n in range(first, last + 1):
        body = f'  "{LAST}": {{' if (n == N - 2 and last_row) else f"line {n}"
        lines.append(f"{n}\t{body}")
    return "\n".join(lines)


CWD = "/r/read/worktree"


def stream(*reads: tuple[Any, ...]) -> str:
    """An invented stream: for each read, its tool call and the result the model got.

    A read's third element, if given, is whether the binary marked that result an error.
    """
    events: list[dict[str, Any]] = [{"type": "system", "subtype": "init", "cwd": CWD}]
    for n, (tool_input, content, *flag) in enumerate(reads):
        tid = f"toolu_{n}"
        events.append(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": tid, "name": "Read", "input": tool_input}
                    ]
                },
            }
        )
        if content is not None:
            events.append(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tid,
                                "content": content,
                                "is_error": bool(flag and flag[0]),
                            }
                        ]
                    },
                    # A line count beside the result: never read.
                    "tool_use_result": {"file": {"numLines": 999999, "totalLines": 999999}},
                }
            )
    events.append({"type": "result", "usage": {"input_tokens": 3, "output_tokens": 4}})
    return "".join(json.dumps(e) + "\n" for e in events)


SHEET = "/r/read/worktree/parts_sheet.json"


def classes(text: str) -> list[str]:
    return [c.cls for c in S.classify_all(S.sheet_reads(text), N, LAST)]


def test_a_read_of_the_whole_file_that_returns_every_line_is_whole() -> None:
    assert classes(stream(({"file_path": SHEET}, numbered(1, N)))) == ["whole"]


def test_a_read_that_returns_fewer_lines_than_it_asked_for_is_cut() -> None:
    assert classes(stream(({"file_path": SHEET}, numbered(1, N - 5)))) == ["cut"]


def test_a_read_one_line_short_of_what_it_asked_for_is_cut() -> None:
    # the last row falls before the missing line, so only the count tells
    assert classes(stream(({"file_path": SHEET}, numbered(1, N - 1)))) == ["cut"]
    page = stream(({"file_path": SHEET, "offset": 3, "limit": 5}, numbered(3, 6)))
    assert classes(page) == ["cut"]


def test_a_read_to_the_end_without_the_last_row_is_cut_even_with_every_line() -> None:
    assert classes(stream(({"file_path": SHEET}, numbered(1, N, last_row=False)))) == ["cut"]


def test_a_reviewer_s_own_paging_is_part_and_together_covers_every_line() -> None:
    text = stream(
        ({"file_path": SHEET, "offset": 1, "limit": 10}, numbered(1, 10)),
        ({"file_path": SHEET, "offset": 11, "limit": 10}, numbered(11, N)),
    )
    assert classes(text) == ["part", "part"]
    found = S.session_reads_text(text, N, LAST)
    assert found["covered_every_line"] and found["part"] == 2 and found["cut"] == 0


def test_a_page_short_of_its_limit_is_cut_whatever_its_offset() -> None:
    text = stream(({"file_path": SHEET, "offset": 5, "limit": 6}, numbered(5, 8)))
    assert classes(text) == ["cut"]


def test_a_page_that_numbers_from_another_line_returned_none_of_its_lines() -> None:
    text = stream(({"file_path": SHEET, "offset": 5, "limit": 3}, numbered(1, 3)))
    assert classes(text) == ["cut"]


def test_a_read_whose_result_never_came_is_no_result_and_voids_nothing() -> None:
    text = stream(({"file_path": SHEET}, None))
    assert classes(text) == ["no_result"]
    found = S.session_reads_text(text, N, LAST)
    assert found["no_result"] == 1 and found["cut"] == 0


# ---- the binary's stubs and errors (the reading of 23.10.2026) ----

#: The pinned binary's three texts for a Read it did not repeat, as a session receives them.
STUB_FILE = (
    "File unchanged since last read. The content from the earlier Read tool_result in this "
    "conversation is still current \u2014 refer to that instead of re-reading."
)
STUB_WASTED = (
    "Wasted call \u2014 file unchanged since your last Read. Refer to that earlier tool_result "
    "instead."
)
STUB_CONTEXT = (
    f'<system-reminder>This file is already in your context (see "Contents of {SHEET}" above) '
    "and has not changed on disk. Use that content instead of re-reading.</system-reminder>"
)
LIMIT_ERROR = (
    "File content (25001 tokens) exceeds maximum allowed tokens (25000). Use offset and limit "
    "parameters to read specific portions of the file, or search for specific content instead "
    "of reading the whole file."
)


@pytest.mark.parametrize("stub", [STUB_FILE, STUB_WASTED, STUB_CONTEXT])
def test_a_stub_after_a_whole_read_of_the_range_is_unchanged(stub: str) -> None:
    text = stream(({"file_path": SHEET}, numbered(1, N)), ({"file_path": SHEET}, stub))
    assert classes(text) == ["whole", "unchanged"]
    found = S.session_reads_text(text, N, LAST)
    assert found["unchanged"] == 1 and found["cut"] == 0 and found["covered_every_line"]


@pytest.mark.parametrize("stub", [STUB_FILE, STUB_WASTED, STUB_CONTEXT])
def test_a_stub_with_no_earlier_read_fails_closed_as_cut(stub: str) -> None:
    assert classes(stream(({"file_path": SHEET}, stub))) == ["cut"]


def test_a_stub_is_unchanged_only_where_an_earlier_read_returned_its_whole_range() -> None:
    text = stream(
        ({"file_path": SHEET, "offset": 1, "limit": 10}, numbered(1, 10)),
        ({"file_path": SHEET, "offset": 1, "limit": 10}, STUB_WASTED),
        ({"file_path": SHEET, "offset": 5, "limit": 3}, STUB_WASTED),
        # the earlier page held lines 1 to 10; this asks for 5 to the end
        ({"file_path": SHEET, "offset": 5}, STUB_WASTED),
    )
    assert classes(text) == ["part", "unchanged", "unchanged", "cut"]


def test_a_stub_after_a_cut_read_is_cut() -> None:
    text = stream(({"file_path": SHEET}, numbered(1, N - 5)), ({"file_path": SHEET}, STUB_WASTED))
    assert classes(text) == ["cut", "cut"]


def test_a_stub_counts_an_earlier_read_of_the_same_path_alone() -> None:
    other = "/elsewhere/parts_sheet.json"
    text = stream(({"file_path": other}, numbered(1, N)), ({"file_path": SHEET}, STUB_WASTED))
    assert classes(text) == ["whole", "cut"]
    # a relative path is the binary's: against the session's working directory
    text = stream(
        ({"file_path": SHEET}, numbered(1, N)), ({"file_path": "parts_sheet.json"}, STUB_WASTED)
    )
    assert classes(text) == ["whole", "unchanged"]


def test_a_result_the_binary_marked_an_error_is_error_and_voids_nothing() -> None:
    missing = "File does not exist. Note: your current working directory is /r/read/worktree."
    text = stream(
        ({"file_path": "/r/read/parts_sheet.json"}, missing, True),
        ({"file_path": SHEET}, numbered(1, N)),
    )
    assert classes(text) == ["error", "whole"]
    found = S.session_reads_text(text, N, LAST)
    assert (found["error"], found["whole"], found["cut"]) == (1, 1, 0)


@pytest.mark.parametrize("is_error", [True, False])
def test_the_binary_s_token_limit_error_is_cut(is_error: bool) -> None:
    text = stream(({"file_path": SHEET, "offset": 1, "limit": 10}, LIMIT_ERROR, is_error))
    assert classes(text) == ["cut"]


def test_a_stub_marked_an_error_is_still_a_stub() -> None:
    text = stream(({"file_path": SHEET}, numbered(1, N)), ({"file_path": SHEET}, STUB_WASTED, True))
    assert classes(text) == ["whole", "unchanged"]


def test_a_result_given_as_text_blocks_is_read_as_its_text() -> None:
    blocks = [{"type": "text", "text": numbered(1, N)}]
    assert classes(stream(({"file_path": SHEET}, blocks))) == ["whole"]


def test_reads_of_other_files_are_not_counted() -> None:
    text = stream(({"file_path": "/r/read/rubric.md"}, numbered(1, 3)))
    assert S.sheet_reads(text) == []


def test_a_round_reads_a_session_under_the_root_that_no_log_names(tmp_path: Path) -> None:
    run, root = tmp_path / "run", tmp_path / "root"
    named, stray = (f"00000000-0000-4000-8000-00000000000{n}" for n in (1, 2))
    T.write_jsonl(run / "events.jsonl", [T.ran("r1", "fail", [], session=named)])
    T.write_jsonl(run / "controls" / "events.jsonl", [])
    whole = stream(({"file_path": SHEET}, numbered(1, C.SHEET_LINES["F"])))
    cut = stream(({"file_path": SHEET}, numbered(1, 5)))
    for sid, text in ((named, whole), (stray, cut)):
        (root / sid / "session").mkdir(parents=True)
        (root / sid / "session" / "stdout.jsonl").write_text(text)
    found = S.round_counts(run, root, "F")
    assert found["sides"]["not_in_a_log"]["reviews"] == 1
    assert found["sides"]["not_in_a_log"]["cut"] == 1 and found["cut"] >= 1


def test_a_round_reports_unchanged_error_and_no_result_reads_and_is_not_void(
    tmp_path: Path,
) -> None:
    run, root = tmp_path / "run", tmp_path / "root"
    sid = "00000000-0000-4000-8000-000000000001"
    T.write_jsonl(run / "events.jsonl", [T.ran("r1", "fail", [], session=sid)])
    T.write_jsonl(run / "controls" / "events.jsonl", [])
    lines = C.SHEET_LINES["I"]
    body = "\n".join(
        f"{n}\t" + (f'"{C.LAST_ROW_ID}": {{' if n == lines else "x") for n in range(1, lines + 1)
    )
    text = stream(
        ({"file_path": "/r/read/parts_sheet.json"}, "File does not exist.", True),
        ({"file_path": SHEET}, body),
        ({"file_path": SHEET}, STUB_WASTED),
        ({"file_path": SHEET}, None),
    )
    (root / sid / "session").mkdir(parents=True)
    (root / sid / "session" / "stdout.jsonl").write_text(text)
    found = S.round_counts(run, root, "I")
    inj = found["sides"]["injected"]
    assert (inj["whole"], inj["unchanged"], inj["error"], inj["no_result"]) == (1, 1, 1, 1)
    assert found["cut"] == 0 and inj["covered_every_line"] == 1


def test_a_round_counts_each_side_and_lists_a_missing_stream_as_unknown(tmp_path: Path) -> None:
    run, root = tmp_path / "run", tmp_path / "root"
    sids = [f"00000000-0000-4000-8000-00000000000{n}" for n in range(4)]
    T.write_jsonl(
        run / "events.jsonl",
        [
            T.ran("r1", "fail", [], session=sids[0]),
            T.unavailable("r2", "infrastructure", True, session=sids[1]),
            T.ran("r2", "pass", [], session=sids[2]),
        ],
    )
    T.write_jsonl(run / "controls" / "events.jsonl", [T.ran("t1", "pass", [], session=sids[3])])
    whole = stream(({"file_path": SHEET}, numbered(1, C.SHEET_LINES["F"], last_row=False)))
    for sid, text in ((sids[0], whole), (sids[2], stream())):
        (root / sid / "session").mkdir(parents=True)
        (root / sid / "session" / "stdout.jsonl").write_text(text)
    found = S.round_counts(run, root, "F")
    inj = found["sides"]["injected"]
    assert (inj["reviews"], inj["stream_missing_unknown"], inj["read_the_sheet"]) == (3, 1, 1)
    assert inj["cut"] == 1  # the invented text lacks the pinned last row id
    assert found["sides"]["twin"]["stream_missing_unknown"] == 1
    assert found["cut"] == 1


# ---- the pinned binary's own streams, from the scripted endpoint ----


def _binary() -> str:
    found = os.environ.get("PHYSGATE_CLAUDE_BIN", "")
    ok = bool(found) and Path(found).is_file()
    if ok:
        version = subprocess.run(
            [found, "--version"], capture_output=True, text=True, check=False, timeout=120
        ).stdout
        ok = version.split(" ")[0].strip() == C.BINARY_VERSION
    if not ok:
        if os.environ.get("RPB_REQUIRE_BINARY") == "1":
            pytest.fail("the pinned binary 2.1.301 is required here (PHYSGATE_CLAUDE_BIN)")
        pytest.skip("no pinned binary 2.1.301 on this machine (PHYSGATE_CLAUDE_BIN)")
    return found


def _page(offset: int, limit: int) -> T.Reads:
    return lambda cwd: [{"file_path": f"{cwd}/parts_sheet.json", "offset": offset, "limit": limit}]


#: Each planned session: the count the endpoint gives the sheet's text, and the reviewer's reads.
PLANS: dict[str, tuple[int, T.Reads]] = {
    "k25000": (25_000, T.whole_read),
    "k25001": (25_001, T.whole_read),
    "p25001": (25_001, _page(1, 600)),
    "again": (10_000, lambda cwd: T.whole_read(cwd) * 2),
    "pages": (
        10_000,
        lambda cwd: _page(1, 600)(cwd) + _page(601, 700)(cwd) + _page(601, 700)(cwd),
    ),
    "elsewhere": (
        10_000,
        lambda cwd: [{"file_path": f"{Path(cwd).parent}/parts_sheet.json"}, *T.whole_read(cwd)],
    ),
}


@pytest.fixture(scope="module")
def counted(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """One real session per plan, through the run commit's reviewer, with no model call."""
    _binary()
    base = tmp_path_factory.mktemp("counted")
    sheet = T.invented_sheet()
    found = {}
    saved = {k: os.environ.get(k) for k in ("ANTHROPIC_BASE_URL", C.TOKEN_VARIABLE)}
    os.environ[C.TOKEN_VARIABLE] = T.DUMMY_TOKEN
    try:
        for name, (count, reads) in PLANS.items():
            out = base / f"out-{name}"
            out.mkdir()
            with T.counting_endpoint(count) as (api, url, counts):
                T.read_sheet_then_review(api, reads)
                os.environ["ANTHROPIC_BASE_URL"] = url
                record = smoke.session(
                    out, base / f"r{name}", sheet, fallback=False, install=base / "i", label=name
                )
            stream = base / f"r{name}" / str(record["session_id"]) / "session" / "stdout.jsonl"
            classes = S.session_reads(stream, C.SHEET_LINES["F"]).get("classes")
            found[name] = {
                "record": record,
                "counts": counts,
                "refusals": api.refusals,
                "classes": classes,
            }
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return found


@pytest.mark.parametrize(("name", "cls"), [("k25000", "whole"), ("k25001", "cut")])
def test_the_binary_s_read_counted_at_the_limit_is_whole_and_one_more_is_cut(
    counted: dict[str, dict[str, Any]], name: str, cls: str
) -> None:
    found = counted[name]
    assert found["refusals"] == []
    # The binary asked the service to count the sheet's text, and was told this count.
    assert sum(c["sheet"] for c in found["counts"]) == 1
    reads = found["record"]["reads"]
    assert reads["missing"] is False and reads["reads"] == 1
    assert reads[cls] == 1 and reads["whole" if cls == "cut" else "cut"] == 0
    assert reads["covered_every_line"] is (cls == "whole")
    assert found["record"]["result_line"] is True


@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("p25001", ["cut"]),
        ("again", ["whole", "unchanged"]),
        ("pages", ["part", "part", "unchanged"]),
        ("elsewhere", ["error", "whole"]),
    ],
)
def test_the_binary_s_own_page_repeat_and_missing_path_are_classed(
    counted: dict[str, dict[str, Any]], name: str, want: list[str]
) -> None:
    found = counted[name]
    assert found["refusals"] == [] and found["record"]["result_line"] is True
    assert found["classes"] == want
    reads = found["record"]["reads"]
    assert reads["cut"] == want.count("cut")
    assert reads["covered_every_line"] is (name != "p25001")


# ---- L10's rule, with the sessions invented ----


def _l10(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plan: list[dict[str, Any]]
) -> tuple[int, dict[str, Any]]:
    runs: list[str] = []

    def fake(
        out: Path, root: Path, sheet: bytes, *, fallback: bool, install: Path, label: str
    ) -> dict[str, Any]:
        runs.append(label)
        reads = plan[len(runs) - 1]
        return {
            "kind": "check" if fallback else "smoke",
            "label": label,
            "reads": reads,
            "tokens_total": 1000 * len(runs),
            "started_utc": "s",
            "ended_utc": "e",
        }

    monkeypatch.setattr(smoke, "session", fake)
    code, record = smoke.l10(tmp_path, tmp_path / "root", b"{}")
    return code, {**record, "labels": runs}


def _reads(whole: int = 0, part: int = 0, cut: int = 0) -> dict[str, Any]:
    return {"missing": False, "reads": whole + part + cut, "whole": whole, "part": part, "cut": cut}


def test_l10_passes_on_a_smoke_with_a_whole_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, record = _l10(tmp_path, monkeypatch, [_reads(), _reads(whole=1)])
    assert code == 0 and record["labels"] == ["smoke-1", "smoke-2"]
    assert record["smoke_tokens_max"] == 2000


def test_l10_stops_at_a_cut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code, _ = _l10(tmp_path, monkeypatch, [_reads(whole=1, cut=1)])
    assert code == 3


def test_l10_runs_the_check_session_after_three_smokes_with_no_whole_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, record = _l10(
        tmp_path, monkeypatch, [_reads(), _reads(part=2), _reads(), _reads(whole=1)]
    )
    assert code == 0 and record["labels"] == ["smoke-1", "smoke-2", "smoke-3", "check-1"]
    (tmp_path / "b").mkdir()
    code, _ = _l10(tmp_path / "b", monkeypatch, [_reads(), _reads(), _reads(), _reads()])
    assert code == 4


def test_l10_fails_as_infrastructure_when_a_session_leaves_no_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _ = _l10(tmp_path, monkeypatch, [{"missing": True}])
    assert code == 1


def test_the_check_session_s_prompt_is_one_line_asking_for_the_sheet() -> None:
    line = smoke.fallback_prompt("/x/read")
    assert "\n" not in line and line.endswith("then stop.")
    assert "/x/read/worktree/parts_sheet.json" in line
