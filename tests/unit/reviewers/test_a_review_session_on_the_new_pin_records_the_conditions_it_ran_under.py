"""A review session on 2.1.322 records the catalog, flags, managed tier and policy limits it saw.

Sessions on 2.1.322 carry the feature-flag and non-essential traffic, so the served catalog and
the remote flags are no longer switched off for a review session either. Each invocation of a
review session on that pin writes its own debug log, read once the session is confirmed gone
and removed with it (it may hold the credential), and the managed tier and the policy limits
are read as a role session's are. The review carries what each invocation saw, so the run can
hold it to what it began with.

A review session on 2.1.301 is untouched: its argv is the one it always had, it writes no
debug log, and the review carries nothing new.

The session is a stand-in executable that writes what its argv asked for.
"""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from test_the_reviewer_judges_an_unissued_revision_by_the_one_line_contract import (
    MODEL,
    REPO,
    ROLE,
    _answer,
)

import physgate.reviewers.claude as claude
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.invocation import reviewer_argv
from physgate.orchestrator.managed import (
    POLICY_LIMITS,
    REMOTE_CACHE,
    ObservedTraffic,
    SessionManaged,
)
from physgate.orchestrator.protocols import ReviewResult
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.contract import WRAPPER
from physgate.reviewers.packet import WORKTREE_NAME, Packet
from physgate.reviewers.rubric import Rubric, load_rubric

#: What 2.1.322 logs at the scripted endpoint: the catalog off, as no first-party endpoint.
SEEN = ObservedTraffic(
    served_catalog="off", served_catalog_reason="not_first_party", feature_flags="not reported off"
)
POLICY = b'{"restrictions": {}}'

#: The stand-in session: records its argv beside its configuration directory, then writes
#: what its mode names into the debug log it was given and into its configuration directory.
STANDIN = r"""
import json, os, sys
args = sys.argv[1:]
config = os.environ["CLAUDE_CONFIG_DIR"]
mode = os.environ.get("STANDIN_MODE", "")
with open(os.path.join(os.path.dirname(config), "argv.json"), "w") as out:
    json.dump(args, out)
if "--debug-file" in args:
    with open(args[args.index("--debug-file") + 1], "w") as log:
        log.write("2026-11-11 [servedCatalog] off (not_first_party)\n")
        log.write("a line that may hold the credential\n")
if "policy" in mode:
    with open(os.path.join(config, "policy-limits.json"), "wb") as out:
        out.write(b'{"restrictions": {}}')
if "remote" in mode:
    with open(os.path.join(config, "remote-settings.json"), "w") as out:
        out.write('{"permissions": {"allow": ["Bash"]}}')
sys.exit(0)
"""


def _reviewer(tmp_path: Path, version: str) -> tuple[ClaudeReviewer, Path, Path]:
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir(parents=True)
    binary.write_text(f"#!{sys.executable}\n{STANDIN}")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    setup = ReviewerSetup(
        run_id="run-1",
        models={"electrical": "claude-sonnet-5"},
        claude_version=version,
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        effort="high",
        max_output_tokens=64000,
        token_ceiling=100_000,
        review_root=tmp_path / "rs",
        repo=None,
        install_bin=tmp_path / "install" / "bin" / "x",
        binary=str(binary),
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=tmp_path / "harness",
    )
    rubric = Rubric(role="electrical", text="r", sha256="0" * 64)
    read = tmp_path / "rs" / "review" / "read"
    (read / WORKTREE_NAME).mkdir(parents=True)
    sdir = tmp_path / "rs" / "review" / "session"
    (sdir / "config").mkdir(parents=True)
    return ClaudeReviewer(role="electrical", setup=setup, rubric=rubric), sdir, read


def _spawn(reviewer: ClaudeReviewer, sdir: Path, read: Path, mode: str = "") -> list[str]:
    installed = Installed(settings="s", config="c", spawn_args=(), spawn_env={"STANDIN_MODE": mode})
    packet = cast(Packet, SimpleNamespace(read_root=str(read)))
    reviewer._spawn(packet, sdir, installed, "sid", prompt="p", schema={})
    return cast(list[str], json.loads((sdir / "argv.json").read_text()))


