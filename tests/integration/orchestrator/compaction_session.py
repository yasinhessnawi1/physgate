"""One session of a pinned binary at the scripted endpoint, driven past its compaction trigger.

The scripted endpoint answers every request offering tools with the next scripted step. Here
the binary's own compaction request is told apart (it carries the compaction marker) and
answered with a summary whose usage is the endpoint's own figures for it, so where those
figures show up afterwards (in the stream, in the result's totals) can be read; or with an
error, as a compaction the API refuses. Every request's body is kept, so what a request after
the compaction carried (the verdict tool's schema, a hook's context) can be checked.

A session-start probe hook can be installed: it appends what the binary gave it to a file and
answers with a context line naming the source it was given, so whether the hook ran, with what
source and session id, and whether its context reached the next request can each be read. No
content of a real session is in any of it: the endpoint's steps and the probe's lines are all.

Nothing here makes a model call: the binary is pointed at the local endpoint with the dummy key.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from scripted_endpoint import (
    COMPACTION_MARKER,
    DUMMY_KEY,
    FakeMessagesApi,
    Script,
    _events,
    _last_user,
    text,
)

from physgate.lines import split_lines
from physgate.orchestrator.decompose import binary_version, read_stream
from physgate.orchestrator.invocation import isolated_env
from physgate.reviewers.claude import COMPACT_BOUNDARY

#: The reviewer's model string in the evaluation's runs.
MODEL = "claude-sonnet-5"
#: The figures the endpoint reports for its answer to a compaction request: none of the
#: endpoint's other figures are these, so wherever they appear, they came from that answer.
COMPACT_USAGE = {
    "input_tokens": 70_001,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "output_tokens": 301,
}
#: What the probe hook answers, followed by the source it was given.
PROBE_CONTEXT = "CTX-PROBE-CONTEXT source="
SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
)
PROMPT = "Read a.txt and answer."

_PROBE = f"""\
import json, sys
data = json.load(sys.stdin)
with open(sys.argv[1], "a", encoding="utf-8") as out:
    out.write(json.dumps(data) + "\\n")
print(json.dumps({{"hookSpecificOutput": {{"hookEventName": "SessionStart",
    "additionalContext": {PROBE_CONTEXT!r} + str(data.get("source"))}}}}))
"""
#: What the read probe records of each Read's result: its type, its keys, and its ``file``
#: object's fields, the content by its length only.
_READ_PROBE = """\
import json, sys
data = json.load(sys.stdin)
result = data.get("tool_response")
shape = {"input": data.get("tool_input")}
if isinstance(result, dict):
    shape["type"] = result.get("type")
    shape["keys"] = sorted(result)
    file = result.get("file")
    if isinstance(file, dict):
        shape["file"] = {k: len(v) if k == "content" else v for k, v in file.items()}
with open(sys.argv[1], "a", encoding="utf-8") as out:
    out.write(json.dumps(shape) + "\\n")
"""
#: What the endpoint answers a compaction request with, unless a row names another answer.
SUMMARY = {"text": "<summary>The session so far.</summary>", "usage": COMPACT_USAGE}


def usage_of(context: int) -> dict[str, int]:
    """A message's input figures for a context of ``context`` tokens in all (output 9)."""
    return {
        "input_tokens": 5,
        "cache_read_input_tokens": context - 5 - 2 - 9,
        "cache_creation_input_tokens": 2,
    }


def body_text(body: dict[str, Any]) -> str:
    """Every text a request body carries: its system prompt and every message, joined."""
    return json.dumps(body, sort_keys=True)


class CompactingApi(FakeMessagesApi):
    """The scripted endpoint, with the compaction request answered as ``compact_reply``."""

    def __init__(
        self,
        script: Script,
        compact_reply: dict[str, Any],
        count_tokens: Callable[[dict[str, Any]], int] | None = None,
    ) -> None:
        """Serve ``script``; answer each compaction request with ``compact_reply``.

        ``count_tokens`` answers a token-count request from its body; by default every count
        is 1, as the scripted endpoint's own.
        """
        super().__init__(script)
        self.compact_reply = compact_reply
        self.count_tokens = count_tokens or (lambda _body: 1)
        #: Every request's body, in the order they arrived, and whether it was a compaction.
        self.bodies: list[dict[str, Any]] = []
        self.compaction_requests: list[int] = []
        self._order = threading.Lock()

    def answer(self, path: str, headers: Any, body: dict[str, Any]) -> tuple[bytes, str]:  # noqa: ANN401
        """Record the body; answer a compaction request here, any other as the endpoint does."""
        with self._order:
            index = len(self.bodies)
            self.bodies.append(body)
        if COMPACTION_MARKER not in _last_user(body.get("messages", [])):
            return super().answer(path, headers, body)
        self.compaction_requests.append(index)
        reply = self.compact_reply
        if "error" in reply:
            error = dict(reply["error"])
            status = error.pop("status")
            shaped = {"type": "error", "error": error, "status": status}
            return json.dumps(shaped).encode(), "application/json"
        return _events(reply, body.get("model", "fake"), 1000 + index), "text/event-stream"


