"""A review session's environment switches the binary's compaction off only where the run says so.

Under ``review_compaction: off`` every review session runs with ``DISABLE_COMPACT=1``, as every
review session did before the flag, and its process record names the one variable it added.
Under ``on`` the environment adds nothing, so the binary compacts a review that nears its
window and carries on, and the process record names nothing added.

The session is a stand-in executable that writes what its environment held.
"""

from __future__ import annotations

import json
import stat
import sys
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from startup_stand_in import stand_in_spawn_env

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.packet import WORKTREE_NAME, Packet
from physgate.reviewers.rubric import Rubric

#: The stand-in session: writes whether its environment switched compaction off.
STANDIN = r"""
import json, os, sys
config = os.environ["CLAUDE_CONFIG_DIR"]
with open(os.path.join(os.path.dirname(config), "env.json"), "w") as out:
    json.dump({"DISABLE_COMPACT": os.environ.get("DISABLE_COMPACT")}, out)
sys.exit(0)
"""


def _setup(tmp_path: Path, binary: Path, compaction: str) -> ReviewerSetup:
    assert "review_compaction" in {f.name for f in fields(ReviewerSetup)}, (
        "a reviewer's setup does not carry the run's review_compaction"
    )
    extra: dict[str, Any] = {"review_compaction": compaction}
    return ReviewerSetup(
        run_id="run-1",
        models={"electrical": "claude-sonnet-5"},
        claude_version="2.1.301",
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
        **extra,
    )


def _spawned(tmp_path: Path, compaction: str) -> tuple[dict[str, Any], dict[str, Any]]:
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir(parents=True)
    binary.write_text(f"#!{sys.executable}\n{STANDIN}")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    reviewer = ClaudeReviewer(
        role="electrical",
        setup=_setup(tmp_path, binary, compaction),
        rubric=Rubric(role="electrical", text="r", sha256="0" * 64),
    )
    read = tmp_path / "rs" / "review" / "read"
    (read / WORKTREE_NAME).mkdir(parents=True)
    sdir = tmp_path / "rs" / "review" / "session"
    (sdir / "config").mkdir(parents=True)
    installed = Installed(settings="s", config="c", spawn_args=(), spawn_env=stand_in_spawn_env())
    packet = cast(Packet, SimpleNamespace(read_root=str(read)))
    reviewer._spawn(packet, sdir, installed, "sid", prompt="p", schema={})
    env = json.loads((sdir / "env.json").read_text())
    process = json.loads((sdir / "process.json").read_text())
    return env, process


def test_under_off_the_session_runs_with_compaction_switched_off_as_before(
    tmp_path: Path,
) -> None:
    env, process = _spawned(tmp_path, "off")
    assert env == {"DISABLE_COMPACT": "1"}
    assert process["env_added"] == ["DISABLE_COMPACT"]


def test_under_on_the_environment_adds_nothing_and_says_so(tmp_path: Path) -> None:
    env, process = _spawned(tmp_path, "on")
    assert env == {"DISABLE_COMPACT": None}
    assert process["env_added"] == []


def test_the_environment_is_a_function_of_the_parameter() -> None:
    from physgate.orchestrator import invocation

    reviewer_env = getattr(invocation, "reviewer_env", None)
    assert reviewer_env is not None, "the reviewer's environment is not a function of the flag"
    assert reviewer_env("off") == {"DISABLE_COMPACT": "1"}
    assert reviewer_env("on") == {}


# --- what the hook layer's installer is asked for ---------------------------------------------


def _installer_argv(tmp_path: Path, compaction: str, monkeypatch: Any) -> list[str]:  # noqa: ANN401
    import physgate.reviewers.claude as claude
    from physgate.reviewers.scan import ScanHit

    asked: list[list[str]] = []

    def run(argv: list[str], **_: object) -> object:
        asked.append(argv)
        printed = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(printed), stderr="")

    monkeypatch.setattr(claude, "subprocess", SimpleNamespace(run=run))
    binary = tmp_path / "bin" / "claude"
    reviewer = ClaudeReviewer(
        role="electrical",
        setup=_setup(tmp_path, binary, compaction),
        rubric=Rubric(role="electrical", text="r", sha256="0" * 64),
    )
    read = tmp_path / "read"
    hit = ScanHit(kind="disabled_checks", evidence="toolu_01", what="a check switched off")
    packet = cast(
        Packet,
        SimpleNamespace(
            read_root=str(read),
            required_reading=(str(read / "transcript-01-of-01.md"), str(read / "rubric.md")),
            indicators=(hit,),
        ),
    )
    sdir = tmp_path / "session"
    sdir.mkdir()
    reviewer._install(packet, sdir, tmp_path / "temp")
    (argv,) = asked
    return argv


def test_under_on_the_installer_is_given_the_rubric_and_the_note(
    tmp_path: Path, monkeypatch: Any  # noqa: ANN401
) -> None:
    import physgate.reviewers.claude as claude
    from physgate.reviewers.scan import ScanHit

    argv = _installer_argv(tmp_path, "on", monkeypatch)
    read = tmp_path / "read"
    after = argv.index("--after-compaction")
    assert argv[after + 1] == str(read / "rubric.md")
    note = argv[argv.index("--compaction-note") + 1]
    hit = ScanHit(kind="disabled_checks", evidence="toolu_01", what="a check switched off")
    assert note == claude.compaction_note(read, (hit,))


def test_under_off_the_installer_is_asked_for_what_it_always_was(
    tmp_path: Path, monkeypatch: Any  # noqa: ANN401
) -> None:
    argv = _installer_argv(tmp_path, "off", monkeypatch)
    assert "--after-compaction" not in argv
    assert "--compaction-note" not in argv


def test_the_installer_command_carries_both_into_the_session_s_request(
    tmp_path: Path, monkeypatch: Any  # noqa: ANN401
) -> None:
    from physgate.hooks import cli

    requests: list[Any] = []

    def install(request: Any, registry: object) -> object:  # noqa: ANN401
        requests.append(request)
        return SimpleNamespace(
            settings_path="s", config_path="c", spawn_args=(), spawn_env={}, network_unenforced=None
        )

    monkeypatch.setattr(cli, "install", install)
    rubric = str(tmp_path / "read" / "rubric.md")
    base = [
        "hooks", "install", "--profile", "reviewer", "--worktree", str(tmp_path / "w"),
        "--state-dir", str(tmp_path / "state"), "--target", str(tmp_path / "t"),
        "--claude-config-dir", str(tmp_path / "c"), "--ceiling", "1000",
        "--read-root", str(tmp_path / "read"), "--reading", rubric,
    ]  # fmt: skip
    assert cli.main([*base, "--after-compaction", rubric, "--compaction-note", "N"]) == 0
    assert cli.main(base) == 0
    on, off = requests
    assert (on.after_compaction, on.compaction_note) == ((rubric,), "N")
    assert (off.after_compaction, off.compaction_note) == ((), None)
