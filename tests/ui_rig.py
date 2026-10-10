"""Shared pieces for the operator UI's server tests.

A fixture build, run directories, a live server on an ephemeral loopback port, and two
detectors of writes that do not depend on the server's own guard.

The detectors are deliberately independent of the code under test. The guard in the server
is one audit hook; the recorder here is another, added by the tests, and it records every
write-capable open and filesystem change from any thread while it is on, so a test still sees
a write if the guard itself is removed or weakened. The snapshot is the second detector: what
every file under a set of directories looks like, bytes and metadata, before and after.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import physgate
from physgate.orchestrator.run_config import (
    ModelStrings,
    RunBounds,
    RunConfig,
    endpoint_of,
    harness_state,
    write_run_config,
)
from physgate.ui import assets
from physgate.ui.guard import MUTATING_EVENTS, SPAWN_EVENTS, WRITE_FLAGS
from physgate.ui.paths import Allowlist
from physgate.ui.routes import Context, Route
from physgate.ui.server import make_server
from physgate.ui.table import ROUTES

#: Every method the sweep sends: the ones a server might serve, and ones nobody does.
METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "PROPFIND", "FROB")


def run_config(run_id: str) -> RunConfig:
    """A complete, valid run configuration; no repository or model is touched."""
    return RunConfig(
        run_id=run_id,
        seed=1,
        brief_sha256="a" * 64,
        gate_mode="observe",
        models=ModelStrings(
            decomposition="claude-sonnet-5",
            roles={"electrical": "claude-sonnet-5"},
            reviewers={"electrical": "claude-opus-5-5"},
        ),
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=120.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        token_ceiling=100_000,
        claude_version="2.1.272",
        target_head="b" * 40,
        endpoint=endpoint_of("http://127.0.0.1:9"),
        auth="api_key",
        reportable=False,
        harness=harness_state(None),
        effort="high",
        max_output_tokens=64000,
        thinking_display="summarized",
        role_python=None,
    )


def write_run(run_dir: Path, run_id: str) -> RunConfig:
    """A run directory holding only its recorded configuration."""
    run_dir.mkdir(parents=True)
    config = run_config(run_id)
    write_run_config(run_dir / "run.json", config)
    return config


def fake_ui(root: Path) -> Path:
    """A ``ui`` directory with sources and a stamped build, as the build script leaves it."""
    ui = root / "ui"
    (ui / "src").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>source</title>\n")
    (ui / "src" / "main.ts").write_text("export const x = 1;\n")
    dist = ui / assets.DIST
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><title>Operator</title><script src="/assets/app.js"></script>\n'
    )
    (dist / "assets" / "app.js").write_text("console.log(1);\n")
    (dist / "assets" / "app.css").write_text("body{}\n")
    assets.write_stamp(ui)
    return ui


@dataclass
class Recorder:
    """What this process does while on, from any thread.

    ``seen``: every write-capable open, filesystem change and spawn. ``opened``: the path of
    every open at all. ``listed``: the path of every directory listing.
    """

    on: bool = False
    seen: list[tuple[str, str]] | None = None
    opened: list[str] = field(default_factory=list)
    listed: list[str] = field(default_factory=list)

    def hook(self, event: str, args: tuple[object, ...]) -> None:
        if not self.on or self.seen is None:
            return
        if event == "open" and args and isinstance(args[0], str | bytes):
            self.opened.append(os.path.abspath(os.fsdecode(args[0])))
        if event in ("os.listdir", "os.scandir") and args and isinstance(args[0], str | bytes):
            self.listed.append(os.path.abspath(os.fsdecode(args[0])))
        if event == "open":
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else 0
            written = isinstance(mode, str) and bool(set("wax+") & set(mode))
            if written or (isinstance(flags, int) and flags & WRITE_FLAGS):
                self.seen.append((event, str(args[0])))
        elif event in MUTATING_EVENTS or event in SPAWN_EVENTS:
            self.seen.append((event, repr(args)[:200]))

    @contextmanager
    def recording(self) -> Iterator[list[tuple[str, str]]]:
        self.seen = []
        self.opened = []
        self.listed = []
        self.on = True
        try:
            yield self.seen
        finally:
            self.on = False


RECORDER = Recorder()
sys.addaudithook(RECORDER.hook)


def snapshot(*directories: Path) -> dict[str, tuple[int, int, int, str]]:
    """Every file beneath ``directories``: (size, mode, mtime_ns, digest of its bytes)."""
    found: dict[str, tuple[int, int, int, str]] = {}
    for directory in directories:
        for dirpath, dirnames, filenames in os.walk(directory):
            for name in dirnames + filenames:
                path = os.path.join(dirpath, name)
                st = os.lstat(path)
                digest = ""
                if os.path.isfile(path) and not os.path.islink(path):
                    with open(path, "rb") as handle:
                        digest = hashlib.sha256(handle.read()).hexdigest()
                found[path] = (st.st_size, st.st_mode, st.st_mtime_ns, digest)
    assert found, "a snapshot of nothing proves nothing"
    return found


@dataclass(frozen=True)
class Live:
    """A server running in this process on an ephemeral loopback port."""

    port: int

    def request(
        self,
        method: str,
        target: str,
        *,
        host: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", host if host is not None else f"127.0.0.1:{self.port}")
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        connection.endheaders()
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, body

    def json(self, target: str) -> object:
        status, _, body = self.request("GET", target)
        assert status == 200, body
        return json.loads(body)


@contextmanager
def serving(context: Context, routes: tuple[Route, ...] = ROUTES) -> Iterator[Live]:
    """Serve ``routes`` over ``context`` until the block ends."""
    server = make_server(context, bind="127.0.0.1", port=0, routes=routes, quiet=True)
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield Live(port=int(server.server_address[1]))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def context_over(*roots: Path, ui_root: Path, held_out: tuple[str, ...] = ()) -> Context:
    """A context over ``roots`` with the fixture build loaded."""
    allowlist = Allowlist.build(
        [str(r) for r in roots], held_out=held_out, answer_keys=(), harness=None
    )
    return Context(allowlist=allowlist, assets=assets.load(ui_root))


#: Where the observability tests keep their real-run rig: the real loop, real git and a real
#: store, with stand-in sessions and no model. It is put on the path here, once, rather than
#: copied, so the UI's tests read the same runs the command line's tests are built on.
EVALUATION_TESTS = Path(__file__).resolve().parent / "unit" / "evaluation"


@cache
def _rig() -> None:
    if str(EVALUATION_TESTS) not in sys.path:
        sys.path.insert(0, str(EVALUATION_TESTS))


def real_runs(root: Path) -> Path:
    """Three runs made by the real loop under ``root/runs``: gated on, observed, and clean.

    In the first two the gate fails the first attempt; under ``observe`` the reviewer still
    reviews and passes it, so a gate event there says a reviewer had passed the work.
    """
    _rig()
    from observe_rig import Gate, fake_run, target_repo

    runs = root / "runs"
    repo = target_repo(root)
    fake_run(runs, "run-on", repo, gate=Gate(fail_on={1}))
    fake_run(runs, "run-observe", repo, gate=Gate(fail_on={1}), overrides={"gate_mode": "observe"})
    fake_run(runs, "run-clean", repo)
    return runs


def sealed_session(run_dir: Path) -> str:
    """The id of a session whose trajectory the run sealed."""
    for raw in (run_dir / "events.jsonl").read_text().splitlines():
        record = json.loads(raw)
        if record.get("kind") == "session_ended" and record.get("trajectory_seal"):
            return str(record["session_id"])
    msg = "the run sealed no trajectory"
    raise AssertionError(msg)


#: What a request may open besides its roots, written here independently of the server's own
#: rule: the interpreter's files and the package's (its recorded price sheets).
OWN_FILES = tuple(
    os.path.realpath(p)
    for p in (sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(physgate.__file__))
)

#: Names nothing may open, wherever they sit.
SECRET_NAMES = {".credentials.json", "key", "key-helper.sh", ".env"}


def opened_outside(
    opened: list[str], roots: tuple[Path, ...], refused: tuple[Path, ...]
) -> list[str]:
    """The opened or listed paths a request had no business touching, by where each really lands.

    The refusals are judged first and hold everywhere, the interpreter's own files included: a
    path in a refused tier, in a corpus, or named like a secret is flagged wherever it lies.
    Only then are the interpreter's and the package's own files let through, and anything else
    must lie beneath a root. Written independently of the server's own rule.
    """

    def under(path: str, base: str) -> bool:
        return path == base or path.startswith(base.rstrip(os.sep) + os.sep)

    bad = []
    for path in opened:
        real = os.path.realpath(path)
        in_refused = any(under(real, os.path.realpath(r)) for r in refused)
        named = os.path.basename(real).casefold() in SECRET_NAMES or "corpora" in Path(real).parts
        if in_refused or named:
            bad.append(f"{path} -> {real}")
            continue
        if any(under(real, base) for base in OWN_FILES):
            continue
        if not any(under(real, os.path.realpath(r)) for r in roots):
            bad.append(f"{path} -> {real}")
    return bad
