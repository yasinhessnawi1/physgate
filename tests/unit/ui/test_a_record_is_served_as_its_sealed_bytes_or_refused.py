"""One simulation record, served as the very bytes its session's end sealed, or refused.

The route finds the record the way the attempt route does: among the records the reader's own
rule says the attempt sealed, by a path built from the log's validated ids, held to the
allowlist. It then reads the file once, through the reader's checked read, which holds it to its
seal's digest and length, has the format's one parser admit those bytes, and answers with them
as they are: never a re-encoding of what was parsed. A file under the run's series directory that
no session's end seals is never opened, whatever its name.

A record that cannot be served as sealed is refused, never answered with a server fault: one that
changed, is gone, is a link inside the run or a FIFO, or is not a record this version reads is
refused with the record's name relative to the run, its seal, the reader's reason and what the
reader found, as the attempt route's row for it says. One the allowlist refuses (a link out of
the roots, toward the held-out tier, a corpus or a credential, or a file with a second name)
stays a refusal of the path, with the same relative name. No refusal carries an absolute path or
a byte of the record, and no read goes past the format's byte bound.

The runs are made by the real loop with the real gate (see ``ui_series_rig``).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from ui_rig import RECORDER, context_over, fake_ui, serving, snapshot
from ui_series_rig import BIG_SEED, bound_run, series_runs

from physgate.orchestrator.events import SessionEnded, read_events
from physgate.series.reader import SealedEntry, attempt_records
from physgate.series.record import MAX_FILE_BYTES
from physgate.series.seal import NAME_PATTERN
from physgate.ui import simulation
from physgate.ui.routes import PARAMETERS, json_response
from physgate.ui.table import ROUTES, RUN

#: Spellings no parameter may match, in every slot of the record route.
HOSTILE = ("..", "%2e%2e", "%252e%252e", "..%2f..%2fheld", "%2fetc", "a%00b", ".hidden", "%", "%ZZ")
#: The runs whose every record is served as sealed: all but the one changed after its seal.
SERVED = (
    "run-series",
    "run-series-refused",
    "run-series-observe",
    "run-series-off",
    "run-series-retried",
    "run-series-large",
    "run-series-bound",
)


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


def _events(run: Path) -> list[Any]:
    return read_events(run / "events.jsonl")


def _sealed(run: Path) -> list[tuple[str, int]]:
    """Every attempt of ``run`` that sealed a record, in log order."""
    keys: dict[tuple[str, int], None] = {}
    for e in _events(run):
        if isinstance(e, SessionEnded) and e.series.records:
            keys.setdefault((e.subtask_id, e.attempt), None)
    return list(keys)


def _entries(run: Path) -> list[SealedEntry]:
    """Every record ``run`` sealed, attempt by attempt, as the reader's own rule finds them."""
    events = _events(run)
    return [
        entry
        for subtask, attempt in _sealed(run)
        for entry in attempt_records(events, subtask, attempt)
    ]


def _target(name: str, entry: SealedEntry) -> str:
    return f"/api/runs/0/{name}/series/{entry.subtask_id}/{entry.attempt}/{entry.record.record_id}"


def _relative(entry: SealedEntry) -> str:
    """The record's path relative to its run, as a refusal names it."""
    return (
        f"series/{entry.subtask_id}/{entry.attempt}/{entry.session_id}/"
        f"{entry.record.record_id}.json"
    )


