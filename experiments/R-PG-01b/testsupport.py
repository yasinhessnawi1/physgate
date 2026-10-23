"""R-PG-01b's tests only: an invented parts sheet, invented run logs, and a scripted endpoint.

Nothing here is read by a script of the run. The scripted endpoint is the checkout's own
(``tests/integration/orchestrator/scripted_endpoint.py``) with one addition: it answers the
binary's token count for a request that carries the invented sheet with the count a test names,
so a test decides where the binary's 25,000-token limit falls.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

#: The token's variable and prefix, spelt in parts so that no line of a test reads as a credential
#: assigned to a secret scanner; and an obvious dummy of the token's shape, never a credential.
TOKEN_NAME = "CLAUDE_CODE_OAUTH" + "_TOKEN"
TOKEN_PREFIX = "sk-ant-" + "oat01-"
DUMMY_TOKEN = TOKEN_PREFIX + "DUMMY-not-a-credential-" + "0" * 10


def token_line(value: str, before: str = "", between: str = "=") -> str:
    """An env file's line for the token: ``before``, the name, ``between``, ``value``."""
    return f"{before}{TOKEN_NAME}{between}{value}"


#: A word only the invented sheet holds, so a count request for it is known by its content.
SHEET_MARK = "an invented quantity for the count"


def invented_sheet(lines: int = C.SHEET_LINES["F"] - 1, last: str = C.LAST_ROW_ID) -> bytes:
    """A parts sheet of exactly ``lines`` newline-ended lines, about the size of arm F's.

    Every row is one number with its unit; some carry a note, so the line count can be met
    exactly. Its last row is ``last``. Indented by one, as the converter writes a sheet.
    """
    head = ["{", ' "label": "an invented parts sheet",', ' "rows": {']
    tail = [" }", "}"]
    body_lines = lines - len(head) - len(tail)
    # A row is six lines, seven with a note: so many rows, the first few with a note.
    count, notes = divmod(body_lines, 6)
    if count < notes or count < 1:
        raise ValueError("the line count cannot be met with whole rows")
    ids = [f"R{1 + i // 99}.{1 + i % 99:02d}" for i in range(count - 1)] + [last]
    out = list(head)
    for i, row_id in enumerate(ids):
        with_note = i < notes
        name = SHEET_MARK if i == 0 else f"an invented quantity, number {i + 1}"
        out += [
            f'  "{row_id}": {{',
            f'   "quantity": "{name}",',
            f'   "value": {i + 1}.5,',
            '   "unit": "V",',
            '   "url": "https://example.invalid/an/address/for/every/row/of/the/invented/parts/sheet"'
            + ("," if with_note else ""),
        ]
        if with_note:
            out.append('   "note": "an invented note"')
        out.append("  }" + ("," if i < count - 1 else ""))
    out += tail
    text = "\n".join(out) + "\n"
    if text.count("\n") != lines:
        raise ValueError(f"the invented sheet has {text.count(chr(10))} lines, not {lines}")
    json.loads(text)
    return text.encode()


@contextmanager
def counting_endpoint(count: int) -> Iterator[tuple[Any, str, list[dict[str, Any]]]]:
    """The checkout's scripted endpoint, counting the invented sheet's requests at ``count``.

    Yields the endpoint, its base URL and the list of count requests it answered.
    """
    sys.path.insert(0, str(C.REPO / "tests" / "integration" / "orchestrator"))
    import scripted_endpoint as E  # noqa: PLC0415

    api = E.FakeMessagesApi(E.Script(main=[]))
    counted: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
            return

        def do_POST(self) -> None:  # noqa: N802 - the name http.server calls
            raw = self.rfile.read(int(self.headers.get("content-length", 0)))
            if "count_tokens" in self.path:
                sheet = SHEET_MARK in raw.decode("utf-8", errors="replace")
                counted.append({"sheet": sheet, "bytes": len(raw)})
                body = json.dumps({"input_tokens": count if sheet else 10}).encode()
                ctype = "application/json"
            else:
                body, ctype = api.answer(self.path, self.headers, json.loads(raw or b"{}"))
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield api, f"http://127.0.0.1:{server.server_address[1]}", counted
    finally:
        server.shutdown()
        server.server_close()


def read_sheet_then_review(api: Any) -> None:  # noqa: ANN401 - the endpoint's own object
    """The scripted reviewer: read the sheet whole, then every required file, then a verdict."""
    sys.path.insert(0, str(C.REPO / "tests" / "integration" / "orchestrator"))
    sys.path.insert(0, str(C.REPO / "tests"))
    from real_domain_reviewers import scripted_verdict  # noqa: PLC0415
    from scripted_endpoint import Script, text, tool  # noqa: PLC0415

    def on_request(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        read = Path(cwd).parent
        packet = json.loads((read.parent / "packet.json").read_text())
        steps = [tool("Read", file_path=f"{cwd}/parts_sheet.json")]
        steps += [tool("Read", file_path=p) for p in packet["required_reading"]]
        steps.append(tool("StructuredOutput", review=scripted_verdict(read, packet, "reject")))
        return steps[done] if done < len(steps) else text("done")

    api.script = Script(main=[])
    api.on_request = on_request


# ---- invented run logs, for the scripts that read a run ----


def item(
    i: str, result: str, section: str = "domain_standards", evidence: str = "-"
) -> dict[str, str]:
    """One rubric item's answer in a review line."""
    return {"item": i, "section": section, "result": result, "evidence": evidence}


def ran(
    sid: str,
    verdict: str,
    items: list[dict[str, str]],
    failing: str | None = None,
    session: str | None = None,
    rubric: str | None = None,
) -> dict[str, Any]:
    """A ``review_ran`` line."""
    return {
        "kind": "review_ran",
        "subtask_id": sid,
        "attempt": 1,
        "result": {
            "verdict": verdict,
            "items": items,
            "failing_item": failing,
            "session_id": session,
            "rubric_sha256": rubric,
        },
    }


def unavailable(sid: str, cause: str, retry: bool, session: str | None = None) -> dict[str, Any]:
    """A ``review_unavailable`` line."""
    return {
        "kind": "review_unavailable",
        "subtask_id": sid,
        "attempt": 1,
        "cause": cause,
        "retry": retry,
        "session_id": session,
    }


def gate(sid: str, *outcomes: tuple[str, str]) -> dict[str, Any]:
    """A ``gate_ran`` line."""
    checks = [{"name": name, "outcome": out} for name, out in outcomes]
    verdict = "fail" if any(o == "fail" for _, o in outcomes) else "pass"
    return {
        "kind": "gate_ran",
        "subtask_id": sid,
        "attempt": 1,
        "result": {"verdict": verdict, "checks": checks},
    }


def planned(sid: str, role: str) -> dict[str, Any]:
    """A ``subtask_planned`` line."""
    return {"kind": "subtask_planned", "subtask_id": sid, "assigned_role": role}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """``rows`` as JSON lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
