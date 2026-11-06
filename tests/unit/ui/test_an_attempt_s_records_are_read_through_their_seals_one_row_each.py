"""One attempt's simulation records, each read through the seal its session's end recorded.

The route reads exactly the records the reader's own rule says the attempt sealed (the rule the
change check and the review packet use), each by a path built from the log's validated ids, held
to the allowlist, and read by the series reader, which holds it to its digest and length. Nothing
else under the run's series directory is opened or named.

Each record is answered with its title, group, axis, inputs, the code that produced it, and per
column the very summary the reviewer's listing gives. A record that cannot be read as sealed (it
changed, it is gone, it is a link or has a second name, it is not a regular file, it points into
the held-out tier, a corpus or a credential, or its sealed bytes are not a record this version
admits) is a row of its own that says why, with its seal, and never empties the rest. No body
carries an absolute path or a byte of a refused record.

The runs are made by the real loop with the real gate (see ``ui_series_rig``).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from ui_rig import RECORDER, context_over, fake_ui, serving, snapshot
from ui_series_rig import BIG_SEED, bound_run, series_runs

from physgate.orchestrator.events import SessionEnded, read_events
from physgate.series import reader, summary
from physgate.series.reader import SealedEntry, attempt_records, read_record
from physgate.ui import simulation
from physgate.ui.routes import PARAMETERS
from physgate.ui.table import ROUTES, RUN

#: Spellings no parameter may match, in every slot of the attempt route.
HOSTILE = ("..", "%2e%2e", "%252e%252e", "..%2f..%2fheld", "%2fetc", "a%00b", ".hidden", "%", "%ZZ")
#: The budget a cold read of an attempt is held to: this many times the time it takes to read
#: the same records' bytes and hash them, measured in the same process, interleaved.
BUDGET_RATIO = 45


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The series runs, the per-session-bound run, a held-out tier and a build; built once."""
    base = tmp_path_factory.mktemp("series")
    runs = base / "runs"
    series_runs(base, runs)
    bound_run(base, runs)
    held = base / "held"
    held.mkdir()
    (held / "scenario.json").write_text('{"marker": "held-out-marker"}')
    return {"base": base, "runs": runs, "held": held, "ui": fake_ui(base / "checkout")}


def _context(world: dict[str, Path], root: Path | None = None) -> Any:  # noqa: ANN401
    return context_over(root or world["runs"], ui_root=world["ui"], held_out=(str(world["held"]),))


def _request(
    world: dict[str, Path], target: str, root: Path | None = None
) -> tuple[int, dict[str, str], bytes]:
    with serving(_context(world, root)) as live:
        return live.request("GET", target)


def _read(
    world: dict[str, Path], name: str, subtask: str, attempt: int, root: Path | None = None
) -> dict[str, Any]:
    status, _, body = _request(world, f"/api/runs/0/{name}/series/{subtask}/{attempt}", root)
    assert status == 200, body
    answer: dict[str, Any] = json.loads(body)
    return answer


def _events(run: Path) -> list[Any]:
    return read_events(run / "events.jsonl")


def _sealed(run: Path) -> list[tuple[str, int]]:
    """Every attempt of ``run`` that sealed a record, in log order."""
    keys: dict[tuple[str, int], None] = {}
    for e in _events(run):
        if isinstance(e, SessionEnded) and e.series.records:
            keys.setdefault((e.subtask_id, e.attempt), None)
    return list(keys)


