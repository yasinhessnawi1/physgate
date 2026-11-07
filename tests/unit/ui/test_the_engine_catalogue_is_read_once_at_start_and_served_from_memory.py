"""The engine catalogue is read once, at start, held to fixed checks, and served from memory.

The command reads the checkout's ``desktop/onboarding/engines.json`` after the allowlist is built
and before the server listens, and keeps its parse, digest and length. The route serves that
copy and opens nothing. A catalogue the checks refuse never stops the server: the route answers
422 with the reason, and every other route is as it was.

What the read does is watched by an audit hook of this module's own, independent of the
server's guard (which is not even installed when the read happens, and polices requests only).
It records every open as the call named it, a relative name and its flags included, because the
read walks descriptors: the checkout, each folder relative to the last, then the file.
"""

from __future__ import annotations

import ast
import hashlib
import http.client
import json
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from ui_rig import RECORDER, context_over, fake_ui, serving, snapshot, write_run

import physgate.ui.server as ui_server
from physgate.cli import main
from physgate.ui import cli as ui_cli
from physgate.ui import engines
from physgate.ui.engines import ABSENT, CATALOGUE_FILE, MAX_BYTES, EngineCatalogue
from physgate.ui.exceptions import UIError
from physgate.ui.guard import SPAWN_EVENTS
from physgate.ui.paths import Allowlist
from physgate.ui.routes import Context, engine_catalogue

REPO = Path(__file__).resolve().parents[3]
REAL = REPO / CATALOGUE_FILE

#: Written into every fixture: it must never appear in a refusal's answer.
MARKER = "CATALOGUE-FIXTURE-MARKER"


@dataclass
class Opens:
    """Every open, thread start and spawn in this process while on, from any thread."""

    on: bool = False
    opened: list[tuple[str, int]] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    marks: list[str] = field(default_factory=list)

    def hook(self, event: str, args: tuple[object, ...]) -> None:
        if not self.on:
            return
        if event == "open" and args and isinstance(args[0], str | bytes):
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else -1
            self.opened.append((os.fsdecode(args[0]), flags))
            self.marks.append(f"open {os.fsdecode(args[0])}")
        elif event == "_thread.start_new_thread" or event in SPAWN_EVENTS:
            self.started.append(event)

    @contextmanager
    def watching(self) -> Iterator[Opens]:
        self.opened, self.started, self.marks = [], [], []
        self.on = True
        try:
            yield self
        finally:
            self.on = False


OPENS = Opens()
sys.addaudithook(OPENS.hook)


# -- fixtures ---------------------------------------------------------------------------------


def _valid_bytes() -> bytes:
    """A catalogue with an entry of each kind the real file has, plus fields nobody draws."""
    return json.dumps(
        {
            "_about": MARKER,
            "engines": [
                {"id": "claude-code", "name": "Claude Code", "status": "available"},
                {"id": "later", "name": "Later", "status": "unsupported", "new_field": [1, 2]},
            ],
            "generated_by": "a later version",
        },
        indent=1,
    ).encode()


def _checkout(tmp: Path, body: bytes | None = None, name: str = "checkout") -> Path:
    checkout = tmp / name
    (checkout / "desktop" / "onboarding").mkdir(parents=True)
    if body is not None:
        (checkout / CATALOGUE_FILE).write_bytes(body)
    return checkout


def _allow(
    tmp: Path, *, held_out: tuple[str, ...] = (), answer_keys: tuple[str, ...] = ()
) -> Allowlist:
    runs = tmp / "runs"
    runs.mkdir(exist_ok=True)
    return Allowlist.build([str(runs)], held_out=held_out, answer_keys=answer_keys, harness=None)


def _load(tmp: Path, checkout: Path, **refused: tuple[str, ...]) -> EngineCatalogue:
    return engines.load(checkout, _allow(tmp, **refused))


# Each refused case: it builds a checkout under ``tmp`` and returns it with the allowlist's
# refused paths, and the words its reason must hold.
Case = Callable[[Path], tuple[Path, dict[str, tuple[str, ...]]]]


