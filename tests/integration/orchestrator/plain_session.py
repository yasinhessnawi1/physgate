"""One plain session of a pinned binary at the scripted endpoint, and how the harness reads its end.

No hook layer and no role: what is measured is the binary's own ending (its result
event, its exit status, what it writes after the result and on stderr), in the
environment every session of its pin gets, and what each reader of a session's end
makes of it: a role session's classification, a review's, the decomposition call's.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripted_endpoint import DUMMY_KEY, DUMMY_OAUTH_TOKEN, Recorded, Script, serving

from physgate.lines import split_lines
from physgate.orchestrator.budget import SessionEnd, classify_session_end, writes_lost
from physgate.orchestrator.credentials import write_login
from physgate.orchestrator.decompose import binary_version, judge, read_stream, schema_refusal
from physgate.orchestrator.dispatch import Captured, captured_from, tail_owner
from physgate.orchestrator.invocation import isolated_env
from physgate.reviewers.claude import COMPACT_BOUNDARY, unavailable_end

#: The reviewer's model string in the evaluation's runs.
MODEL = "claude-sonnet-5"
#: A structured answer's schema, small enough to break on purpose.
SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
)
PROMPT = "Read a.txt and answer."


@dataclass(frozen=True)
class Ended:
    """A session as it ended: its stream, its exit, and what the endpoint saw."""

    version: str
    stdout: str
    stderr: str
    exit_code: int
    requests: tuple[Recorded, ...]
    session_id: str

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
        """The stream's result event, as every reader of a session's end takes it."""
        return read_stream(self.stdout)[0]

    @property
    def after_result(self) -> list[dict[str, Any]]:
        """The events the binary wrote after its result."""
        events = self.events
        last = max((i for i, e in enumerate(events) if e.get("type") == "result"), default=None)
        return [] if last is None else events[last + 1 :]

    @property
    def compacted(self) -> bool:
        """Whether the stream marks a compaction."""
        return any(
            e.get("type") == "system" and e.get("subtype") == COMPACT_BOUNDARY for e in self.events
        )

    def _as_dispatch_reads_it(self) -> Captured:
        """The stream as the dispatcher reads a role session's on this pin."""
        return captured_from(
            self.stdout.encode(), own_tail_of=tail_owner(self.version, self.session_id)
        )

    @property
    def forged(self) -> str | None:
        """Why a role session's stream is not taken as the runtime's alone, or ``None``."""
        return self._as_dispatch_reads_it().tampered

    def as_a_role_session(self) -> SessionEnd:
        """How a role session with this end is classified."""
        captured = self._as_dispatch_reads_it()
        return classify_session_end(
            captured.result,
            exit_code=self.exit_code,
            stopped_at_wall_clock=False,
            lost=captured.lost,
            claude_version=self.version,
        )

    def as_a_review(self) -> str | None:
        """Why a review with this end is no verdict, or ``None`` if a verdict may be read."""
        cut = unavailable_end(self.stdout, self.result, exit_code=self.exit_code, timed_out=False)
        return None if cut is None else cut[0]

    def as_the_decomposition(self) -> str | None:
        """Why a decomposition call with this end gives no plan, or ``None`` if it gives one."""
        result, _, answered = read_stream(self.stdout)
        return judge(
            result,
            exit_code=self.exit_code,
            timed_out=False,
            model=MODEL,
            roles=["control"],
            answered=answered,
            refused=schema_refusal(self.stdout),
            lost=writes_lost(self.stdout),
            claude_version=self.version,
        )[0]


def run_session(  # noqa: PLR0913 - one session, with everything it is given
    binary: str,
    work: Path,
    steps: list[dict[str, Any]],
    *,
    max_turns: int = 20,
    structured: bool = False,
    env: dict[str, str] | None = None,
    settings: dict[str, Any] | None = None,
    subscription: bool = False,
    on_request: Callable[[str, str, int], dict[str, Any] | None] | None = None,
    prepare: Callable[[Path], None] | None = None,
) -> Ended:
    """Run one session in ``work`` on the scripted ``steps`` and return how it ended.

    ``env`` is added to, or replaces, what the pin's sessions get; ``prepare`` is given the
    session's directory once its ``home``, ``config`` and ``cwd`` exist, before it starts.
    """
    version = binary_version(binary)
    for name in ("home", "config", "cwd"):
        (work / name).mkdir(parents=True, exist_ok=True)
    (work / "cwd" / "a.txt").write_text("hello\n")
    settings_file = work / "settings.json"
    settings_file.write_text(json.dumps(settings or {}))
    session_id = str(uuid.uuid4())
    if prepare is not None:
        prepare(work)
    with serving(Script(main=steps)) as (api, url):
        api.on_request = on_request
        session_env = isolated_env(
            home=work / "home",
            config_dir=work / "config",
            binary=binary,
            claude_version=version,
            max_retries=0,
            max_output_tokens=1000,
            base_url=url,
            api_key=None if subscription else DUMMY_KEY,
        )
        session_env.update(env or {})
        if subscription:
            write_login(work / "config", DUMMY_OAUTH_TOKEN)
        argv = [
            binary,
            "-p",
            PROMPT,
            "--setting-sources",
            "",
            "--settings",
            str(settings_file),
            "--tools",
            "Read,Bash",
            *(("--json-schema", SCHEMA) if structured else ()),
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--model",
            MODEL,
            "--effort",
            "low",
            "--session-id",
            session_id,
            "--max-turns",
            str(max_turns),
            "--permission-mode",
            "bypassPermissions",
        ]
        done = subprocess.run(
            argv,
            cwd=work / "cwd",
            env=session_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        requests = tuple(api.requests)
    return Ended(
        version=version,
        stdout=done.stdout,
        stderr=done.stderr,
        exit_code=done.returncode,
        requests=requests,
        session_id=session_id,
    )
