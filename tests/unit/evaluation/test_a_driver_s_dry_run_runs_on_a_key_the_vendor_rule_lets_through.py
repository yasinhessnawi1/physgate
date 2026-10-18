"""Every real-run driver's dry run runs on a dummy key; its real run keeps the subscription.

A subscription is delivered only to its vendor's own endpoint, and a dry run serves every
session from the scripted local endpoint, which is not it. So each driver's dry run runs on a
dummy key, names ``api_key`` in the parameters it writes, and never reads the env file; its
real run runs on the subscription at the vendor's default endpoint. Each driver is run here up
to the point where its work starts, the work stood in for, and what it would hand the
orchestrator is held to the rule the orchestrator applies (``require_vendor_endpoint``).
Afterwards nothing of the credential is left in the process's environment.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integration" / "orchestrator"))
import real_domain_reviewers as domain_reviewers  # noqa: E402
import real_domain_roles as roles  # noqa: E402
import real_instrument_pilot as pilot  # noqa: E402
import real_paired_reviewers as paired  # noqa: E402
import real_rerun as rerun  # noqa: E402
import spot_check  # noqa: E402
from scripted_endpoint import DUMMY_KEY  # noqa: E402

from physgate.orchestrator.credentials import require_vendor_endpoint  # noqa: E402
from physgate.orchestrator.exceptions import CredentialEndpointError  # noqa: E402
from physgate.orchestrator.run_config import endpoint_of  # noqa: E402

TOKEN = "sk-ant-oat01-test-dummy-not-a-credential"
KINDS = ["--dry-run", "--real"]
VARIABLES = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL")


def _seen(auth: str, base_url: str | None = None) -> dict[str, Any]:
    """What the driver hands the orchestrator at the moment its work starts."""
    return {
        "auth": auth,
        "key": os.environ.get("ANTHROPIC_API_KEY"),
        "subscription": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
        "base_url": base_url if base_url is not None else os.environ.get("ANTHROPIC_BASE_URL"),
    }


def _work(seen: list[dict[str, Any]], auth: Callable[[], str]) -> Callable[[Path], dict[str, Any]]:
    """A stand-in for a driver's work: it records what it was handed and does nothing."""

    def work(root: Path) -> dict[str, Any]:
        seen.append(_seen(auth()))
        return {}

    return work


def _held_to_the_rule(seen: dict[str, Any], kind: str) -> None:
    endpoint = endpoint_of(seen["base_url"])
    if kind == "--dry-run":
        assert (seen["auth"], seen["key"], seen["subscription"]) == ("api_key", DUMMY_KEY, None)
        assert endpoint.startswith("http://127.0.0.1:")
        require_vendor_endpoint(seen["auth"], endpoint)
        # The control: the subscription the driver used to rehearse with is refused here.
        with pytest.raises(CredentialEndpointError):
            require_vendor_endpoint("subscription", endpoint)
    else:
        assert (seen["auth"], seen["key"], seen["subscription"]) == ("subscription", None, TOKEN)
        assert endpoint == "default"
        require_vendor_endpoint(seen["auth"], endpoint)


def _prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: Any, kind: str
) -> tuple[Path, Path]:  # noqa: ANN401
    """Clean credential variables, an env file, a stand-in binary; a dry run reads no env file."""
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / "env"
    env_file.write_text(f"CLAUDE_CODE_OAUTH_TOKEN={TOKEN}\n")
    if kind == "--dry-run":

        def read(path: Path) -> str:
            msg = f"the dry run read the env file {path}"
            raise AssertionError(msg)

        monkeypatch.setattr(module, "load_token", read)
    if hasattr(module, "claude_binary"):
        monkeypatch.setattr(module, "claude_binary", lambda: sys.executable)
    criteria = tmp_path / "criteria.txt"
    criteria.write_text("criteria for a stand-in run\n")
    return env_file, criteria


def _main(monkeypatch: pytest.MonkeyPatch, main: Callable[[], object], *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["driver.py", *argv])
    main()


def _nothing_left(module: Any) -> None:  # noqa: ANN401
    assert os.environ.get("ANTHROPIC_API_KEY") is None
    assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") is None
    assert module.AUTH == "subscription"


@pytest.mark.parametrize("kind", KINDS)
def test_the_first_control_and_firmware_run_s_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    env_file, criteria = _prepare(tmp_path, monkeypatch, roles, kind)
    monkeypatch.setattr(roles, "binary_version", lambda: "2.1.301")
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(roles, "one_run", _work(seen, lambda: roles.params()["auth"]))
    out = tmp_path / "out"
    _main(
        monkeypatch,
        roles.main,
        kind,
        "--criteria",
        str(criteria),
        "--out",
        str(out),
        "--env-file",
        str(env_file),
    )
    (found,) = seen
    _held_to_the_rule(found, kind)
    _nothing_left(roles)
    capsys.readouterr()