@contextmanager
def serving(api: CompactingApi) -> Iterator[str]:
    """Run ``api`` on a free port; yield its base URL. As the scripted endpoint's own server."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
            return

        def do_POST(self) -> None:  # noqa: N802 - the name http.server calls
            raw = self.rfile.read(int(self.headers.get("content-length", 0)))
            status = 200
            if "count_tokens" in self.path:
                counted = api.count_tokens(json.loads(raw or b"{}"))
                body, ctype = json.dumps({"input_tokens": counted}).encode(), "application/json"
            else:
                body, ctype = api.answer(self.path, self.headers, json.loads(raw or b"{}"))
                if ctype == "application/json":
                    shaped = json.loads(body)
                    status = int(shaped.pop("status"))
                    body = json.dumps(shaped).encode()
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@dataclass(frozen=True)
class Ran:
    """One invocation as it ended: its stream, its exit, the endpoint's record, the probe's."""

    version: str
    session_id: str
    stdout: str
    stderr: str
    exit_code: int
    bodies: tuple[dict[str, Any], ...]
    compaction_requests: tuple[int, ...]
    #: Each input the session-start probe was given, in order.
    hook_inputs: tuple[dict[str, Any], ...] = field(default=())

    @property
    def events(self) -> list[dict[str, Any]]:
        """Every event of the stream, in order."""
        found = []
        for line in split_lines(self.stdout):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                found.append(event)
        return found

    @property
    def result(self) -> dict[str, Any] | None:
        """The stream's result event."""
        return read_stream(self.stdout)[0]

    @property
    def boundaries(self) -> list[dict[str, Any]]:
        """Each compaction boundary event of the stream."""
        return [
            e
            for e in self.events
            if e.get("type") == "system" and e.get("subtype") == COMPACT_BOUNDARY
        ]

    def after_compaction(self) -> list[dict[str, Any]]:
        """The bodies of the requests made after the first compaction request."""
        if not self.compaction_requests:
            return []
        return list(self.bodies[self.compaction_requests[0] + 1 :])


class Session:
    """A session's directories, kept across a resume, and how to invoke the binary on them."""

    def __init__(
        self, binary: str, work: Path, *, probe: bool = True, read_probe: bool = False
    ) -> None:
        """Make ``work``'s ``home``, ``config`` and ``cwd``, and the probe hooks' settings.

        ``read_probe`` installs a hook after each Read that records the shape of its result.
        """
        self.binary = binary
        self.work = work
        self.version = binary_version(binary)
        self.session_id = str(uuid.uuid4())
        for name in ("home", "config", "cwd"):
            (work / name).mkdir(parents=True, exist_ok=True)
        (work / "cwd" / "a.txt").write_text("hello\n")
        self.hook_log = work / "hook-inputs.jsonl"
        settings: dict[str, Any] = {}
        if probe:
            script = work / "probe.py"
            script.write_text(_PROBE)
            command = f"{sys.executable} -I {script} {self.hook_log}"
            settings["hooks"] = {
                "SessionStart": [{"hooks": [{"type": "command", "command": command}]}]
            }
        self.read_log = work / "read-results.jsonl"
        if read_probe:
            script = work / "read_probe.py"
            script.write_text(_READ_PROBE)
            command = f"{sys.executable} -I {script} {self.read_log}"
            settings.setdefault("hooks", {})["PostToolUse"] = [
                {"matcher": "Read", "hooks": [{"type": "command", "command": command}]}
            ]
        self.settings = work / "settings.json"
        self.settings.write_text(json.dumps(settings))

    def hook_inputs(self) -> tuple[dict[str, Any], ...]:
        """Every input the probe was given so far."""
        if not self.hook_log.exists():
            return ()
        return tuple(json.loads(line) for line in self.hook_log.read_text().splitlines() if line)

    def read_results(self) -> list[dict[str, Any]]:
        """The shape of each Read's result so far, as the read probe recorded it."""
        if not self.read_log.exists():
            return []
        return [json.loads(line) for line in self.read_log.read_text().splitlines() if line]

    def run(  # noqa: PLR0913 - one invocation, with everything it is given
        self,
        steps: list[dict[str, Any]],
        *,
        compact_reply: dict[str, Any] | None = None,
        resume: bool = False,
        prompt: str = PROMPT,
        env: dict[str, str] | None = None,
        max_turns: int = 20,
        count_tokens: Callable[[dict[str, Any]], int] | None = None,
    ) -> Ran:
        """Invoke the binary once on ``steps``, served one per request whatever the conversation.

        ``resume`` resumes this session (``--resume``) instead of starting it; ``count_tokens``
        answers the binary's token-count requests (by default, 1 each).
        """
        served = iter(steps)
        api = CompactingApi(Script(main=[]), compact_reply or SUMMARY, count_tokens)
        api.on_request = lambda _t, _c, _d: next(served, text("done"))
        with serving(api) as url:
            session_env = isolated_env(
                home=self.work / "home",
                config_dir=self.work / "config",
                binary=self.binary,
                claude_version=self.version,
                max_retries=0,
                max_output_tokens=1000,
                base_url=url,
                api_key=DUMMY_KEY,
            )
            session_env.update(env or {})
            argv = [
                self.binary,
                "-p",
                prompt,
                "--setting-sources",
                "",
                "--settings",
                str(self.settings),
                "--tools",
                "Read",
                "--json-schema",
                SCHEMA,
                "--output-format",
                "stream-json",
                "--verbose",
                "--include-partial-messages",
                "--model",
                MODEL,
                "--effort",
                "low",
                *(("--resume", self.session_id) if resume else ("--session-id", self.session_id)),
                "--max-turns",
                str(max_turns),
                "--permission-mode",
                "bypassPermissions",
            ]
            done = subprocess.run(
                argv,
                cwd=self.work / "cwd",
                env=session_env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        return Ran(
            version=self.version,
            session_id=self.session_id,
            stdout=done.stdout,
            stderr=done.stderr,
            exit_code=done.returncode,
            bodies=tuple(api.bodies),
            compaction_requests=tuple(api.compaction_requests),
            hook_inputs=self.hook_inputs(),
        )
