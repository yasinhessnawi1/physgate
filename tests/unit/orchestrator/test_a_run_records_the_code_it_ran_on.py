"""A run records the checkout it ran from, and a reportable one starts only from a clean commit.

A number is reproducible only if the code that produced it can be named. The
harness's commit, whether its tree was clean, and a digest of anything
uncommitted are measured when a run is decomposed and recorded in ``run.json``;
``run`` and ``resume`` refuse to drive it on anything else, and a run marked
reportable refuses to start from a dirty tree or from no checkout at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from loop_fakes import FakeGate, FakeReviewer
from orch_helpers import CLEAN_HARNESS, make_config
from pydantic import ValidationError

import physgate.orchestrator.cli as orchestrator_cli
from physgate.cli import main
from physgate.orchestrator.exceptions import RunConfigError
from physgate.orchestrator.run_config import (
    HarnessState,
    harness_state,
    require_harness,
    require_reportable,
    write_run_config,
)


def checkout(root: Path) -> Path:
    """A git checkout with one committed file."""
    root.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q", "-b", "master"], ["config", "user.email", "t@example.invalid"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "a.py").write_text("x = 1\n")
    (root / ".gitignore").write_text("ignored/\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "one"], cwd=root, check=True)
    return root


def head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_a_clean_checkout_is_its_commit_and_nothing_else(tmp_path: Path) -> None:
    root = checkout(tmp_path / "h")
    (root / "ignored").mkdir()
    (root / "ignored" / "big.bin").write_bytes(b"\0" * 10)  # ignored files are not the code
    state = harness_state(root)
    assert state == HarnessState(commit=head(root), clean=True, uncommitted_sha256=None)


def test_an_edited_file_and_an_untracked_file_each_make_the_tree_dirty(tmp_path: Path) -> None:
    root = checkout(tmp_path / "h")
    (root / "a.py").write_text("x = 2\n")
    edited = harness_state(root)
    assert edited.commit == head(root) and not edited.clean and edited.uncommitted_sha256
    subprocess.run(["git", "checkout", "--", "a.py"], cwd=root, check=True)
    (root / "new.py").write_text("y = 1\n")
    added = harness_state(root)
    assert not added.clean and added.uncommitted_sha256 not in (None, edited.uncommitted_sha256)
    (root / "new.py").write_text("y = 2\n")  # the untracked file's content is in the digest
    assert harness_state(root).uncommitted_sha256 != added.uncommitted_sha256


def _dirty(root: Path) -> None:
    """An edit to a tracked file, and a binary one: what the digest's patch holds."""
    (root / "a.py").write_text("x = 2\n")
    (root / "b.bin").write_bytes(b"\0\1\2")
    subprocess.run(["git", "add", "b.bin"], cwd=root, check=True)
    (root / "b.bin").write_bytes(b"\0\1\3")


