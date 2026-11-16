"""Against every pinned binary: a review under ``review_compaction: on`` that compacts, end to end.

The real binary under the hook layer's reviewer profile, at the scripted endpoint, driven past
its compaction trigger by the last required read; it then reads the rubric again by the range
the note after a compaction names (from offset 1, with a limit of the rubric's lines as the Read
tool counts them), and gives its verdict. The compaction call's own usage is in the binary's
totals and in no message of its stream (measured on both pins), so the review's account holds
it as one line of its own, marked as a compaction, and a repair resume of the same session does
not count it again.

After a compaction the binary carries the files read before it that were modified last into
the next request, and on 2.1.301 a Read with no range of a carried file answers that the file is
unchanged, with nothing the reading hook can record: a reviewer that reads a carried rubric so
reaches no verdict on that pin, and one that reads it by the note's range does (measured, and
held here, with the rubric made the newest file so it is carried every time).

The run-level guard (``COMPACTION_MEASURED_PINS``) is not on this path: the reviewer is built
directly, as every real-binary review row builds it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from compaction_session import (
    COMPACT_USAGE,
    SUMMARY,
    CompactingApi,
    body_text,
    serving,
    usage_of,
)
from knowledge_fixture import write_fixture
from scripted_endpoint import DUMMY_KEY, Script, text, tool
from test_a_claude_review_is_a_verdict_only_when_it_read_everything import (
    RUBRIC,
    _attempt,
    _config,
    _reading,
    verdict,
)

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import binary_version, read_stream
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.protocols import MessageUsage, ReviewResult
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.rubric import Rubric, parse_rubric

BINARIES = [
    b
    for b in (
        os.environ.get("PHYSGATE_PINNED_BINS") or os.environ.get("PHYSGATE_CLAUDE_BIN") or ""
    ).split(os.pathsep)
    if b
]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]

#: A context past the trigger on every pin, as the last read reports it.
PAST = 999_000
FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
KEYS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
#: The range the note after a compaction names for the rubric.
NOTE_RANGE = re.compile(
    r"rubric\.md again in full with the Read tool, from offset (\d+) with limit (\d+);"
)
#: What a review whose rubric is carried and read again with no range ends in, per pin.
PLAIN_REREAD_OF_A_CARRIED_RUBRIC = {"2.1.301": "no_verdict", "2.1.322": "pass"}
#: The suite's rubric with no newline after its last line.
NO_FINAL_NEWLINE = Rubric(
    role="control",
    text=RUBRIC.text.rstrip("\n"),
    sha256=hashlib.sha256(RUBRIC.text.rstrip("\n").encode()).hexdigest(),
    items=parse_rubric(RUBRIC.text.rstrip("\n")),
)


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(
        tmp_path_factory.mktemp("install") / "i", Path(__file__).resolve().parents[3]
    )


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _invalid() -> dict[str, Any]:
    """A verdict the schema takes and the check after the session refuses: a one-word finding."""
    return {**verdict(), "finding": "test"}


def _review(  # noqa: PLR0913 - one review, with how its reviewer reads
    tmp_path: Path,
    install: Path,
    binary: str,
    answers: list[dict[str, Any]],
    *,
    repair_resumes: int = 0,
    rubric: Rubric = RUBRIC,
    by_range: bool = True,
    carried: bool = False,
    compactions: int = 1,
) -> tuple[ReviewResult | Exception, Path]:
    """One review driven past its trigger ``compactions`` times; its outcome and session directory.

    Every required file is read, the last read past the trigger; after each compaction the
    rubric is read again, by the range the note in that request names (``by_range``) or with
    no range, and ``answers`` are given in turn after the last. ``carried`` makes the rubric
    the newest file before the first trigger, so the binary carries it past the compaction.
    """
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    attempt = _attempt(tmp_path)
    config = _config(binary_version(binary)).model_copy(update={"review_compaction": "on"})
    api = CompactingApi(Script(main=[]), SUMMARY)
    plan: list[dict[str, Any] | Callable[[], dict[str, Any]]] = []

    #: The range each note named, ``None`` where it named none (held after the review: the
    #: endpoint answers on its own thread).
    ranges: list[tuple[int, int] | None] = []

    def again(path: str) -> Callable[[], dict[str, Any]]:
        def read() -> dict[str, Any]:
            if not by_range:
                return tool("Read", file_path=path)
            named = NOTE_RANGE.search(body_text(api.bodies[-1]))
            ranges.append(None if named is None else (int(named[1]), int(named[2])))
            if named is None:
                return tool("Read", file_path=path)
            return tool("Read", file_path=path, offset=int(named[1]), limit=int(named[2]))

        return read

    def step(_thread: str, cwd: str, _done: int) -> dict[str, Any]:
        if not plan:
            reading = _reading(cwd)
            (path,) = (p for p in reading if p.endswith("rubric.md"))
            if carried:
                later = time.time() + 5
                os.utime(path, (later, later))
            reads = [tool("Read", file_path=p) for p in reading]
            reads[-1] = {**reads[-1], "usage": usage_of(PAST)}
            plan.extend([*reads, again(path)])
            for _ in range(compactions - 1):
                plan.extend([{**tool("Read", file_path=reading[0]), "usage": usage_of(PAST)}])
                plan.append(again(path))
            plan.extend(tool("StructuredOutput", review=a) for a in answers)
            plan.append(text("done"))
        item = plan.pop(0) if len(plan) > 1 else plan[0]
        return item() if callable(item) else item

    api.on_request = step
    with serving(api) as url:
        setup = ReviewerSetup.of_run(
            config,
            review_root=tmp_path / "rs",
            repo=Path(attempt.worktree),
            install_bin=install,
            binary=binary,
            base_url=url,
            credential=Credential(mode="api_key", secret=DUMMY_KEY),
            library=library,
        )
        setup = dataclasses.replace(setup, repair_resumes=repair_resumes)
        reviewer = ClaudeReviewer(role="control", rubric=rubric, setup=setup)
        try:
            outcome: ReviewResult | Exception = reviewer.review(attempt)
        except Exception as exc:  # noqa: BLE001 - what the review raised is what is measured
            outcome = exc
    (session,) = sorted((tmp_path / "rs").glob("*/session"))
    assert len(api.compaction_requests) == compactions, "the review did not compact as driven"
    if by_range:
        assert len(ranges) == compactions
        assert None not in ranges, "the note after a compaction names no range to read"
    if carried:
        # The rubric's last line is in the first request after the compaction: it was carried.
        last = rubric.text.rstrip("\n").rsplit("\n", 1)[-1]
        assert last in body_text(api.bodies[api.compaction_requests[0] + 1])
    return outcome, session


def _rubric_reads(session: Path) -> list[dict[str, Any]]:
    """Each Read result of the rubric in the session's first stream, as the binary gave it."""
    found = []
    for line in (session / "stdout.jsonl").read_text().splitlines():
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        result = event.get("tool_use_result") if event.get("type") == "user" else None
        if not isinstance(result, dict):
            continue
        file = result.get("file")
        if isinstance(file, dict) and str(file.get("filePath", "")).endswith("rubric.md"):
            found.append(result)
    return found