def _logs(sdir: Path) -> list[str]:
    return sorted(p.name for p in (sdir / "config").iterdir() if p.name.startswith("debug"))


def test_a_review_session_on_2_1_301_gets_the_argv_it_always_had_and_records_nothing_new(
    tmp_path: Path,
) -> None:
    reviewer, sdir, read = _reviewer(tmp_path, "2.1.301")
    argv = _spawn(reviewer, sdir, read, mode="policy remote")
    expected = reviewer_argv(
        reviewer._setup.binary,
        prompt="p",
        spawn_args=(),
        schema="{}",
        model="claude-sonnet-5",
        session_id="sid",
        max_turns=20,
        effort="high",
    )
    assert argv == expected[1:]
    assert "--debug-file" not in argv
    assert reviewer._seen == []


def test_a_review_session_on_2_1_322_writes_its_debug_log_beside_its_login_and_nothing_else_moves(
    tmp_path: Path,
) -> None:
    reviewer, sdir, read = _reviewer(tmp_path, "2.1.322")
    argv = _spawn(reviewer, sdir, read)
    without = reviewer_argv(
        reviewer._setup.binary,
        prompt="p",
        spawn_args=(),
        schema="{}",
        model="claude-sonnet-5",
        session_id="sid",
        max_turns=20,
        effort="high",
    )
    assert argv == [*without[1:], "--debug-file", str(sdir / "config" / "debug.log")]


def test_a_review_session_on_2_1_322_records_the_catalog_and_flags_its_log_showed_and_no_log_stays(
    tmp_path: Path,
) -> None:
    reviewer, sdir, read = _reviewer(tmp_path, "2.1.322")
    _spawn(reviewer, sdir, read)
    assert reviewer._seen == [
        SessionManaged(observed_traffic=SEEN, managed_drift=None, policy_limits_sha256=None)
    ]
    assert _logs(sdir) == []  # read, then removed: it may hold the credential


def test_a_review_session_on_2_1_322_records_the_policy_limits_it_received(
    tmp_path: Path,
) -> None:
    reviewer, sdir, read = _reviewer(tmp_path, "2.1.322")
    _spawn(reviewer, sdir, read, mode="policy")
    assert len(reviewer._seen) == 1, "one invocation, one record of what it saw"
    (seen,) = reviewer._seen
    assert seen.policy_limits_sha256 == hashlib.sha256(POLICY).hexdigest()
    assert (sdir / "config" / POLICY_LIMITS).is_file()


def test_a_review_session_on_2_1_322_records_remote_managed_settings_delivered_to_it(
    tmp_path: Path,
) -> None:
    reviewer, sdir, read = _reviewer(tmp_path, "2.1.322")
    _spawn(reviewer, sdir, read, mode="remote")
    assert len(reviewer._seen) == 1, "one invocation, one record of what it saw"
    (seen,) = reviewer._seen
    assert seen.managed_drift is not None and REMOTE_CACHE in seen.managed_drift


def test_an_unconfirmed_stop_reads_no_log_and_still_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unconfirmed(process: subprocess.Popen[bytes], started: object, wall: float) -> object:
        process.wait()
        msg = "the process table could not be read"
        raise OSError(msg)

    monkeypatch.setattr(claude, "await_session", unconfirmed)
    reviewer, sdir, read = _reviewer(tmp_path, "2.1.322")
    with pytest.raises(OSError, match="process table"):
        _spawn(reviewer, sdir, read)
    argv = json.loads((sdir / "argv.json").read_text())
    assert "--debug-file" in argv  # reached: the session was given a log, and wrote it
    assert reviewer._seen == []
    assert _logs(sdir) == []


# --- what each invocation saw reaches the review's result, or its unavailability ---

VALID = _answer(not_evaluable_item=False)
INVALID = _answer(not_evaluable_item=True)
FIRST = SessionManaged(observed_traffic=SEEN, managed_drift=None, policy_limits_sha256=None)
SECOND = FIRST.model_copy(update={"policy_limits_sha256": "b" * 64})