def test_a_dirty_checkout_s_digest_is_of_git_s_default_patch(tmp_path: Path) -> None:
    # Digests recorded before the patch was read with explicit flags stay valid: on a checkout
    # that sets nothing, the digest is still that of the patch plain git writes.
    root = checkout(tmp_path / "h")
    _dirty(root)
    plain = subprocess.run(
        ["git", "-c", "core.attributesFile=/dev/null", "diff", "--binary", "HEAD"],
        cwd=root,
        env={"PATH": "/usr/bin:/bin", "HOME": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": os.devnull},
        capture_output=True,
        check=True,
    ).stdout  # fmt: skip
    assert plain.startswith(b"diff --git a/a.py b/a.py")
    assert harness_state(root).uncommitted_sha256 == hashlib.sha256(plain).hexdigest()


def test_the_checkout_s_own_diff_settings_do_not_change_its_digest(tmp_path: Path) -> None:
    root = checkout(tmp_path / "h")
    _dirty(root)
    before = harness_state(root)
    # Inert local settings, visible only in the patch git writes: no path prefixes, mnemonic
    # prefixes, and colour codes even into a pipe.
    for key, value in (
        ("diff.noprefix", "true"),
        ("diff.mnemonicPrefix", "true"),
        ("color.ui", "always"),
    ):
        subprocess.run(["git", "config", key, value], cwd=root, check=True)
    assert harness_state(root) == before


def test_no_checkout_is_recorded_as_none_and_not_clean(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    expected = HarnessState(commit=None, clean=False, uncommitted_sha256=None)
    assert harness_state(tmp_path / "plain") == expected
    assert harness_state(None) == expected


@pytest.mark.parametrize(
    ("commit", "clean", "digest"),
    [
        (None, True, None),
        (None, False, "d" * 64),
        ("c" * 40, True, "d" * 64),
        ("c" * 40, False, None),
    ],
)
def test_a_harness_record_that_contradicts_itself_is_refused(
    commit: str | None, clean: bool, digest: str | None
) -> None:
    with pytest.raises(ValidationError):
        HarnessState(commit=commit, clean=clean, uncommitted_sha256=digest)


@pytest.mark.parametrize(
    "harness",
    [
        HarnessState(commit="c" * 40, clean=False, uncommitted_sha256="d" * 64),
        HarnessState(commit=None, clean=False, uncommitted_sha256=None),
    ],
)
def test_a_reportable_run_from_a_dirty_tree_or_no_checkout_is_refused(
    harness: HarnessState,
) -> None:
    with pytest.raises(RunConfigError, match="reportable"):
        require_reportable(harness, reportable=True)
    # The schema holds the same rule, so a configuration built past the check is refused too.
    with pytest.raises(ValidationError, match="reportable run starts only"):
        make_config(reportable=True, harness=harness)
    require_reportable(harness, reportable=False)
    assert make_config(reportable=False, harness=harness).harness == harness


def test_a_reportable_run_from_a_clean_commit_is_accepted() -> None:
    require_reportable(CLEAN_HARNESS, reportable=True)
    assert make_config(reportable=True, harness=CLEAN_HARNESS).reportable


def test_a_changed_harness_is_refused_and_names_what_changed() -> None:
    config = make_config(harness=CLEAN_HARNESS)
    require_harness(config, CLEAN_HARNESS)
    moved = HarnessState(commit="e" * 40, clean=True, uncommitted_sha256=None)
    with pytest.raises(RunConfigError) as caught:
        require_harness(config, moved)
    assert caught.value.context["changed"] == "commit"
    dirty = HarnessState(commit="c" * 40, clean=False, uncommitted_sha256="d" * 64)
    with pytest.raises(RunConfigError) as caught:
        require_harness(config, dirty)
    assert caught.value.context["changed"] == "clean,uncommitted_sha256"


def _decompose_args(tmp_path: Path, reportable: bool) -> list[str]:
    params = {
        "auth": "api_key",
        "gate_mode": "on",
        "models": {
            "decomposition": "claude-sonnet-5",
            "roles": {"electrical": "claude-sonnet-5"},
            "reviewers": {"electrical": "claude-opus-5-5"},
        },
        "bounds": {
            "binary_max_retries": 0,
            "session_wall_clock_s": 120.0,
            "session_max_turns": 20,
            "infra_retry_delays_s": [],
        },
        "token_ceiling": 100000,
        "reportable": reportable,
        "effort": "high",
        "max_output_tokens": 64000,
        "thinking_display": "summarized",
        "role_python": None,
        "escalation_backend": "rules",
        "queue_decisions": "record",
        "held_out": [],
        "held_out_canaries": [],
        "held_out_sha256": [],
        "network": "open",
        # A parameters file cannot name the harness: it is measured and overrules this.
        "harness": {"commit": "f" * 40, "clean": True, "uncommitted_sha256": None},
    }
    (tmp_path / "brief.md").write_text("Build a robot.\n")
    (tmp_path / "params.json").write_text(json.dumps(params))
    target = checkout(tmp_path / "target")
    return [
        "decompose",
        str(tmp_path / "brief.md"),
        "--seed",
        "7",
        "--run-id",
        "run-1",
        "--params",
        str(tmp_path / "params.json"),
        "--target",
        str(target),
        "--run-dir",
        str(tmp_path / "run"),
    ]


def _refusing_binary(tmp_path: Path) -> Path:
    """A binary that answers ``--version`` and records any other invocation, which it refuses."""
    script = tmp_path / "bin" / "claude"
    script.parent.mkdir(parents=True, exist_ok=True)
    calls = tmp_path / "calls.txt"
    script.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "2.1.272 (Claude Code)"; exit 0; fi\n'
        f'echo called >> "{calls}"\nexit 1\n'
    )
    script.chmod(0o755)
    return script


@pytest.mark.parametrize("state", ["dirty", "none"])
def test_decompose_refuses_a_reportable_run_before_any_request_or_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: str,
) -> None:
    harness = checkout(tmp_path / "harness")
    (harness / "a.py").write_text("x = 2\n")
    monkeypatch.setattr(
        orchestrator_cli, "_harness_root", lambda: harness if state == "dirty" else None
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(_refusing_binary(tmp_path)))
    assert main(_decompose_args(tmp_path, reportable=True)) == 2
    assert "reportable run" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "calls.txt").exists()  # no invocation but the version check


def test_decompose_records_the_measured_harness_not_the_parameters_file_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = checkout(tmp_path / "harness")
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(_refusing_binary(tmp_path)))
    # What is recorded is the subject here, not the evaluation's requirement on the OS
    # layer, which this machine's stand-in binary predates: the next test is about that.
    import physgate.evaluation.requirements as evaluation_requirements

    monkeypatch.setattr(evaluation_requirements, "REQUIREMENTS", ())
    main(_decompose_args(tmp_path, reportable=True))  # the call itself fails: no model here
    capsys.readouterr()
    recorded = json.loads((tmp_path / "run" / "run.json").read_text())
    assert recorded["harness"] == {
        "commit": head(harness),
        "clean": True,
        "uncommitted_sha256": None,
    }
    assert recorded["reportable"] is True


def test_a_reportable_run_without_the_os_layer_is_refused_before_any_request_or_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = checkout(tmp_path / "harness")
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(_refusing_binary(tmp_path)))
    assert main(_decompose_args(tmp_path, reportable=True)) == 2
    err = capsys.readouterr().err
    error = json.loads(err.strip().splitlines()[-1])
    assert error["error"] == "the run may not start"
    assert "only inside the OS layer" in error["requirements"]
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "calls.txt").exists(), "the binary was called for the decomposition"


@pytest.mark.parametrize("command", ["run", "resume"])
def test_run_and_resume_refuse_a_harness_that_moved_since_the_run_was_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    harness = checkout(tmp_path / "harness")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run_config(run_dir / "run.json", make_config(harness=harness_state(harness)))
    (harness / "b.py").write_text("z = 1\n")  # a change after the run was recorded
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    registrations = orchestrator_cli.Registrations(
        gate=FakeGate(), reviewers={"electrical": FakeReviewer()}
    )
    args = [command, "--run-dir", str(run_dir), "--target", str(tmp_path / "t")]
    assert (
        main(
            [*args, "--install", str(tmp_path / "install"), "--review-root", str(tmp_path / "rs")],
            registrations,
        )
        == 2
    )
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "the harness checkout differs from the one this run recorded"
    assert error["changed"] == "clean,uncommitted_sha256"
    assert not (tmp_path / "install").exists() and not (run_dir / "events.jsonl").exists()
