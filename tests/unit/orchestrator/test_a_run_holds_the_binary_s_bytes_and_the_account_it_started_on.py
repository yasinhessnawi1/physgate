"""A run records the Claude Code binary's bytes and its account, and is driven on no others.

A version string names a release, not the bytes that run: each platform has its own build, and
a binary can be replaced under an unchanged version. When a run is decomposed the command
measures the sha256 of the binary it will execute and this machine's platform, and records them;
``run`` and ``resume`` measure again and refuse a different binary. A run whose numbers may be
reported refuses, before any request or record, a binary that is not the listed build of its
version. Runs may also be spread over several accounts: each names the one it draws on, the
command records that name with a fingerprint of the credential, and a run continued on another
credential is refused. Runs recorded before either was recorded are driven as before.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest
from loop_fakes import FakeGate, FakeReviewer
from orch_helpers import make_config

import physgate.evaluation.requirements as evaluation_requirements
import physgate.orchestrator.cli as orchestrator_cli
from physgate.cli import main
from physgate.evaluation.observe.compare import drift
from physgate.evaluation.observe.rerun import UNRECORDED_ACCOUNT, RerunPlan
from physgate.orchestrator import binaries
from physgate.orchestrator.binaries import KNOWN_BINARIES, ClaudeBinary, KnownBinary
from physgate.orchestrator.credentials import Credential, fingerprint
from physgate.orchestrator.exceptions import InvocationError, RunConfigError
from physgate.orchestrator.run_config import (
    RunAccount,
    RunConfig,
    harness_state,
    load_run_config,
    require_same_account,
    write_run_config,
)

DUMMY = "sk-ant-test-dummy-not-a-credential"
#: A parameter left out of the parameters file.
_DROP = object()
OTHER = "sk-ant-test-another-dummy-credential"


def _checkout(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q", "-b", "master"], ["config", "user.email", "t@example.invalid"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "one"], cwd=root, check=True)
    return root


def _binary(tmp_path: Path, marker: str = "") -> Path:
    """A stand-in that answers ``--version`` and records, and refuses, any other invocation."""
    script = tmp_path / "bin" / "claude"
    script.parent.mkdir(parents=True, exist_ok=True)
    calls = tmp_path / "calls.txt"
    script.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "2.1.272 (Claude Code)"; exit 0; fi\n'
        f'echo called >> "{calls}"\nexit 1\n# {marker}\n'
    )
    script.chmod(0o755)
    return script


def _decompose_args(tmp_path: Path, **extra: object) -> list[str]:
    params = {
        "auth": "api_key",
        "account": "seat-2",
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
        "reportable": False,
        "effort": "high",
        "max_output_tokens": 64000,
        "thinking_display": "summarized",
        "role_python": None,
        "escalation_backend": "rules",
        "queue_decisions": "record",
        "os_layer_absent": "allow",
        "held_out": [],
        "held_out_canaries": [],
        "held_out_sha256": [],
        "network": "open",
        "design_review": "off",
        "ablation": False,
        "reviewers": "paired",
        "skills": "on",
        "hooks": "on",
        **extra,
    }
    params = {k: v for k, v in params.items() if v is not _DROP}
    (tmp_path / "brief.md").write_text("Build a robot.\n")
    (tmp_path / "params.json").write_text(json.dumps(params))
    target = _checkout(tmp_path / "target")
    return [
        "decompose",
        str(tmp_path / "brief.md"),
        *("--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")),
        *("--target", str(target), "--run-dir", str(tmp_path / "run")),
    ]


def _here(sha256: str) -> ClaudeBinary:
    return ClaudeBinary(sha256=sha256, platform=binaries.platform_here())


# ---- measuring --------------------------------------------------------------------------------


def test_the_binary_is_measured_by_the_bytes_its_path_resolves_to(tmp_path: Path) -> None:
    real = _binary(tmp_path)
    link = tmp_path / "claude-link"
    link.symlink_to(real)
    measured = binaries.measure(str(link))
    assert measured.sha256 == hashlib.sha256(real.read_bytes()).hexdigest()
    assert measured.platform == binaries.platform_here()


def test_a_binary_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InvocationError, match="cannot be read"):
        binaries.measure(str(tmp_path / "no-such-binary"))


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("darwin", "arm64", "darwin-arm64"),
        ("linux", "x86_64", "linux-x64"),
        ("linux", "aarch64", "linux-arm64"),
        ("linux", "AMD64", "linux-x64"),
    ],
)
def test_the_platform_is_named_as_the_build_packages_name_it(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, expected: str
) -> None:
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    assert binaries.platform_here() == expected


@pytest.mark.parametrize(("system", "machine"), [("win32", "AMD64"), ("linux", "riscv64")])
def test_a_machine_no_build_is_used_on_is_refused(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str
) -> None:
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    with pytest.raises(InvocationError, match="no Claude Code build"):
        binaries.platform_here()


# ---- the listed builds ------------------------------------------------------------------------


def test_every_listed_build_names_where_its_digest_was_measured() -> None:
    assert KNOWN_BINARIES, "the table lists no build"
    for (version, _platform), known in KNOWN_BINARIES.items():
        assert version.count(".") == 2
        assert known.source.strip()


def test_the_listed_build_of_a_version_is_accepted() -> None:
    (version, platform), known = next(iter(KNOWN_BINARIES.items()))
    binaries.require_listed(version, ClaudeBinary(sha256=known.sha256, platform=platform))


def test_another_digest_under_a_listed_version_and_platform_is_refused() -> None:
    (version, platform), known = next(iter(KNOWN_BINARIES.items()))
    other = ("0" if known.sha256[0] != "0" else "1") + known.sha256[1:]
    with pytest.raises(RunConfigError, match="not the listed") as caught:
        binaries.require_listed(version, ClaudeBinary(sha256=other, platform=platform))
    assert caught.value.context["found"] == other


def test_a_version_or_platform_with_no_listed_build_is_refused() -> None:
    with pytest.raises(RunConfigError, match="is listed"):
        binaries.require_listed("2.1.272", ClaudeBinary(sha256="a" * 64, platform="linux-x64"))


# ---- holding a run to its binary --------------------------------------------------------------


def test_a_run_is_driven_only_on_the_binary_it_recorded() -> None:
    recorded = ClaudeBinary(sha256="a" * 64, platform="linux-x64")
    binaries.require_same(recorded, recorded)
    with pytest.raises(RunConfigError) as caught:
        binaries.require_same(recorded, ClaudeBinary(sha256="b" * 64, platform="linux-x64"))
    assert caught.value.context["changed"] == "sha256"
    with pytest.raises(RunConfigError) as caught:
        binaries.require_same(recorded, ClaudeBinary(sha256="a" * 64, platform="linux-arm64"))
    assert caught.value.context["changed"] == "platform"


def test_a_run_recorded_before_the_binary_was_recorded_is_driven() -> None:
    binaries.require_same(None, ClaudeBinary(sha256="b" * 64, platform="linux-x64"))


# ---- holding a run to its account -------------------------------------------------------------


def test_the_fingerprint_is_a_short_digest_prefix_that_never_holds_the_secret() -> None:
    found = fingerprint(Credential(mode="api_key", secret=DUMMY))
    assert found == hashlib.sha256(DUMMY.encode()).hexdigest()[:12]
    assert DUMMY not in found and found != fingerprint(Credential(mode="api_key", secret=OTHER))


def test_a_run_is_driven_only_on_the_credential_its_account_was_recorded_with() -> None:
    account = RunAccount(
        name="seat-2", token_sha256_prefix=fingerprint(Credential(mode="api_key", secret=DUMMY))
    )
    config = make_config(account=account)
    require_same_account(config, Credential(mode="api_key", secret=DUMMY))
    with pytest.raises(RunConfigError, match="seat-2") as caught:
        require_same_account(config, Credential(mode="api_key", secret=OTHER))
    assert caught.value.context["recorded"] == account.token_sha256_prefix
    require_same_account(make_config(), Credential(mode="api_key", secret=OTHER))


# ---- the record -------------------------------------------------------------------------------


def test_a_record_from_before_reads_as_not_recorded_and_keeps_its_digest(tmp_path: Path) -> None:
    old = make_config()
    path = tmp_path / "run.json"
    write_run_config(path, old)
    raw = json.loads(path.read_text())
    assert "binary" not in raw and "account" not in raw
    assert load_run_config(path).sha256() == old.sha256()


def test_a_new_record_carries_both_and_reads_back_whole(tmp_path: Path) -> None:
    config = make_config(
        binary=ClaudeBinary(sha256="c" * 64, platform="darwin-arm64"),
        account=RunAccount(name="seat-1", token_sha256_prefix="0123456789ab"),
    )
    path = tmp_path / "run.json"
    write_run_config(path, config)
    raw = json.loads(path.read_text())
    assert raw["binary"] == {"sha256": "c" * 64, "platform": "darwin-arm64"}
    assert raw["account"] == {"name": "seat-1", "token_sha256_prefix": "0123456789ab"}
    assert load_run_config(path) == config


def test_compare_refuses_across_two_builds_but_not_across_two_accounts() -> None:
    a = make_config(
        binary=ClaudeBinary(sha256="c" * 64, platform="linux-x64"),
        account=RunAccount(name="seat-1", token_sha256_prefix="0123456789ab"),
    )
    b = make_config(
        binary=ClaudeBinary(sha256="d" * 64, platform="linux-x64"),
        account=RunAccount(name="seat-2", token_sha256_prefix="ba9876543210"),
    )
    assert drift(a, b) == ["binary"]
    assert drift(a, a.model_copy(update={"account": b.account})) == []
    assert drift(a, a.model_copy(update={"binary": None})) == []


# ---- through the command ----------------------------------------------------------------------


def test_decompose_records_the_binary_it_measured_and_the_account_it_was_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The evaluation's requirement on the OS layer, which the stand-in predates, is not the
    # subject here: what is recorded is.
    monkeypatch.setattr(evaluation_requirements, "REQUIREMENTS", ())
    harness = _checkout(tmp_path / "harness")
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY)
    binary = _binary(tmp_path)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(binary))
    main(_decompose_args(tmp_path))  # the call itself fails: no model here
    capsys.readouterr()
    recorded = json.loads((tmp_path / "run" / "run.json").read_text())
    assert recorded["binary"] == {
        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "platform": binaries.platform_here(),
    }
    assert recorded["account"] == {
        "name": "seat-2",
        "token_sha256_prefix": hashlib.sha256(DUMMY.encode()).hexdigest()[:12],
    }
    assert DUMMY not in (tmp_path / "run" / "run.json").read_text()


@pytest.mark.parametrize(
    ("named", "said"),
    [
        (_DROP, "account: Field required"),
        (None, "a new run names the account it draws on"),
        ({"name": "seat-2", "token_sha256_prefix": "0123456789ab"}, "account: "),
    ],
    ids=["absent", "null", "a claimed fingerprint"],
)
def test_a_run_that_names_no_account_is_refused_before_any_request_or_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    named: object,
    said: str,
) -> None:
    monkeypatch.setattr(evaluation_requirements, "REQUIREMENTS", ())
    harness = _checkout(tmp_path / "harness")
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(_binary(tmp_path)))
    assert main(_decompose_args(tmp_path, account=named)) == 2
    error = json.loads(capsys.readouterr().err)
    assert said in f"{error.get('reason', '')} {error['error']}"
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "calls.txt").exists()


def test_a_reportable_run_on_an_unlisted_binary_is_refused_before_any_request_or_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(evaluation_requirements, "REQUIREMENTS", ())
    harness = _checkout(tmp_path / "harness")
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(_binary(tmp_path)))
    assert main(_decompose_args(tmp_path, reportable=True)) == 2
    error = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert "Claude Code 2.1.272 is listed" in error["error"]
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "calls.txt").exists()


def test_a_reportable_run_on_the_listed_build_passes_the_binary_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(evaluation_requirements, "REQUIREMENTS", ())
    harness = _checkout(tmp_path / "harness")
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY)
    binary = _binary(tmp_path)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(binary))
    listed = {
        ("2.1.272", binaries.platform_here()): KnownBinary(
            sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), source="a test's stand-in"
        )
    }
    monkeypatch.setattr(binaries, "KNOWN_BINARIES", listed)
    main(_decompose_args(tmp_path, reportable=True))
    err = capsys.readouterr().err
    assert "is listed" not in err and "not the listed" not in err


def _drive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    *,
    recorded: ClaudeBinary,
    account: RunAccount,
    secret: str,
) -> dict[str, str]:
    harness = _checkout(tmp_path / "harness")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run_config(
        run_dir / "run.json",
        make_config(harness=harness_state(harness), binary=recorded, account=account),
    )
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(_binary(tmp_path)))
    registrations = orchestrator_cli.Registrations(
        gate=FakeGate(), reviewers={"electrical": FakeReviewer()}
    )
    args = [command, "--run-dir", str(run_dir), "--target", str(tmp_path / "t")]
    code = main(
        [*args, "--install", str(tmp_path / "install"), "--review-root", str(tmp_path / "rs")],
        registrations,
    )
    assert code == 2
    assert not (tmp_path / "install").exists() and not (run_dir / "events.jsonl").exists()
    error: dict[str, str] = json.loads(capsys.readouterr().err)
    return error


@pytest.mark.parametrize("command", ["run", "resume"])
def test_run_and_resume_refuse_a_binary_other_than_the_recorded_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    account = RunAccount(
        name="seat-2", token_sha256_prefix=fingerprint(Credential(mode="api_key", secret=DUMMY))
    )
    error = _drive(
        tmp_path,
        monkeypatch,
        capsys,
        command,
        recorded=_here("e" * 64),
        account=account,
        secret=DUMMY,
    )
    assert error["error"] == "the Claude Code binary differs from the one this run recorded"
    assert error["changed"] == "sha256"


@pytest.mark.parametrize("command", ["run", "resume"])
def test_run_and_resume_refuse_another_account_s_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    binary = _binary(tmp_path)
    recorded = _here(hashlib.sha256(binary.read_bytes()).hexdigest())
    account = RunAccount(
        name="seat-2", token_sha256_prefix=fingerprint(Credential(mode="api_key", secret=DUMMY))
    )
    error = _drive(
        tmp_path,
        monkeypatch,
        capsys,
        command,
        recorded=recorded,
        account=account,
        secret=OTHER,
    )
    assert "account 'seat-2' was recorded with" in error["error"]


def test_a_rerun_names_the_recorded_account_and_never_its_fingerprint_or_binary(
    tmp_path: Path,
) -> None:
    def plan(config: RunConfig) -> RerunPlan:
        return RerunPlan(
            recorded=config,
            brief=tmp_path / "brief.md",
            run_id="rerun",
            run_dir=tmp_path / "run",
            target=tmp_path / "t",
            install=tmp_path / "i",
            review_root=tmp_path / "rs",
        )

    recorded = make_config(
        binary=ClaudeBinary(sha256="c" * 64, platform="linux-x64"),
        account=RunAccount(name="seat-3", token_sha256_prefix="0123456789ab"),
    )
    params = plan(recorded).params()
    assert params["account"] == "seat-3"
    assert "binary" not in params and "0123456789ab" not in json.dumps(params)
    assert plan(make_config()).params()["account"] == UNRECORDED_ACCOUNT
