"""Stand-ins for a blind check's kept session, laid out as the check keeps a real one.

The layout and the stream's shape are the ones the scripted-endpoint check on the pinned binary
leaves under the role's withheld root (``withheld/check/<session id>/``): ``record.json`` (how
the session ended, what it spent, whether a canary showed) and ``stdout.jsonl``, the binary's
stream, whose start names the directory it worked in, its model and the binary's version; whose
assistant lines hold each tool call; and whose user lines hold each call's result, with the time
and, for a read, the file read whole. Nothing is read from a real store: each stand-in is built
from the fixture version's own held-out tier, in the row's temporary directory.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from physgate.evaluation.tiers.check_tasks import QUESTIONS, bundle
from physgate.evaluation.tiers.store import check_evidence, version_dir, work_root

ANSWERED_AT = "2026-11-18T09:41:07.512Z"
#: How the import says the time above.
ANSWERED = "2026-11-18T09:41:07Z"
SPENT = {"cap": 500000, "end": "ended", "tokens": 150878, "wall_clock_s": 165.2}

Answers = Callable[[list[str]], dict[str, Any]]


def one_flagged(keys: list[str]) -> dict[str, Any]:
    """Every task yes on all three questions but the first key's, which is not answerable."""
    found: dict[str, Any] = {k: dict.fromkeys(QUESTIONS, True) for k in keys}
    found[sorted(keys)[0]]["answerable_as_asked"] = False
    return found


def all_yes(keys: list[str]) -> dict[str, Any]:
    return {k: dict.fromkeys(QUESTIONS, True) for k in keys}


def given(store: Path, version: str) -> dict[str, Any]:
    """The tasks a check of ``version`` is given, as its tasks file holds them."""
    found: dict[str, Any] = json.loads(
        json.dumps(bundle(version_dir(store, "control", version) / "held_out"))
    )
    return found


def _call(n: int, name: str, model: str, **arguments: Any) -> dict[str, Any]:  # noqa: ANN401
    block = {"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": arguments}
    message = {"id": f"msg_{n}", "type": "message", "role": "assistant", "model": model}
    return {"type": "assistant", "message": {**message, "content": [block]}}


def _result(
    n: int, text: str, *, error: bool = False, at: str | None = None, result: object = None
) -> dict[str, Any]:
    block: dict[str, Any] = {"tool_use_id": f"toolu_{n}", "type": "tool_result", "content": text}
    if error:
        block["is_error"] = True
    line: dict[str, Any] = {"type": "user", "message": {"role": "user", "content": [block]}}
    if at is not None:
        line["timestamp"] = at
    if result is not None:
        line["tool_use_result"] = result
    return line


def kept_session(
    store: Path,
    version: str,
    answers: Answers | dict[str, Any] = one_flagged,
    *,
    session_id: str = "5c0e2a51-7d4b-4c55-9a43-2f0d6c1b8e7a",
    model: str = "claude-sonnet-5",
    binary: str = "2.1.322",
    read: str = "whole",
    tasks: Mapping[str, Any] | None = None,
    write: str = "tool",
    refused_after: Answers | None = None,
    after: Sequence[tuple[str, dict[str, Any]]] = (),
    record: Mapping[str, Any] | None = None,
) -> Path:
    """A kept check session on ``version``, as the check leaves one; its directory.

    ``answers``: what it writes to its answer file, given the tasks' keys. ``read``: ``whole``
    (its stream holds its whole read of the tasks file), ``part`` (a read of some lines) or
    ``none``. ``tasks``: what that read shows, the version's own tasks by default. ``write``:
    ``tool`` (its file-write tool, the result not an error), ``shell`` (a shell command) or
    ``none``. ``refused_after``: an answer whose write was refused after the one that landed.
    ``after``: tool calls made after the answer was written, by name and input. ``record``:
    fields of its record in place of an ended session's.
    """
    shown = dict(given(store, version) if tasks is None else tasks)
    keys = sorted(shown)
    body = answers(keys) if callable(answers) else answers
    cwd = str(work_root(store, "control") / "check-0a1b2c3d4e5f6a7b" / "worktree")
    lines: list[dict[str, Any]] = [
        {"type": "system", "subtype": "hook_started", "session_id": session_id},
        {
            "type": "system",
            "subtype": "init",
            "cwd": cwd,
            "session_id": session_id,
            "model": model,
            "claude_code_version": binary,
            "tools": ["Bash", "Read", "Write"],
        },
    ]
    n = 0
    if read != "none":
        n += 1
        text = json.dumps(shown, sort_keys=True, indent=1)
        total = text.count("\n") + 1
        part = 40 if read == "part" else total
        file = {
            "filePath": f"{cwd}/tasks.json",
            "content": "\n".join(text.split("\n")[:part]),
            "numLines": part,
            "startLine": 1,
            "totalLines": total,
        }
        lines += [
            _call(n, "Read", model, file_path=f"{cwd}/tasks.json"),
            _result(
                n, "1\t{", at="2026-11-18T09:40:59.100Z", result={"type": "text", "file": file}
            ),
        ]
    n += 1
    content = json.dumps(body)
    if write == "tool":
        lines += [
            _call(n, "Write", model, file_path=f"{cwd}/answers.json", content=content),
            _result(n, f"File created successfully at: {cwd}/answers.json", at=ANSWERED_AT),
        ]
    elif write == "shell":
        command = f"cat > answers.json <<'EOF'\n{content}\nEOF"
        lines += [
            _call(n, "Bash", model, command=command, description="x"),
            _result(n, "", at=ANSWERED_AT),
        ]
    if refused_after is not None:
        n += 1
        late = json.dumps(refused_after(keys))
        lines += [
            _call(n, "Write", model, file_path=f"{cwd}/answers.json", content=late),
            _result(n, "PreToolUse:Write hook error: refused", error=True, at=ANSWERED_AT),
        ]
    for name, arguments in after:
        n += 1
        lines += [_call(n, name, model, **arguments), _result(n, "", at=ANSWERED_AT)]
    lines.append({"type": "result", "subtype": "success", "session_id": session_id})
    here = check_evidence(store, "control") / session_id
    here.mkdir(parents=True)
    (here / "stdout.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    kept: dict[str, Any] = {
        "session_id": session_id,
        **SPENT,
        "exit_code": 0,
        "held_out_seen": False,
        "evidence_dropped": [],
        "tokens_not_in_binary_totals": 0,
        **(record or {}),
    }
    (here / "record.json").write_text(json.dumps(kept, sort_keys=True, indent=1))
    return here


def printed(flagged: Sequence[str], tasks: int = 8, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    """The line the check printed of such a session: counts, the flagged digests and the spend."""
    body: dict[str, Any] = {
        "all_yes": tasks - len(flagged),
        "answered": True,
        "flagged": sorted(flagged),
        "session": dict(SPENT),
        "tasks": tasks,
    }
    body.update(changes)
    return body