def _totals(stream: Path) -> dict[str, int]:
    result, _, _ = read_stream(stream.read_text())
    (model,) = ((result or {}).get("modelUsage") or {}).values()
    return {f: int(model[k]) for f, k in zip(FIELDS, KEYS, strict=True)}


def _summed(usage: tuple[MessageUsage, ...]) -> dict[str, int]:
    return {f: sum(int(getattr(m.usage, f)) for m in usage) for f in FIELDS}


def _marked(usage: tuple[MessageUsage, ...]) -> list[MessageUsage]:
    return [m for m in usage if getattr(m, "compaction", False)]


def test_a_review_that_compacts_reaches_its_verdict_with_the_compaction_counted_once(
    tmp_path: Path, install: Path, binary: str
) -> None:
    outcome, session = _review(tmp_path, install, binary, [verdict()])
    assert isinstance(outcome, ReviewResult), repr(outcome)
    assert outcome.verdict == "pass" and outcome.compactions == 1
    assert len(outcome.compaction_pre_tokens) == 1
    (line,) = _marked(outcome.usage)
    assert {f: int(getattr(line.usage, f)) for f in FIELDS} == {f: COMPACT_USAGE[f] for f in FIELDS}
    # With the line, the review's account is the binary's own totals, each token once.
    assert _summed(outcome.usage) == _totals(session / "stdout.jsonl")