def _copy(world: dict[str, Path], name: str, tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "runs"
    target = root / name
    shutil.copytree(
        world["runs"] / name, target, symlinks=True, ignore=shutil.ignore_patterns("worktrees")
    )
    return root, target


def _first(run: Path) -> SealedEntry:
    """The first attempt's record with the smallest id: the one the refusal tests change."""
    subtask, attempt = _sealed(run)[0]
    return attempt_records(_events(run), subtask, attempt)[0]


def test_the_attempt_route_is_one_read_placed_after_the_listing() -> None:
    patterns = [route.pattern for route in ROUTES]
    attempt = f"{RUN}/series/{{subtask:subtask}}/{{attempt:attempt}}"
    assert attempt in patterns, "one attempt's records are read by a route of their own"
    (route,) = [r for r in ROUTES if r.pattern == attempt]
    assert (route.kind, route.method) == ("read", "GET")
    assert patterns.index(attempt) == patterns.index(f"{RUN}/series") + 1
    assert [r.kind for r in ROUTES].count("act") == 1


def test_the_route_types_are_the_reader_s_own_spelling_and_refuse_every_hostile_one() -> None:
    from urllib.parse import unquote

    subtask, attempt = PARAMETERS.get("subtask"), PARAMETERS.get("attempt")
    assert subtask is not None and attempt is not None, "both route types exist"
    for bad in HOSTILE:
        assert subtask.fullmatch(unquote(bad)) is None, bad
        assert attempt.fullmatch(unquote(bad)) is None, bad
    assert [n for n in ("0", "10", "-1", "1.0", "", "１") if attempt.fullmatch(n)] == []
    assert [n for n in "123456789" if attempt.fullmatch(n)] == list("123456789")
    assert subtask.fullmatch("-x") is None and subtask.fullmatch("a" * 65) is None
    assert subtask.fullmatch("a" * 64) is not None
    # The reader's own pattern object, not a copy that could drift from it.
    assert subtask is getattr(reader, "SUBTASK_PATTERN", None)


def test_an_attempt_past_the_last_one_a_subtask_gets_is_404_before_any_record_is_sought(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series"
    subtask, _ = _sealed(run)[0]
    with serving(_context(world)) as live, RECORDER.recording():
        status, _, body = live.request("GET", f"/api/runs/0/run-series/series/{subtask}/5")
    assert status == 404, body
    assert "no such attempt" in json.loads(body)["error"]
    assert [p for p in RECORDER.opened if f"{os.sep}series{os.sep}" in p] == []


def test_an_attempt_that_sealed_nothing_is_404(world: dict[str, Path]) -> None:
    run = world["runs"] / "run-series-refused"
    refused_attempt = next(
        (e.subtask_id, e.attempt)
        for e in _events(run)
        if isinstance(e, SessionEnded) and not e.series.records
    )
    subtask, attempt = refused_attempt
    status, _, body = _request(world, f"/api/runs/0/run-series-refused/series/{subtask}/{attempt}")
    assert status == 404, body
    assert "sealed no" in json.loads(body)["error"]
    status, _, _ = _request(world, f"/api/runs/0/run-series/series/{subtask}/4")
    assert status == 404


def _summary(column: Any) -> dict[str, Any]:  # noqa: ANN401
    column_summary = getattr(summary, "column_summary", None)
    assert callable(column_summary)
    found = column_summary(column)
    return {
        "name": column.name,
        "unit": found.unit,
        "samples": found.samples,
        "first": found.first,
        "last": found.last,
        "smallest": found.smallest,
        "largest": found.largest,
    }


def test_each_record_is_served_with_the_review_s_own_summaries_and_its_seal(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series"
    events = _events(run)
    commits = {e.session_id: e.attempt_commit for e in events if isinstance(e, SessionEnded)}
    keys = _sealed(run)
    assert len(keys) == 2
    loops = 0
    for subtask, attempt in keys:
        answer = _read(world, "run-series", subtask, attempt)
        assert (answer["subtask_id"], answer["attempt"]) == (subtask, attempt)
        sealed = attempt_records(events, subtask, attempt)
        assert [r["record_id"] for r in answer["records"]] == [e.record.record_id for e in sealed]
        for row, entry in zip(answer["records"], sealed, strict=True):
            record = read_record(entry.path(run), entry.seal())
            assert "refused" not in row, row
            assert row["session_id"] == entry.session_id
            assert (row["sha256"], row["length"]) == (entry.record.sha256, entry.record.length)
            assert (row["title"], row["group"], row["axis"]) == (
                record.title,
                record.group,
                record.axis,
            )
            assert row["x"] == _summary(record.x)
            assert row["traces"] == [_summary(t) for t in record.traces]
            assert row["inputs"] == {
                name: {"value": given.value, "unit": given.unit}
                for name, given in record.inputs.items()
            }
            assert row["producer"]["script"] == {
                "path": record.producer.script.path,
                "sha256": record.producer.script.sha256,
                "blob": entry.record.script_blob,
            }
            blobs = {code.path: code.blob for code in entry.record.loaded}
            assert row["producer"]["loaded"] == [
                {"path": code.path, "sha256": code.sha256, "blob": blobs.get(code.path)}
                for code in record.producer.loaded
            ]
            assert row["environment"] == [
                {"path": code.path, "sha256": code.sha256} for code in entry.record.environment
            ]
            assert row["attempt_commit"] == commits[entry.session_id]
            assert row["loop"] is (entry.record.record_id == "loop_nominal")
            loops += row["loop"]
    assert loops == 2


def test_only_the_sealed_records_and_the_log_are_opened(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root, run = _copy(world, "run-series-retried", tmp_path)
    subtask, attempt = _sealed(run)[0]
    sealed = attempt_records(_events(run), subtask, attempt)
    where = sealed[0].path(run).parent
    (where / "unsealed_extra.json").write_text('{"format": "series.v1"}')
    outside = tmp_path / "elsewhere.json"
    outside.write_text("outside every root")
    os.symlink(outside, where / "linked_out.json")
    os.mkfifo(where.parent / "piped.json")
    assert (run / "series" / "_refused").is_dir() and (run / "series" / "_discarded").is_dir()
    with serving(_context(world, root)) as live, RECORDER.recording() as writes:
        status, _, body = live.request("GET", f"/api/runs/0/run-series-retried/series/{subtask}/1")
    assert status == 200, body
    assert writes == []
    real = os.path.realpath(run)
    opened = {os.path.realpath(p) for p in RECORDER.opened if os.path.realpath(p).startswith(real)}
    assert opened == {os.path.realpath(run / "events.jsonl")} | {
        os.path.realpath(e.path(run)) for e in sealed
    }
    assert [p for p in RECORDER.listed if os.path.realpath(p).startswith(real)] == []
    for planted in (b"unsealed_extra", b"linked_out", b"piped", b"outside every root"):
        assert planted not in body


def test_a_later_session_s_record_is_served_in_place_of_the_one_it_superseded(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series-retried"
    events = _events(run)
    first, retry = [e for e in events if isinstance(e, SessionEnded) and e.attempt == 1][:2]
    answer = _read(world, "run-series-retried", first.subtask_id, 1)
    rows = [(r["record_id"], r["session_id"]) for r in answer["records"]]
    assert rows == [
        (e.record.record_id, e.session_id) for e in attempt_records(events, first.subtask_id, 1)
    ]
    assert {session for _, session in rows} == {retry.session_id}
    assert len(rows) == 6


def _change(entry: SealedEntry, run: Path, tmp_path: Path, how: str) -> None:
    path = entry.path(run)
    data = path.read_bytes()
    if how == "a byte changed":
        at = data.index(b'"values": [') + len(b'"values": [')
        path.write_bytes(data[:at] + (b"9" if data[at : at + 1] != b"9" else b"8") + data[at + 1 :])
    elif how == "its length changed":
        path.write_bytes(data + b" ")
    elif how == "gone":
        path.unlink()
    elif how == "a link inside the run":
        twin = path.with_name("twin_elsewhere.json")
        twin.write_bytes(data)
        path.unlink()
        os.symlink(twin, path)
    elif how == "a link out of the roots":
        outside = tmp_path / "outside.json"
        outside.write_bytes(data)
        path.unlink()
        os.symlink(outside, path)
    elif how == "a second name":
        os.link(path, tmp_path / "second_name.json")
    elif how == "a fifo in its place":
        path.unlink()
        os.mkfifo(path)
    else:
        raise AssertionError(how)


@pytest.mark.parametrize(
    "how",
    [
        "a byte changed",
        "its length changed",
        "gone",
        "a link inside the run",
        "a link out of the roots",
        "a second name",
        "a fifo in its place",
    ],
)
def test_a_record_not_as_sealed_is_a_refused_row_and_every_other_row_stays(
    world: dict[str, Path], tmp_path: Path, how: str
) -> None:
    root, run = _copy(world, "run-series", tmp_path)
    entry = _first(run)
    sealed = attempt_records(_events(run), entry.subtask_id, entry.attempt)
    _change(entry, run, tmp_path, how)
    status, _, body = _request(
        world, f"/api/runs/0/run-series/series/{entry.subtask_id}/{entry.attempt}", root
    )
    assert status == 200, body
    rows = json.loads(body)["records"]
    assert [r["record_id"] for r in rows] == [e.record.record_id for e in sealed]
    refused, *kept = rows
    assert refused["refused"] == "seal", refused
    assert refused["record"] == (
        f"series/{entry.subtask_id}/{entry.attempt}/{entry.session_id}/{entry.record.record_id}.json"
    )
    assert (refused["sealed_sha256"], refused["sealed_length"]) == (
        entry.record.sha256,
        entry.record.length,
    )
    assert refused["error"]
    assert "title" not in refused and "traces" not in refused
    assert all("refused" not in row and row["traces"] for row in kept)
    if how == "a byte changed":
        assert refused["found_sha256"] != entry.record.sha256
    if how == "its length changed":
        assert refused["found_length"] == entry.record.length + 1
    assert os.path.realpath(tmp_path).encode() not in body
    assert str(tmp_path).encode() not in body


def test_sealed_bytes_this_version_cannot_read_are_a_refused_row_of_their_own(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root, run = _copy(world, "run-series", tmp_path)
    entry = _first(run)
    unreadable = b'{"format": "series.v1", "id": "not a record"}'
    entry.path(run).write_bytes(unreadable)
    log = run / "events.jsonl"
    lines = log.read_bytes().splitlines(keepends=True)
    for at, raw in enumerate(lines):
        line = json.loads(raw)
        if line["kind"] == "session_ended" and line["session_id"] == entry.session_id:
            for sealed in line["series"]["records"]:
                if sealed["record_id"] == entry.record.record_id:
                    sealed["sha256"] = hashlib.sha256(unreadable).hexdigest()
                    sealed["length"] = len(unreadable)
            lines[at] = (json.dumps(line) + "\n").encode()
    log.write_bytes(b"".join(lines))
    answer = _read(world, "run-series", entry.subtask_id, entry.attempt, root)
    refused, *kept = answer["records"]
    assert refused["refused"] == "format" and refused["error"], refused
    assert refused["sealed_sha256"] == hashlib.sha256(unreadable).hexdigest()
    assert b"not a record" not in json.dumps(answer).encode()
    assert kept and all("refused" not in row for row in kept)


@pytest.mark.parametrize("toward", ["held-out tier", "corpus", "credential"])
def test_a_record_that_points_where_nothing_may_be_read_is_refused_with_none_of_its_bytes(
    world: dict[str, Path], tmp_path: Path, toward: str
) -> None:
    root, run = _copy(world, "run-series", tmp_path)
    entry = _first(run)
    marker = "".join(("planted", "-marker-", toward.replace(" ", "-")))
    if toward == "held-out tier":
        target = world["held"] / "scenario.json"
        marker = "held-out-marker"
    elif toward == "corpus":
        target = root / "corpora" / "scenario.json"
    else:
        target = root / "notes" / ".env"
    if toward != "held-out tier":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"marker": marker}))
    entry.path(run).unlink()
    os.symlink(target, entry.path(run))
    with serving(_context(world, root)) as live, RECORDER.recording():
        status, _, body = live.request(
            "GET", f"/api/runs/0/run-series/series/{entry.subtask_id}/{entry.attempt}"
        )
    assert status == 200, body
    refused = json.loads(body)["records"][0]
    assert refused["refused"] == "seal", refused
    assert marker.encode() not in body
    assert [p for p in RECORDER.opened if os.path.realpath(p) == os.path.realpath(target)] == []


@pytest.mark.parametrize(
    "forgery",
    [
        "a session id with a separator",
        "a record id that climbs",
        "a ninth attempt",
        "a subtask named refused",
    ],
)
def test_a_forged_end_line_is_refused_before_any_record_is_opened(
    world: dict[str, Path], tmp_path: Path, forgery: str
) -> None:
    root, run = _copy(world, "run-series", tmp_path)
    entry = _first(run)
    log = run / "events.jsonl"
    lines = log.read_bytes().splitlines(keepends=True)
    at = next(i for i, raw in enumerate(lines) if json.loads(raw)["kind"] == "session_ended")
    line = json.loads(lines[at])
    if forgery == "a session id with a separator":
        line["session_id"] = "a/b"
    elif forgery == "a record id that climbs":
        line["series"]["records"][0]["record_id"] = ".."
    elif forgery == "a ninth attempt":
        line["attempt"] = 9
    else:
        line["subtask_id"] = "refused"
    lines[at] = (json.dumps(line) + "\n").encode()
    log.write_bytes(b"".join(lines))
    with serving(_context(world, root)) as live, RECORDER.recording():
        status, _, body = live.request(
            "GET", f"/api/runs/0/run-series/series/{entry.subtask_id}/{entry.attempt}"
        )
    assert status == 422, body
    assert [p for p in RECORDER.opened if f"{os.sep}series{os.sep}" in p] == []


def test_an_integer_input_a_browser_cannot_hold_exactly_is_sent_as_its_numeral(
    world: dict[str, Path],
) -> None:
    subtask, attempt = _sealed(world["runs"] / "run-series-bound")[0]
    rows = _read(world, "run-series-bound", subtask, attempt)["records"]
    assert len(rows) == 256
    by_id = {row["record_id"]: row for row in rows}
    assert by_id["run_000"]["inputs"]["seed"] == {"value": str(BIG_SEED), "unit": "dimensionless"}
    assert by_id["run_001"]["inputs"]["seed"] == {"value": 1, "unit": "dimensionless"}


def test_the_attempt_route_answers_get_and_head_alike_stores_nothing_and_writes_nothing(
    world: dict[str, Path],
) -> None:
    names = sorted(p.name for p in world["runs"].iterdir() if (p / "run.json").is_file())
    targets = [
        f"/api/runs/0/{name}/series/{subtask}/{attempt}"
        for name in names
        if name != "run-series-tampered"
        for subtask, attempt in _sealed(world["runs"] / name)
    ]
    assert len(targets) >= 10
    before = snapshot(world["runs"])
    with serving(_context(world)) as live, RECORDER.recording() as writes:
        for target in targets:
            status, headers, body = live.request("GET", target)
            head_status, head_headers, head_body = live.request("HEAD", target)
            assert status == head_status == 200, (target, body[:300])
            assert head_body == b""
            assert headers["content-length"] == head_headers["content-length"] == str(len(body))
            assert "no-store" in headers["cache-control"]
    assert writes == []
    assert snapshot(world["runs"]) == before


#: Run in a fresh interpreter: the first request that parses a record's units, under the read
#: guard, with a second audit hook recording every write, spawn and thread the request makes.
FIRST_READ = """
import json, os, sys
from physgate.ui import guard, simulation
from physgate.ui.guard import MUTATING_EVENTS, SPAWN_EVENTS, WRITE_FLAGS
from physgate.ui.paths import Allowlist
from physgate.ui.routes import Context
root, name, subtask, attempt = sys.argv[1:5]
seen = []
def spy(event, args):
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        written = isinstance(mode, str) and set("wax+") & set(mode)
        if written or (isinstance(flags, int) and flags & WRITE_FLAGS):
            seen.append(event)
    elif event in MUTATING_EVENTS or event in SPAWN_EVENTS or event == "_thread.start_new_thread":
        seen.append(event)
allowlist = Allowlist.build([root], held_out=[], answer_keys=[], harness=None)
context = Context(allowlist=allowlist, assets=None)
guard.install()
sys.addaudithook(spy)
with guard.scope("read", readable=allowlist.readable):
    params = {"root": "0", "name": name, "subtask": subtask, "attempt": attempt}
    answer = simulation.attempt(context, params)
rows = len(json.loads(answer.body)["records"])
print(json.dumps({"status": answer.status, "rows": rows, "seen": seen}))
"""


def test_the_first_record_read_in_a_fresh_process_writes_nothing_and_starts_nothing(
    world: dict[str, Path],
) -> None:
    assert callable(getattr(simulation, "attempt", None)), "the attempt route's handler exists"
    subtask, attempt = _sealed(world["runs"] / "run-series")[0]
    done = subprocess.run(
        [sys.executable, "-c", FIRST_READ, str(world["runs"]), "run-series", subtask, str(attempt)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    found = json.loads(done.stdout.strip().splitlines()[-1])
    assert found == {"status": 200, "rows": 6, "seen": []}


def _ratio(world: dict[str, Path], name: str) -> tuple[float, float, float]:
    """The cold read of an attempt against reading and hashing its records' bytes, interleaved."""
    handler = getattr(simulation, "attempt", None)
    assert callable(handler), "the attempt route's handler exists"
    run = world["runs"] / name
    subtask, attempt = _sealed(run)[0]
    entries = attempt_records(_events(run), subtask, attempt)
    context = _context(world)
    params = {"root": "0", "name": name, "subtask": subtask, "attempt": str(attempt)}
    reads: list[float] = []
    floors: list[float] = []
    for _ in range(7):
        started = time.perf_counter()
        for entry in entries:
            hashlib.sha256(entry.path(run).read_bytes()).hexdigest()
        floors.append(time.perf_counter() - started)
        started = time.perf_counter()
        answered = handler(context, params)
        reads.append(time.perf_counter() - started)
        assert answered.status == 200
    read, floor = statistics.median(reads), statistics.median(floors)
    return read / floor, read, floor


@pytest.mark.parametrize("name", ["run-series-large", "run-series-bound"])
def test_reading_an_attempt_stays_within_its_budget(world: dict[str, Path], name: str) -> None:
    ratio, read, floor = _ratio(world, name)
    # Reported beside the ratio, which is what is held: an absolute time carries its machine.
    print(
        f"{name}: read {read * 1000:.1f} ms, read-and-hash floor {floor * 1000:.1f} ms, "
        f"{ratio:.1f}x"
    )
    assert ratio <= BUDGET_RATIO, (name, ratio, read, floor)