def _review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answers: list[dict[str, Any]],
    seen: list[SessionManaged],
    repairs: int,
    reviews: int = 1,
) -> list[object]:
    """Review ``reviews`` times; each invocation answers in turn and saw the next of ``seen``."""
    read = tmp_path / "rs" / "review" / "read"
    read.mkdir(parents=True)
    packet = SimpleNamespace(read_root=str(read), indicators=(), sha256=lambda: "0" * 64)
    streams: dict[Path, int] = {}

    def spawn(self: ClaudeReviewer, *args: object, **kwargs: object) -> tuple[Path, int, bool]:
        n = len(streams)
        self._seen.append(seen[n])
        path = tmp_path / f"stream-{n}.jsonl"
        path.write_text("")
        streams[path] = n
        return path, 0, False

    def captured(path: Path, data: bytes | None = None) -> object:
        result = {"type": "result", "structured_output": {WRAPPER: answers[streams[path]]}}
        return SimpleNamespace(result=result, usage=(), answered={MODEL}, tampered=None)

    monkeypatch.setattr(claude, "binary_version", lambda binary: "2.1.322")
    monkeypatch.setattr(claude, "review_dir", lambda root, sid: tmp_path / "rs" / "review")
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda self, review, a, sid: packet)
    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda self, p, sdir: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", spawn)
    monkeypatch.setattr(claude, "review_prompt", lambda *a, **k: "p")
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "read_captured", captured)
    monkeypatch.setattr(claude, "require_matching_totals", lambda *a: None)
    monkeypatch.setattr(claude, "unavailable_end", lambda *a, **k: None)
    monkeypatch.setattr(claude, "read_in_full", lambda *a: True)
    monkeypatch.setattr(claude, "write_key_helper", lambda state, key: None)
    setup = ReviewerSetup(
        run_id="run-1",
        models={ROLE: MODEL},
        claude_version="2.1.322",
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        effort="high",
        max_output_tokens=64000,
        token_ceiling=100_000,
        review_root=tmp_path / "rs",
        repo=None,
        install_bin=tmp_path / "install" / "bin" / "x",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=tmp_path / "harness",
        repair_resumes=repairs,
    )
    reviewer = ClaudeReviewer(role=ROLE, setup=setup, rubric=load_rubric(REPO / "knowledge", ROLE))
    out: list[object] = []
    for _ in range(reviews):
        if (tmp_path / "rs" / "review" / "session").exists():
            for p in sorted((tmp_path / "rs" / "review" / "session").iterdir()):
                p.unlink()
            (tmp_path / "rs" / "review" / "session").rmdir()
        try:
            out.append(reviewer.review(SimpleNamespace()))  # type: ignore[arg-type]
        except ReviewUnavailableError as exc:
            out.append(exc)
    return out


def test_a_review_carries_what_each_of_its_invocations_saw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (result,) = _review(tmp_path, monkeypatch, [INVALID, VALID], [FIRST, SECOND], repairs=1)
    assert isinstance(result, ReviewResult) and result.repair_resumes == 1
    assert result.managed == (FIRST, SECOND)


def test_a_review_that_is_no_verdict_carries_what_its_invocations_saw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (result,) = _review(tmp_path, monkeypatch, [INVALID], [FIRST], repairs=0)
    assert isinstance(result, ReviewUnavailableError) and result.cause == "invalid_verdict"
    assert result.managed == (FIRST,)


def test_each_review_carries_only_its_own_invocations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _review(
        tmp_path, monkeypatch, [VALID, VALID], [FIRST, SECOND], repairs=0, reviews=2
    )
    assert isinstance(first, ReviewResult) and first.managed == (FIRST,)
    assert isinstance(second, ReviewResult) and second.managed == (SECOND,)


def test_a_review_with_nothing_seen_is_written_as_before() -> None:
    result = ReviewResult(
        verdict="pass", finding="sound", reviewer_model=MODEL, session_id="s", usage=()
    )
    assert "managed" not in json.loads(result.model_dump_json())


def test_a_stop_the_process_table_does_not_confirm_reads_no_log_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        claude, "still_running", lambda *a: "still running after the stop: [1]", raising=False
    )
    reviewer, sdir, read = _reviewer(tmp_path, "2.1.322")
    argv = _spawn(reviewer, sdir, read)
    assert "--debug-file" in argv  # reached: the session was given a log, and wrote it
    assert reviewer._seen == [
        SessionManaged(observed_traffic=None, managed_drift=None, policy_limits_sha256=None)
    ]
    assert _logs(sdir) == []