def _link_inside(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    checkout = _checkout(tmp)
    real = checkout / "desktop" / "onboarding" / "engines.real.json"
    real.write_bytes(_valid_bytes())
    (checkout / CATALOGUE_FILE).symlink_to(real)
    return checkout, {}


def _link_outside(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    checkout = _checkout(tmp)
    away = tmp / "away.json"
    away.write_bytes(_valid_bytes())
    (checkout / CATALOGUE_FILE).symlink_to(away)
    return checkout, {}


def _folder_is_a_link(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    elsewhere = _checkout(tmp, _valid_bytes(), name="elsewhere")
    checkout = tmp / "checkout"
    checkout.mkdir()
    (checkout / "desktop").symlink_to(elsewhere / "desktop")
    return checkout, {}


def _second_name(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    checkout = _checkout(tmp, _valid_bytes())
    os.link(checkout / CATALOGUE_FILE, tmp / "another-name.json")
    return checkout, {}


def _fifo(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    checkout = _checkout(tmp)
    os.mkfifo(checkout / CATALOGUE_FILE)
    return checkout, {}


def _directory(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    checkout = _checkout(tmp)
    (checkout / CATALOGUE_FILE).mkdir()
    ((checkout / CATALOGUE_FILE) / MARKER).write_text(MARKER)
    return checkout, {}


def _too_large(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    padding = " " * (MAX_BYTES + 1 - len(_valid_bytes()))
    return _checkout(tmp, _valid_bytes() + padding.encode()), {}


def _in_held_out(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    checkout = _checkout(tmp, _valid_bytes())
    return checkout, {"held_out": (str(checkout / "desktop"),)}


def _in_answer_key(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    checkout = _checkout(tmp, _valid_bytes())
    return checkout, {"answer_keys": (str(checkout / "desktop" / "onboarding"),)}


def _in_corpora(tmp: Path) -> tuple[Path, dict[str, tuple[str, ...]]]:
    (tmp / "corpora").mkdir()
    return _checkout(tmp / "corpora", _valid_bytes()), {}


def _bytes(body: bytes) -> Case:
    return lambda tmp: (_checkout(tmp, body), {})


REFUSED: dict[str, tuple[Case, str]] = {
    "a link inside the checkout": (_link_inside, "it is a link"),
    "a link out of the checkout": (_link_outside, "it is a link"),
    "a folder on the way that is a link": (_folder_is_a_link, "a folder on the way"),
    "a second name on disk": (_second_name, "a second name"),
    "a pipe": (_fifo, "not a regular file"),
    "a directory": (_directory, "not a regular file"),
    "a file over 64 KiB": (_too_large, "larger than 64 KiB"),
    "inside a held-out root": (_in_held_out, "where nothing may be read"),
    "inside an answer key": (_in_answer_key, "where nothing may be read"),
    "inside a corpus": (_in_corpora, "where nothing may be read"),
    "not UTF-8": (_bytes(b'{"engines": [], "x": "\xff' + MARKER.encode() + b'"}'), "not UTF-8"),
    "not JSON": (_bytes(b'{"engines": [' + MARKER.encode() + b"]}"), "not JSON"),
    "NaN": (_bytes(b'{"engines": [{"memory_gb": NaN}], "m": "' + MARKER.encode() + b'"}'), "NaN"),
    "an infinity": (_bytes(b'{"engines": [{"memory_gb": -Infinity}]}'), "an infinity"),
    "a repeated key": (
        _bytes(b'{"engines": [], "engines": [], "m": "' + MARKER.encode() + b'"}'),
        "repeats the key 'engines'",
    ),
    "a repeated key inside an entry": (
        _bytes(b'{"engines": [{"id": "a", "id": "b"}]}'),
        "repeats the key 'id'",
    ),
    "a top level that is not an object": (
        _bytes(b'["' + MARKER.encode() + b'"]'),
        "top level is not an object",
    ),
    "no engines list": (_bytes(b'{"m": "' + MARKER.encode() + b'"}'), "lists no engines"),
    "an engines field that is not a list": (
        _bytes(b'{"engines": {"id": "a"}}'),
        "lists no engines",
    ),
    "nested too deeply": (_bytes(b"[" * 30_000 + b"]" * 30_000), "nested too deeply"),
}


# -- the read at start -------------------------------------------------------------------------


@pytest.mark.parametrize("body", [_valid_bytes(), REAL.read_bytes()], ids=["fixture", "real"])
def test_a_catalogue_that_passes_every_check_is_read_whole_with_its_digest_and_length(
    tmp_path: Path, body: bytes
) -> None:
    held = _load(tmp_path, _checkout(tmp_path, body))
    assert held.state == "read", held.reason
    assert held.value == json.loads(body)
    assert held.sha256 == hashlib.sha256(body).hexdigest()
    assert held.length == len(body)
    assert held.reason is None


def test_unknown_keys_and_unknown_statuses_are_kept_as_written(tmp_path: Path) -> None:
    held = _load(tmp_path, _checkout(tmp_path, _valid_bytes()))
    assert isinstance(held.value, dict)
    assert held.value["generated_by"] == "a later version"
    assert held.value["engines"][1] == {
        "id": "later",
        "name": "Later",
        "status": "unsupported",
        "new_field": [1, 2],
    }


def test_a_catalogue_of_exactly_64_kib_is_read(tmp_path: Path) -> None:
    body = _valid_bytes() + b" " * (MAX_BYTES - len(_valid_bytes()))
    assert len(body) == MAX_BYTES
    held = _load(tmp_path, _checkout(tmp_path, body))
    assert held.state == "read", held.reason
    assert held.length == MAX_BYTES


def test_this_checkout_s_own_catalogue_is_read_and_held_to_its_bytes(tmp_path: Path) -> None:
    held = engines.load(REPO, _allow(tmp_path))
    data = REAL.read_bytes()
    assert held.state == "read", held.reason
    assert held.sha256 == hashlib.sha256(data).hexdigest()
    assert held.value == json.loads(data)


@pytest.mark.parametrize("case", list(REFUSED), ids=list(REFUSED))
def test_a_catalogue_that_fails_a_check_is_refused_with_its_reason(
    tmp_path: Path, case: str
) -> None:
    build, words = REFUSED[case]
    checkout, refused = build(tmp_path)
    held = _load(tmp_path, checkout, **refused)
    assert held.state == "refused", (case, held)
    assert held.reason is not None
    assert words in held.reason, held.reason
    assert (held.value, held.sha256, held.length) == (None, None, None)
    assert MARKER not in held.reason


@pytest.mark.parametrize("where", ["no checkout", "no file", "no folder"])
def test_with_no_checkout_or_no_file_there_the_catalogue_is_absent(
    tmp_path: Path, where: str
) -> None:
    if where == "no checkout":
        held = engines.load(None, _allow(tmp_path))
    elif where == "no file":
        held = _load(tmp_path, _checkout(tmp_path))
    else:
        (tmp_path / "checkout").mkdir()
        held = _load(tmp_path, tmp_path / "checkout")
    assert held == ABSENT


def test_the_read_walks_descriptors_and_opens_the_file_once_never_through_a_link(
    tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path, _valid_bytes())
    allowlist = _allow(tmp_path)
    with OPENS.watching() as seen:
        held = engines.load(checkout, allowlist)
    assert held.state == "read", held.reason
    names = [name for name, _ in seen.opened]
    assert names == [str(checkout), "desktop", "onboarding", "engines.json"], names
    for name, flags in seen.opened[1:]:
        assert flags & os.O_NOFOLLOW, f"{name} was opened through any link"
    file_flags = seen.opened[-1][1]
    assert file_flags & os.O_NONBLOCK, "a pipe planted at the path would hang the start"
    assert file_flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC) == 0


def test_a_link_planted_at_the_path_is_refused_before_its_target_is_ever_opened(
    tmp_path: Path,
) -> None:
    checkout, _ = _link_outside(tmp_path)
    with OPENS.watching() as seen:
        held = _load(tmp_path, checkout)
    assert held.state == "refused"
    away = str((tmp_path / "away.json").resolve())
    assert [n for n, _ in seen.opened if os.path.isabs(n) and str(Path(n).resolve()) == away] == []


def test_the_read_writes_nothing_and_starts_no_thread_or_process(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path, _valid_bytes())
    allowlist = _allow(tmp_path)
    before = snapshot(checkout)
    with RECORDER.recording() as writes, OPENS.watching() as seen:
        held = engines.load(checkout, allowlist)
    assert held.state == "read"
    assert writes == []
    assert seen.started == []
    assert snapshot(checkout) == before


def test_a_record_whose_fields_do_not_fit_its_state_cannot_be_made() -> None:
    for wrong in (
        {"state": "read"},
        {"state": "read", "sha256": "a" * 64, "length": 1, "value": {}, "reason": "x"},
        {"state": "absent", "reason": "x"},
        {"state": "refused"},
        {"state": "refused", "reason": "x", "sha256": "a" * 64},
        {"state": "other"},
    ):
        with pytest.raises(UIError, match="do not fit its state"):
            EngineCatalogue(**wrong)  # type: ignore[arg-type]


# -- the command: once, before it listens ------------------------------------------------------


class _StopError(Exception):
    """Raised in place of making the server: the test has seen what it needs."""


def test_the_command_reads_this_checkout_s_catalogue_before_it_makes_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    write_run(runs / "run-1", "run-1")
    ui = fake_ui(tmp_path / "ui-checkout")
    monkeypatch.setattr(ui_cli, "_ui_root", lambda: ui)
    given: list[Context] = []

    def made(context: Context, **_: object) -> None:
        OPENS.marks.append("make_server")
        given.append(context)
        raise _StopError

    monkeypatch.setattr(ui_server, "make_server", made)
    with OPENS.watching() as seen, pytest.raises(_StopError):
        main(["ui", "--root", str(runs), "--port", "0"])
    assert "make_server" in seen.marks, "the command never reached the server"
    assert seen.marks.count("open engines.json") == 1, seen.marks
    assert seen.marks.index("open engines.json") < seen.marks.index("make_server")
    (context,) = given
    data = REAL.read_bytes()
    assert context.engines.state == "read", context.engines.reason
    assert context.engines.sha256 == hashlib.sha256(data).hexdigest()


# -- the route ---------------------------------------------------------------------------------


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    runs = tmp_path / "runs"
    runs.mkdir()
    write_run(runs / "run-1", "run-1")
    return {"runs": runs, "ui": fake_ui(tmp_path / "ui-checkout")}


def _over(world: dict[str, Path], held: EngineCatalogue) -> Context:
    return replace(context_over(world["runs"], ui_root=world["ui"]), engines=held)


def _get(port: int, target: str) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("GET", target)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, body


@pytest.mark.parametrize("body", [_valid_bytes(), REAL.read_bytes()], ids=["fixture", "real"])
def test_the_route_serves_exactly_what_was_read_and_names_the_file_inside_the_checkout(
    world: dict[str, Path], tmp_path: Path, body: bytes
) -> None:
    checkout = _checkout(tmp_path, body)
    held = _load(tmp_path, checkout)
    with serving(_over(world, held)) as live:
        status, raw = _get(live.port, "/api/engines")
    assert status == 200, raw[:300]
    answer = json.loads(raw)
    assert answer == {
        "file": CATALOGUE_FILE,
        "sha256": hashlib.sha256(body).hexdigest(),
        "length": len(body),
        "catalogue": json.loads(body),
    }
    for absolute in (str(checkout), str(checkout.resolve()), str(tmp_path), str(REPO)):
        assert absolute.encode() not in raw, "an E1 answer carries an absolute path"


def test_the_route_opens_nothing_and_answers_the_same_bytes_every_time(
    world: dict[str, Path], tmp_path: Path
) -> None:
    held = _load(tmp_path, _checkout(tmp_path, _valid_bytes()))
    context = _over(world, held)
    with serving(context) as live:
        # One answer first, so anything the server imports on its first request is loaded
        # before the watch begins: what is watched is the route, not the interpreter.
        assert _get(live.port, "/api/runs")[0] == 200
        with OPENS.watching() as seen, RECORDER.recording() as writes:
            answers = {_get(live.port, "/api/engines") for _ in range(5)}
    assert len(answers) == 1
    ((status, _),) = answers
    assert status == 200
    assert seen.opened == [], seen.opened
    assert writes == []


def test_the_handler_itself_opens_nothing_and_starts_no_thread(
    world: dict[str, Path], tmp_path: Path
) -> None:
    held = _load(tmp_path, _checkout(tmp_path, _valid_bytes()))
    context = _over(world, held)
    with OPENS.watching() as seen:
        response = engine_catalogue(context, {})
    assert response.status == 200
    assert (seen.opened, seen.started) == ([], [])


@pytest.mark.parametrize("case", list(REFUSED), ids=list(REFUSED))
def test_a_refused_catalogue_never_stops_the_server_and_is_a_422_with_no_file_bytes(
    world: dict[str, Path], tmp_path: Path, case: str
) -> None:
    build, words = REFUSED[case]
    checkout, refused = build(tmp_path)
    held = _load(tmp_path, checkout, **refused)
    with serving(_over(world, held)) as live:
        status, raw = _get(live.port, "/api/engines")
        runs_status, _ = _get(live.port, "/api/runs")
        page_status, _ = _get(live.port, "/")
    assert status == 422, raw[:300]
    error = json.loads(raw)["error"]
    assert error.startswith("the engine catalogue could not be read: "), error
    assert words in error
    assert MARKER.encode() not in raw
    assert str(tmp_path).encode() not in raw
    assert (runs_status, page_status) == (200, 200)


def test_with_no_catalogue_the_route_is_a_404_with_its_sentence_and_nothing_else_changes(
    world: dict[str, Path],
) -> None:
    plain = context_over(world["runs"], ui_root=world["ui"])
    assert plain.engines is ABSENT, "a context built without a catalogue has none"
    with serving(plain) as live:
        status, raw = _get(live.port, "/api/engines")
        runs_status, runs = _get(live.port, "/api/runs")
    assert status == 404
    assert json.loads(raw) == {"error": "this checkout lists no engines"}
    assert runs_status == 200
    assert [r["run_id"] for r in json.loads(runs)["runs"]] == ["run-1"]


# -- the module --------------------------------------------------------------------------------


def test_the_catalogue_module_imports_the_standard_library_and_the_ui_package_only() -> None:
    source = Path(engines.__file__).read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    assert imported, "a scan that found no import proves nothing"
    outside = {
        m
        for m in imported
        if m.split(".")[0] not in sys.stdlib_module_names and not m.startswith("physgate.ui.")
    }
    assert outside == set()
    assert not any(m.startswith("physgate.evaluation") for m in imported)