def test_a_repair_resume_after_a_compaction_does_not_count_it_again(
    tmp_path: Path, install: Path, binary: str
) -> None:
    outcome, session = _review(tmp_path, install, binary, [_invalid(), verdict()], repair_resumes=1)
    assert isinstance(outcome, ReviewResult), repr(outcome)
    assert outcome.verdict == "pass" and outcome.compactions == 1
    assert outcome.repair_resumes == 1
    # One compaction line across both invocations; the resumed invocation's totals are the
    # whole session's, and the account matches them.
    assert len(_marked(outcome.usage)) == 1
    assert _summed(outcome.usage) == _totals(session / "stdout-repair-1.jsonl")
    # The record keeps the mark, and only on the compaction's line.
    dumped = [json.loads(m.model_dump_json()) for m in outcome.usage]
    assert sum(1 for d in dumped if d.get("compaction") is True) == 1
    assert all("compaction" not in d for d in dumped if not d.get("compaction"))


@pytest.mark.parametrize("rubric", [RUBRIC, NO_FINAL_NEWLINE], ids=["newline", "none"])
def test_a_reviewer_that_reads_its_carried_rubric_by_the_note_s_range_reaches_its_verdict(
    tmp_path: Path, install: Path, binary: str, rubric: Rubric
) -> None:
    outcome, session = _review(tmp_path, install, binary, [verdict()], rubric=rubric, carried=True)
    assert isinstance(outcome, ReviewResult), repr(outcome)
    assert outcome.verdict == "pass" and outcome.compactions == 1
    # The re-read is the rubric in full, as the Read tool counts its lines, from line 1.
    lines = rubric.text.count("\n") + 1
    first, again = _rubric_reads(session)
    assert again["type"] == "text"
    assert (again["file"]["startLine"], again["file"]["numLines"]) == (1, lines)
    assert again["file"]["totalLines"] == first["file"]["totalLines"] == lines


def test_a_reviewer_that_reads_its_carried_rubric_with_no_range_ends_as_measured_on_each_pin(
    tmp_path: Path, install: Path, binary: str
) -> None:
    expected = PLAIN_REREAD_OF_A_CARRIED_RUBRIC.get(binary_version(binary))
    assert expected is not None, f"nothing was measured on {binary_version(binary)}"
    outcome, session = _review(tmp_path, install, binary, [verdict()], by_range=False, carried=True)
    if expected == "pass":
        assert isinstance(outcome, ReviewResult), repr(outcome)
        assert outcome.verdict == "pass" and outcome.compactions == 1
        return
    # 2.1.301: the re-read answers that the file is unchanged, with no lines the reading hook
    # can record, so the verdict is refused until the session runs out of turns.
    assert isinstance(outcome, ReviewUnavailableError), repr(outcome)
    assert outcome.cause == expected
    plain = _rubric_reads(session)[1]
    assert plain["type"] == "file_unchanged" and set(plain["file"]) == {"filePath"}


def test_a_reviewer_that_compacts_twice_reads_its_rubric_by_each_note_s_range_to_a_verdict(
    tmp_path: Path, install: Path, binary: str
) -> None:
    outcome, session = _review(tmp_path, install, binary, [verdict()], carried=True, compactions=2)
    assert isinstance(outcome, ReviewResult), repr(outcome)
    assert outcome.verdict == "pass" and outcome.compactions == 2
    assert [r["type"] for r in _rubric_reads(session)] == ["text", "text", "text"]
    assert _summed(outcome.usage) == _totals(session / "stdout.jsonl")