@pytest.mark.parametrize("kind", KINDS)
def test_the_paired_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    # What the paired driver points the first run's driver at, restored afterwards.
    for name in ("CONTROL_SPEC", "BRIEF", "params", "FIRMWARE_PROPOSAL", "FIRMWARE_SPEC"):
        monkeypatch.setattr(roles, name, getattr(roles, name))
    for name in ("INTERFACE", "command", "RUN_ID"):
        monkeypatch.setattr(roles, name, getattr(roles, name))
    env_file, criteria = _prepare(tmp_path, monkeypatch, roles, kind)
    monkeypatch.setattr(paired, "binary_version", lambda: "2.1.301")
    monkeypatch.setattr(paired, "claude_binary", lambda: sys.executable)
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(paired, "paired", _work(seen, lambda: paired.params()["auth"]))
    python = str(Path(sys.base_prefix) / "bin" / "python3")
    out = tmp_path / "out"
    _main(
        monkeypatch,
        paired.main,
        "paired",
        kind,
        *("--criteria", str(criteria), "--out", str(out), "--env-file", str(env_file)),
        *("--role-python", python),
    )
    (found,) = seen
    _held_to_the_rule(found, kind)
    _nothing_left(paired)
    capsys.readouterr()


@pytest.mark.parametrize("kind", KINDS)
def test_the_rerun_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    env_file, criteria = _prepare(tmp_path, monkeypatch, rerun, kind)
    monkeypatch.setattr(rerun, "binary_version", lambda: "2.1.301")
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(rerun, "both_runs", _work(seen, lambda: rerun.params()["auth"]))
    out = tmp_path / "out"
    _main(
        monkeypatch,
        rerun.main,
        kind,
        "--criteria",
        str(criteria),
        "--out",
        str(out),
        "--env-file",
        str(env_file),
    )
    (found,) = seen
    _held_to_the_rule(found, kind)
    _nothing_left(rerun)
    capsys.readouterr()


@pytest.mark.parametrize("kind", KINDS)
def test_the_spot_check_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    env_file, _ = _prepare(tmp_path, monkeypatch, spot_check, kind)
    monkeypatch.setattr(spot_check, "binary_version", lambda: "2.1.301")
    monkeypatch.setattr(spot_check, "prepare_install", lambda install, root: None)
    monkeypatch.setattr(spot_check, "verdict", lambda checks, variant: (False, []))
    seen: list[dict[str, Any]] = []

    def cycle(root: Path, variant: str, env: dict[str, str], *_: object) -> dict[str, Any]:
        # The sessions' own processes get this environment, not this process's.
        seen.append(
            {
                "auth": spot_check.params()["auth"],
                "key": env.get("ANTHROPIC_API_KEY"),
                "subscription": env.get("CLAUDE_CODE_OAUTH_TOKEN"),
                "base_url": env.get("ANTHROPIC_BASE_URL"),
            }
        )
        return {}

    monkeypatch.setattr(spot_check, "run_cycle", cycle)
    out = tmp_path / "out"
    _main(
        monkeypatch,
        spot_check.main,
        "--variant",
        "a",
        kind,
        "--out",
        str(out),
        "--env-file",
        str(env_file),
    )
    (found,) = seen
    _held_to_the_rule(found, kind)
    _nothing_left(spot_check)
    capsys.readouterr()


@pytest.mark.parametrize("kind", KINDS)
def test_the_instrument_pilot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    env_file, _ = _prepare(tmp_path, monkeypatch, pilot, kind)
    monkeypatch.setattr(pilot, "request_defaults", lambda requests, version: {})
    seen: list[dict[str, Any]] = []

    def command(argv: list[str], registrations: object) -> int:
        # The parameters file the instrument's command is given, read as the command reads it.
        params = json.loads(Path(argv[argv.index("--params") + 1]).read_text())
        seen.append(_seen(params["auth"]))
        return 0

    monkeypatch.setattr(pilot, "physgate_main", command)
    out = tmp_path / "out"
    argv = [kind, "--out", str(out), "--env-file", str(env_file)]
    assert pilot.main(argv, binary_check=lambda: pilot.PILOT_VERSION) == 0
    (found,) = seen
    _held_to_the_rule(found, kind)
    _nothing_left(pilot)
    capsys.readouterr()


@pytest.mark.parametrize("kind", KINDS)
def test_the_second_domain_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    env_file, criteria = _prepare(tmp_path, monkeypatch, domain_reviewers, kind)
    monkeypatch.setattr(domain_reviewers, "version_of", lambda binary: "2.1.301")
    seen: list[dict[str, Any]] = []

    def reviews(root: Path, credential: Any, base_url: str | None, only: object) -> dict[str, Any]:  # noqa: ANN401
        # The credential the reviewers are built with goes to them in their setup.
        variable = (
            "ANTHROPIC_API_KEY" if credential.mode == "api_key" else "CLAUDE_CODE_OAUTH_TOKEN"
        )
        monkeypatch.setenv(variable, credential.secret)
        seen.append(_seen(credential.mode, base_url))
        monkeypatch.delenv(variable)
        return {}

    monkeypatch.setattr(domain_reviewers, "reviews", reviews)
    out = tmp_path / "out"
    _main(
        monkeypatch,
        domain_reviewers.main,
        "reviews",
        kind,
        *("--criteria", str(criteria), "--out", str(out), "--env-file", str(env_file)),
    )
    (found,) = seen
    _held_to_the_rule(found, kind)
    assert os.environ.get("ANTHROPIC_API_KEY") is None
    assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") is None
    capsys.readouterr()
