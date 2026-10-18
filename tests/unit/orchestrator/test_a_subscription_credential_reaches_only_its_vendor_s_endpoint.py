"""A subscription credential is delivered only to its vendor's own endpoint.

The runtime sends its login, as an OAuth bearer token, to whatever endpoint the session is
pointed at (measured on the pinned binary against the scripted local endpoint). A run in
subscription mode against a proxy, a gateway or another provider would therefore hand the
person's subscription to a third party. It is refused at every place it could start: when a
new run is configured, when a recorded run is driven again, and where the credential is put
down for a session, before anything of the session exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from orch_helpers import make_config

from physgate.cli import main
from physgate.orchestrator.credentials import LOGIN_FILE, write_login
from physgate.orchestrator.exceptions import CredentialEndpointError, OrchestratorError

TOKEN = "sk-ant-oat01-test-dummy-not-a-credential"

#: Endpoints that are not the vendor's own, in the form a run records them.
FOREIGN = (
    "http://127.0.0.1:53817",
    "http://[::1]:8080",
    "https://api.deepseek.com/anthropic",
    "https://openrouter.ai/api",
    # The vendor's host in clear text, on another port, under a path, or as a prefix.
    "http://api.anthropic.com",
    "https://api.anthropic.com:8443",
    "https://api.anthropic.com/v1",
    "https://api.anthropic.com.example.net",
)
#: The vendor's own: the runtime's default, or its API host named outright.
VENDOR = ("default", "https://api.anthropic.com")


def _files_holding(root: Path, secret: str) -> list[str]:
    return [str(p) for p in root.rglob("*") if p.is_file() and secret.encode() in p.read_bytes()]


@pytest.mark.parametrize("endpoint", FOREIGN)
def test_a_subscription_to_any_other_endpoint_is_refused(endpoint: str) -> None:
    from physgate.orchestrator.credentials import require_vendor_endpoint

    with pytest.raises(CredentialEndpointError, match="its vendor's own endpoint") as caught:
        require_vendor_endpoint("subscription", endpoint)
    assert caught.value.context == {"auth": "subscription", "endpoint": endpoint}


@pytest.mark.parametrize("endpoint", VENDOR)
def test_a_subscription_to_the_vendor_s_own_endpoint_is_delivered(endpoint: str) -> None:
    from physgate.orchestrator.credentials import VENDOR_ENDPOINTS, require_vendor_endpoint

    assert endpoint in VENDOR_ENDPOINTS
    require_vendor_endpoint("subscription", endpoint)


@pytest.mark.parametrize("endpoint", [*FOREIGN, *VENDOR])
def test_an_api_key_is_not_held_to_the_subscription_s_rule(endpoint: str) -> None:
    from physgate.orchestrator.credentials import require_vendor_endpoint

    require_vendor_endpoint("api_key", endpoint)


@pytest.mark.parametrize("endpoint", FOREIGN)
def test_the_login_is_never_written_for_a_foreign_endpoint(tmp_path: Path, endpoint: str) -> None:
    config_dir = tmp_path / "config"
    with pytest.raises(CredentialEndpointError):
        write_login(config_dir, TOKEN, endpoint=endpoint)
    assert not (config_dir / LOGIN_FILE).exists()
    assert _files_holding(tmp_path, TOKEN) == []


def test_the_login_is_written_for_the_vendor_s_endpoint(tmp_path: Path) -> None:
    for endpoint in VENDOR:
        config_dir = tmp_path / endpoint.replace("/", "_").replace(":", "_")
        path = write_login(config_dir, TOKEN, endpoint=endpoint)
        assert json.loads(path.read_text())["claudeAiOauth"]["accessToken"] == TOKEN


@pytest.mark.parametrize("endpoint", FOREIGN)
def test_a_configuration_naming_a_subscription_and_a_foreign_endpoint_is_refused(
    endpoint: str,
) -> None:
    from physgate.orchestrator.run_config import require_credential_endpoint

    with pytest.raises(CredentialEndpointError):
        require_credential_endpoint(make_config(auth="subscription", endpoint=endpoint))
    # The same endpoint with a key, and the subscription at the vendor's own, are runs.
    require_credential_endpoint(make_config(auth="api_key", endpoint=endpoint))
    require_credential_endpoint(make_config(auth="subscription", endpoint="default"))


def _params(tmp_path: Path) -> Path:
    from physgate.orchestrator.cli import EXAMPLES

    params = tmp_path / "params.json"
    params.write_text((EXAMPLES / "params.subscription.json").read_text())
    return params


@pytest.mark.parametrize(
    "base_url", ["https://api.deepseek.com/anthropic", "http://127.0.0.1:53817/"]
)
def test_decompose_refuses_a_subscription_to_a_foreign_endpoint_before_anything_happens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    base_url: str,
) -> None:
    (tmp_path / "brief.md").write_text("Build a robot.\n")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", TOKEN)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", base_url)
    # Refused before the binary is even looked for: nothing of the run is set up.
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PHYSGATE_CLAUDE_BIN", raising=False)
    args = [
        "decompose",
        str(tmp_path / "brief.md"),
        *("--seed", "7", "--run-id", "run-1", "--params", str(_params(tmp_path))),
        *("--target", str(tmp_path), "--run-dir", str(tmp_path / "run")),
    ]
    assert main(args) == 2
    error = json.loads(capsys.readouterr().err)
    assert "its vendor's own endpoint" in error["error"]
    assert error["auth"] == "subscription"
    assert error["endpoint"] == base_url.rstrip("/")
    assert TOKEN not in json.dumps(error)
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("command", ["run", "resume"])
def test_a_recorded_subscription_run_is_never_driven_against_a_foreign_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    from loop_fakes import FakeGate, FakeReviewer

    from physgate.orchestrator.cli import Registrations
    from physgate.orchestrator.record import RunRecord

    foreign = "https://openrouter.ai/api"
    record = RunRecord(make_config(auth="subscription", endpoint=foreign), tmp_path / "run")
    record.start([])
    record.close()
    events = (tmp_path / "run" / "events.jsonl").read_bytes()
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", TOKEN)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", foreign)
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PHYSGATE_CLAUDE_BIN", raising=False)
    registrations = Registrations(gate=FakeGate(), reviewers={"electrical": FakeReviewer()})
    args = [
        command,
        *("--run-dir", str(tmp_path / "run"), "--target", str(tmp_path)),
        *("--install", str(tmp_path / "install"), "--review-root", str(tmp_path / "reviews")),
    ]
    assert main(args, registrations) == 2
    error = json.loads(capsys.readouterr().err)
    assert "its vendor's own endpoint" in error["error"]
    assert (error["auth"], error["endpoint"]) == ("subscription", foreign)
    assert (tmp_path / "run" / "events.jsonl").read_bytes() == events
    assert not (tmp_path / "run" / "sessions").exists()
    assert not (tmp_path / "install").exists()


def test_the_refusal_is_a_domain_error_every_command_reports() -> None:
    assert issubclass(CredentialEndpointError, OrchestratorError)


REPO = Path(__file__).resolve().parents[3]
FOREIGN_URL = "https://api.deepseek.com/anthropic"


def _setup(tmp_path: Path, base_url: str | None) -> object:
    from physgate.orchestrator.credentials import Credential
    from physgate.reviewers.claude import ReviewerSetup

    return ReviewerSetup(
        run_id="run-1",
        models={"electrical": "claude-sonnet-5"},
        claude_version="2.1.301",
        bounds=make_config().bounds,
        effort="high",
        max_output_tokens=64000,
        token_ceiling=100_000,
        review_root=tmp_path / "reviews",
        repo=None,
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="/nonexistent/claude",
        base_url=base_url,
        credential=Credential(mode="subscription", secret=TOKEN),
        library=REPO,
    )


def test_no_reviewer_is_built_to_send_a_subscription_to_a_foreign_endpoint(
    tmp_path: Path,
) -> None:
    from physgate.reviewers.claude import ClaudeReviewer
    from physgate.reviewers.rubric import load_rubric

    rubric = load_rubric(REPO / "knowledge", "electrical")
    with pytest.raises(CredentialEndpointError):
        ClaudeReviewer(role="electrical", setup=_setup(tmp_path, FOREIGN_URL), rubric=rubric)  # type: ignore[arg-type]
    ClaudeReviewer(role="electrical", setup=_setup(tmp_path, None), rubric=rubric)  # type: ignore[arg-type]
    assert not (tmp_path / "reviews").exists()


def test_no_dispatcher_is_built_to_send_a_subscription_to_a_foreign_endpoint(
    tmp_path: Path,
) -> None:
    from typing import Any, cast

    from physgate.orchestrator.credentials import Credential
    from physgate.orchestrator.dispatch import ClaudeDispatcher

    def build(base_url: str | None) -> ClaudeDispatcher:
        return ClaudeDispatcher(
            config=make_config(auth="subscription"),
            run=cast(Any, None),
            store_root=tmp_path / "store",
            install_bin=tmp_path / "install" / "bin" / "physgate",
            binary="/nonexistent/claude",
            base_url=base_url,
            credential=Credential(mode="subscription", secret=TOKEN),
            review_root=tmp_path / "reviews",
        )

    with pytest.raises(CredentialEndpointError):
        build(FOREIGN_URL)
    build(None)
    assert _files_holding(tmp_path, TOKEN) == []


def test_the_one_call_is_refused_before_its_directory_exists(tmp_path: Path) -> None:
    from physgate.orchestrator.credentials import Credential
    from physgate.orchestrator.decompose import call

    with pytest.raises(CredentialEndpointError):
        call(
            "Build a robot.",
            config=make_config(auth="subscription"),
            workdir=tmp_path / "decomposition",
            base_url=FOREIGN_URL,
            credential=Credential(mode="subscription", secret=TOKEN),
        )
    assert not (tmp_path / "decomposition").exists()


def test_the_instrument_builds_no_reviewer_for_a_subscription_to_a_foreign_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    from physgate.evaluation.inject.cli import _real_reviewers
    from physgate.evaluation.inject.runner import InstrumentParams

    params = InstrumentParams(
        auth="subscription",
        reviewers={"electrical": "claude-sonnet-5"},
        bounds=make_config().bounds,
        effort="high",
        max_output_tokens=64000,
        token_ceiling=100_000,
    )
    args = argparse.Namespace(
        install=tmp_path / "install", scratch=tmp_path / "scratch", run_id="inject-1"
    )
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", TOKEN)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", FOREIGN_URL)
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PHYSGATE_CLAUDE_BIN", raising=False)
    built: list[object] = []

    def factory(setup: object) -> dict[str, object]:
        built.append(setup)
        return {}

    with pytest.raises(CredentialEndpointError):
        _real_reviewers(args, params, factory)  # type: ignore[arg-type]
    assert built == []
    assert not (tmp_path / "install").exists()


def test_the_generalist_review_refuses_a_subscription_to_a_foreign_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.orchestrator.run_config import write_run_config

    (tmp_path / "run").mkdir()
    config = make_config(auth="subscription", endpoint=FOREIGN_URL)
    write_run_config(tmp_path / "run" / "run.json", config)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", TOKEN)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", FOREIGN_URL)
    args = [
        "generalist",
        *("--run-dir", str(tmp_path / "run"), "--subtask", "s1", "--attempt", "1"),
        *("--target", str(tmp_path), "--install", str(tmp_path / "install")),
        *("--review-root", str(tmp_path / "reviews"), "--out", str(tmp_path / "out")),
        *("--run-id", "generalist-1", "--prices", "2026-10-16"),
    ]
    assert main(args) == 2
    error = json.loads(capsys.readouterr().err)
    assert "its vendor's own endpoint" in error["error"]
    assert not (tmp_path / "out").exists()