def _copy(world: dict[str, Path], name: str, tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "runs"
    target = root / name
    shutil.copytree(
        world["runs"] / name, target, symlinks=True, ignore=shutil.ignore_patterns("worktrees")
    )
    return root, target


def _first(run: Path) -> SealedEntry:
    """The first attempt's record with the smallest id: the one the refusal tests change."""
    return _entries(run)[0]


def _reseal(run: Path, entry: SealedEntry, data: bytes) -> None:
    """Write ``data`` as ``entry``'s record and rewrite its session's end line to seal it."""
    entry.path(run).write_bytes(data)
    log = run / "events.jsonl"
    lines = log.read_bytes().splitlines(keepends=True)
    for at, raw in enumerate(lines):
        line = json.loads(raw)
        if line["kind"] == "session_ended" and line["session_id"] == entry.session_id:
            for sealed in line["series"]["records"]:
                if sealed["record_id"] == entry.record.record_id:
                    sealed["sha256"] = hashlib.sha256(data).hexdigest()
                    sealed["length"] = len(data)
            lines[at] = (json.dumps(line) + "\n").encode()
    log.write_bytes(b"".join(lines))


def test_the_record_route_is_one_read_placed_after_the_attempt_route() -> None:
    patterns = [route.pattern for route in ROUTES]
    attempt = f"{RUN}/series/{{subtask:subtask}}/{{attempt:attempt}}"
    record = f"{attempt}/{{record:record}}"
    assert record in patterns, "one record's bytes are read by a route of their own"
    (route,) = [r for r in ROUTES if r.pattern == record]
    assert (route.kind, route.method) == ("read", "GET")
    assert patterns.index(record) == patterns.index(attempt) + 1
    assert [r.kind for r in ROUTES].count("act") == 1


def test_the_record_type_is_the_format_s_own_name_and_refuses_every_hostile_spelling() -> None:
    from urllib.parse import unquote

    record = PARAMETERS.get("record")
    assert record is not None, "the record route's type exists"
    assert record.pattern == NAME_PATTERN, "the record format's own name rule, never a copy"
    for bad in HOSTILE:
        assert record.fullmatch(unquote(bad)) is None, bad
    refused = ("Upper", "a-b", "1abc", "_a", "a.json", "a" * 65, "", "a b")
    assert [name for name in refused if record.fullmatch(name)] == []
    for name in ("step_nominal", "a", "a" * 64, "run_000"):
        assert record.fullmatch(name) is not None, name


def test_every_sealed_record_is_served_as_the_very_bytes_its_seal_names(
    world: dict[str, Path],
) -> None:
    served = 0
    with serving(_context(world)) as live:
        for name in SERVED:
            run = world["runs"] / name
            for entry in _entries(run):
                status, headers, body = live.request("GET", _target(name, entry))
                assert status == 200, (name, entry.record.record_id, body[:300])
                assert headers["content-type"] == "application/json"
                assert hashlib.sha256(body).hexdigest() == entry.record.sha256
                assert len(body) == entry.record.length
                assert body == entry.path(run).read_bytes()
                served += 1
    # Every run's records, the per-session bound's included: a sweep of a few would prove less.
    assert served >= 550, served
    # Sealed bytes are not what re-encoding the parsed record would give, so serving a
    # re-encoding instead could not pass the digest check above.
    entry = _first(world["runs"] / "run-series")
    data = entry.path(world["runs"] / "run-series").read_bytes()
    assert json_response(json.loads(data)).body != data


def test_a_large_integer_is_served_as_the_record_wrote_it(world: dict[str, Path]) -> None:
    run = world["runs"] / "run-series-bound"
    entry = next(e for e in _entries(run) if e.record.record_id == "run_000")
    with serving(_context(world)) as live:
        status, _, body = live.request("GET", _target("run-series-bound", entry))
    assert status == 200, body[:300]
    assert str(BIG_SEED).encode() in body


def test_the_record_is_opened_once_and_nothing_beneath_the_run_but_it_and_the_log(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root, run = _copy(world, "run-series-retried", tmp_path)
    entries = _entries(run)
    entry = entries[0]
    where = entry.path(run).parent
    (where / "unsealed_extra.json").write_text('{"format": "series.v1"}')
    outside = tmp_path / "elsewhere.json"
    outside.write_text("outside every root")
    os.symlink(outside, where / "linked_out.json")
    os.mkfifo(where.parent / "piped.json")
    with serving(_context(world, root)) as live, RECORDER.recording() as writes:
        status, _, body = live.request("GET", _target("run-series-retried", entry))
    assert status == 200, body[:300]
    assert writes == []
    real = os.path.realpath(run)
    opened = [os.path.realpath(p) for p in RECORDER.opened if os.path.realpath(p).startswith(real)]
    record = os.path.realpath(entry.path(run))
    assert opened.count(record) == 1, "the bytes served come from the one open that checked them"
    assert set(opened) == {os.path.realpath(run / "events.jsonl"), record}
    assert [p for p in RECORDER.listed if os.path.realpath(p).startswith(real)] == []
    for planted in (b"unsealed_extra", b"linked_out", b"piped", b"outside every root"):
        assert planted not in body


def test_a_later_session_s_record_is_served_in_place_of_the_one_it_superseded(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series-retried"
    events = _events(run)
    first, retry = [e for e in events if isinstance(e, SessionEnded) and e.attempt == 1][:2]
    assert first.outcome == "infrastructure" and first.series.records
    entries = attempt_records(events, first.subtask_id, 1)
    assert {e.session_id for e in entries} == {retry.session_id}
    with serving(_context(world)) as live, RECORDER.recording():
        for entry in entries:
            status, _, body = live.request("GET", _target("run-series-retried", entry))
            assert status == 200, body[:300]
    sessions = {
        Path(p).parent.name
        for p in RECORDER.opened
        if f"{os.sep}series{os.sep}" in p and p.endswith(".json")
    }
    assert sessions == {retry.session_id}


def test_a_record_the_attempt_did_not_seal_is_404_and_nothing_beneath_the_run_is_opened(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root, run = _copy(world, "run-series", tmp_path)
    entry = _first(run)
    # A well-formed record at the path a sealed one of that id would have, sealed by no line.
    planted = entry.path(run).with_name("planted_one.json")
    planted.write_bytes(entry.path(run).read_bytes().replace(b"step_nominal", b"planted_one"))
    refused_run = world["runs"] / "run-series-refused"
    nothing = next(
        (e.subtask_id, e.attempt)
        for e in _events(refused_run)
        if isinstance(e, SessionEnded) and not e.series.records
    )
    base = f"/api/runs/0/run-series/series/{entry.subtask_id}"
    with serving(_context(world, root)) as live, RECORDER.recording():
        unsealed = live.request("GET", f"{base}/{entry.attempt}/planted_one")
        unknown = live.request("GET", f"{base}/{entry.attempt}/no_such_record")
        too_far = live.request("GET", f"{base}/5/{entry.record.record_id}")
    with serving(_context(world)) as live:
        sealed_nothing = live.request(
            "GET", f"/api/runs/0/run-series-refused/series/{nothing[0]}/{nothing[1]}/loop_nominal"
        )
    for status, _, body in (unsealed, unknown):
        assert status == 404, body
        assert "sealed no record of that id" in json.loads(body)["error"]
    assert too_far[0] == 404 and "no such attempt" in json.loads(too_far[2])["error"]
    assert sealed_nothing[0] == 404, sealed_nothing[2]
    assert [p for p in RECORDER.opened if f"{os.sep}series{os.sep}" in p] == []
    assert b'"values"' not in unsealed[2] and b"Stand-in" not in unsealed[2]


def _change(entry: SealedEntry, run: Path, tmp_path: Path, how: str) -> None:
    path = entry.path(run)
    data = path.read_bytes()
    at = data.index(b'"values": [') + len(b'"values": [')
    other = data[:at] + (b"9" if data[at : at + 1] != b"9" else b"8") + data[at + 1 :]
    if how == "a byte changed":
        path.write_bytes(other)
    elif how == "its length changed":
        path.write_bytes(data + b" ")
    elif how == "replaced by another of the same length":
        path.unlink()
        path.write_bytes(other)
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


#: How each change is answered: the reader's refusal (422), or the allowlist's (403).
CHANGES = {
    "a byte changed": 422,
    "its length changed": 422,
    "replaced by another of the same length": 422,
    "gone": 422,
    "a link inside the run": 422,
    "a link out of the roots": 403,
    "a second name": 403,
    "a fifo in its place": 422,
}


@pytest.mark.parametrize("how", list(CHANGES))
def test_a_record_not_as_sealed_is_refused_with_its_seal_and_as_the_attempt_s_row_says(
    world: dict[str, Path], tmp_path: Path, how: str
) -> None:
    root, run = _copy(world, "run-series", tmp_path)
    entry = _first(run)
    data = entry.path(run).read_bytes()
    _change(entry, run, tmp_path, how)
    attempt = f"/api/runs/0/run-series/series/{entry.subtask_id}/{entry.attempt}"
    with serving(_context(world, root)) as live:
        status, _, body = live.request("GET", _target("run-series", entry))
        listed = live.request("GET", attempt)
    assert status == CHANGES[how], (how, status, body[:300])
    answer = json.loads(body)
    row = json.loads(listed[2])["records"][0]
    assert (row["record_id"], row["refused"]) == (entry.record.record_id, "seal"), row
    assert answer["record"] == _relative(entry) == row["record"]
    assert "path" not in answer
    if status == 403:
        # The allowlist's own refusal, named by the record's place in the run alone.
        assert answer["error"] == row["error"]
    else:
        assert answer["seal"] == "broken"
        assert answer["error"] and answer["reason"] == row["error"]
        assert (answer["sealed_sha256"], answer["sealed_length"]) == (
            entry.record.sha256,
            str(entry.record.length),
        )
        for found in ("found_sha256", "found_length"):
            assert answer.get(found) == (None if found not in row else str(row[found])), found
    if how in ("a byte changed", "replaced by another of the same length"):
        assert answer.get("found_sha256") not in (None, entry.record.sha256), answer
    if how == "its length changed":
        assert answer.get("found_length") == str(entry.record.length + 1), answer
    assert os.path.realpath(tmp_path).encode() not in body
    assert str(tmp_path).encode() not in body
    assert b'"values"' not in body and b"Stand-in" not in body
    assert data[:40] not in body


def test_the_other_records_of_an_attempt_are_served_beside_a_changed_one(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series-tampered"
    sealed = attempt_records(_events(run), *_sealed(run)[0])
    changed = [
        e for e in sealed if hashlib.sha256(e.path(run).read_bytes()).hexdigest() != e.record.sha256
    ]
    assert len(changed) == 1, "the tampered run changes one record of its first attempt"
    (entry,) = changed
    others = [e for e in sealed if e != entry]
    with serving(_context(world)) as live:
        status, _, body = live.request("GET", _target("run-series-tampered", entry))
        kept = [live.request("GET", _target("run-series-tampered", e)) for e in others]
    assert status == 422, body[:300]
    answer = json.loads(body)
    assert answer["seal"] == "broken"
    assert answer["found_sha256"] != entry.record.sha256
    assert len(kept) == 5
    for (got, _, data), other in zip(kept, others, strict=True):
        assert got == 200 and hashlib.sha256(data).hexdigest() == other.record.sha256


def test_sealed_bytes_this_version_cannot_read_are_refused_as_held_with_none_of_them(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root, run = _copy(world, "run-series", tmp_path)
    entry = _first(run)
    unreadable = b'{"format": "series.v1", "id": "not a record"}'
    _reseal(run, entry, unreadable)
    resealed = attempt_records(_events(run), entry.subtask_id, entry.attempt)[0]
    attempt = f"/api/runs/0/run-series/series/{entry.subtask_id}/{entry.attempt}"
    with serving(_context(world, root)) as live:
        status, _, body = live.request("GET", _target("run-series", resealed))
        listed = live.request("GET", attempt)
    assert status == 422, body[:300]
    answer = json.loads(body)
    row = json.loads(listed[2])["records"][0]
    assert answer["seal"] == "held"
    assert answer["reason"] == row["error"] and "does not validate" in answer["reason"]
    assert answer["record"] == _relative(resealed)
    assert answer["sealed_sha256"] == hashlib.sha256(unreadable).hexdigest()
    assert answer["sealed_length"] == str(len(unreadable))
    assert b"not a record" not in body
    assert os.path.realpath(tmp_path).encode() not in body


@pytest.mark.parametrize(
    "toward", ["held-out tier", "a corpus", "a credential in the run", "outside every root"]
)
def test_a_record_planted_as_a_link_where_nothing_may_be_read_is_refused_unopened(
    world: dict[str, Path], tmp_path: Path, toward: str
) -> None:
    root, run = _copy(world, "run-series", tmp_path)
    entry = _first(run)
    marker = "".join(("planted", "-marker-", toward.replace(" ", "-")))
    if toward == "held-out tier":
        target = world["held"] / "scenario.json"
        marker = "held-out-marker"
    elif toward == "a corpus":
        target = root / "corpora" / "scenario.json"
    elif toward == "a credential in the run":
        target = run / "notes" / ".env"
    else:
        target = tmp_path / "outside" / "target.json"
    if toward != "held-out tier":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"marker": marker}))
    entry.path(run).unlink()
    os.symlink(target, entry.path(run))
    with serving(_context(world, root)) as live, RECORDER.recording():
        status, _, body = live.request("GET", _target("run-series", entry))
    assert status == 403, (toward, status, body[:300])
    assert json.loads(body)["record"] == _relative(entry)
    assert marker.encode() not in body
    assert os.path.realpath(tmp_path).encode() not in body
    assert os.path.realpath(world["held"]).encode() not in body
    assert [p for p in RECORDER.opened if os.path.realpath(p) == os.path.realpath(target)] == []


def _counting(returned: list[int]) -> Callable[[int, int], bytes]:
    """``os.read``, recording how many bytes each call gave back."""
    real = os.read

    def read(fd: int, size: int) -> bytes:
        chunk = real(fd, size)
        returned.append(len(chunk))
        return chunk

    return read


def test_a_record_sealed_over_the_byte_bound_is_refused_before_a_byte_of_it_is_read(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, run = _copy(world, "run-series", tmp_path)
    entry = _first(run)
    _reseal(run, entry, b" " * (MAX_FILE_BYTES + 1))
    resealed = attempt_records(_events(run), entry.subtask_id, entry.attempt)[0]
    assert resealed.record.length == MAX_FILE_BYTES + 1
    returned: list[int] = []
    with serving(_context(world, root)) as live:
        monkeypatch.setattr(os, "read", _counting(returned))
        status, _, body = live.request("GET", _target("run-series", resealed))
        monkeypatch.undo()
    assert status == 422, body[:300]
    answer = json.loads(body)
    assert answer["seal"] == "held" and "at most" in answer["reason"]
    assert returned == [], "a record over the bound is refused before any of it is read"


def test_the_largest_record_is_read_within_the_byte_bound(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    run = world["runs"] / "run-series-large"
    entry = next(e for e in _entries(run) if e.record.record_id == "long_run")
    assert entry.record.length > MAX_FILE_BYTES // 2, "a record near the bound proves more"
    returned: list[int] = []
    with serving(_context(world)) as live:
        monkeypatch.setattr(os, "read", _counting(returned))
        status, _, body = live.request("GET", _target("run-series-large", entry))
        monkeypatch.undo()
    assert status == 200, body[:300]
    assert len(body) == entry.record.length
    assert 0 < sum(returned) <= MAX_FILE_BYTES + 1


def test_the_record_route_answers_get_and_head_alike_stores_nothing_and_writes_nothing(
    world: dict[str, Path],
) -> None:
    targets = [
        _target(name, entry)
        for name in ("run-series", "run-series-refused", "run-series-large", "run-series-tampered")
        for entry in _entries(world["runs"] / name)
    ]
    targets.append(targets[0].rsplit("/", 1)[0] + "/no_such_record")
    assert len(targets) >= 50
    before = snapshot(world["runs"])
    statuses: set[int] = set()
    with serving(_context(world)) as live, RECORDER.recording() as writes:
        for target in targets:
            status, headers, body = live.request("GET", target)
            head_status, head_headers, head_body = live.request("HEAD", target)
            assert status == head_status, target
            assert head_body == b""
            assert headers["content-length"] == head_headers["content-length"] == str(len(body))
            assert headers["cache-control"] == head_headers["cache-control"] == "no-store"
            statuses.add(status)
    assert statuses == {200, 404, 422}, statuses
    assert writes == []
    assert snapshot(world["runs"]) == before


#: Run in a fresh interpreter: the first request that parses a record's units, under the read
#: guard, with a second audit hook recording every write, spawn and thread the request makes.
FIRST_READ = """
import hashlib, json, sys
from physgate.ui import guard, simulation
from physgate.ui.guard import MUTATING_EVENTS, SPAWN_EVENTS, WRITE_FLAGS
from physgate.ui.paths import Allowlist
from physgate.ui.routes import Context
root, name, subtask, attempt, record = sys.argv[1:6]
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
    params = {"root": "0", "name": name, "subtask": subtask, "attempt": attempt, "record": record}
    answer = simulation.record(context, params)
digest = hashlib.sha256(answer.body).hexdigest()
print(json.dumps({"status": answer.status, "sha256": digest, "seen": seen}))
"""


def test_the_first_record_served_in_a_fresh_process_writes_nothing_and_starts_nothing(
    world: dict[str, Path],
) -> None:
    assert callable(getattr(simulation, "record", None)), "the record route's handler exists"
    entry = _first(world["runs"] / "run-series")
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            FIRST_READ,
            str(world["runs"]),
            "run-series",
            entry.subtask_id,
            str(entry.attempt),
            entry.record.record_id,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    found = json.loads(done.stdout.strip().splitlines()[-1])
    assert found == {"status": 200, "sha256": entry.record.sha256, "seen": []}
