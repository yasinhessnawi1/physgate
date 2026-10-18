"""The held-out tier and the network are recorded run parameters that reach every session.

A run names its held-out roots, the held-out tasks' canaries and whether role sessions'
shell commands may reach the network; each is required, recorded in ``run.json`` and
part of the run's digest when set, and a run recorded before the fields existed reads
back as nothing held out and the network open, with its digest unchanged. Every role
session and every reviewer is installed with each held-out root, and a role session
running inside the OS layer is taken offline when the run asks for it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orch_helpers import SCRIPTED_BOUNDS, make_config
from pydantic import ValidationError

from physgate.orchestrator import dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.oslayer.probe import Absent, Present

CANARY = "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize("name", ["held_out", "held_out_canaries", "held_out_sha256", "network"])
def test_each_is_a_required_parameter(name: str) -> None:
    fields = json.loads(make_config().model_dump_json())
    del fields[name]
    with pytest.raises(ValidationError):
        RunConfig.model_validate_json(json.dumps(fields))


def test_set_they_are_recorded_and_part_of_the_digest() -> None:
    plain = make_config()
    held = make_config(held_out=("/elsewhere/heldout",), held_out_canaries=(CANARY,))
    offline = make_config(network="none")
    assert b'"held_out":["/elsewhere/heldout"]' in held.canonical_bytes()
    assert CANARY.encode() in held.canonical_bytes()
    assert b'"network":"none"' in offline.canonical_bytes()
    assert len({plain.sha256(), held.sha256(), offline.sha256()}) == 3


def test_unset_they_leave_the_recorded_bytes_as_they_were() -> None:
    raw = make_config().canonical_bytes()
    for name in (b"held_out", b"held_out_canaries", b"network"):
        assert name not in raw


def test_a_run_recorded_before_the_fields_reads_as_nothing_held_out_and_open(
    tmp_path: Path,
) -> None:
    recorded = make_config()
    (tmp_path / "run.json").write_bytes(recorded.canonical_bytes())
    loaded = load_run_config(tmp_path / "run.json")
    assert (loaded.held_out, loaded.held_out_canaries, loaded.network) == ((), (), "open")
    assert loaded.sha256() == recorded.sha256()


@pytest.mark.parametrize(
    "change",
    [
        {"held_out": ("relative/heldout",)},
        {"held_out_canaries": ("not-a-canary",)},
        {"network": "proxied"},
    ],
    ids=["relative root", "malformed canary", "unknown network"],
)
def test_a_malformed_value_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_config(**change)


def _dispatcher(tmp_path: Path, **config: Any) -> ClaudeDispatcher:  # noqa: ANN401
    return ClaudeDispatcher(
        config=make_config(**config),
        run=SimpleNamespace(subtask_branch=lambda subtask: f"b/{subtask}"),  # type: ignore[arg-type]
        store_root=tmp_path / "store",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=tmp_path / "reviews",
    )


def test_a_held_out_canary_in_a_session_s_stream_is_found(tmp_path: Path) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.write_text('{"type":"user","content":"... ' + CANARY + ' ..."}\n')
    clean = tmp_path / "clean.jsonl"
    clean.write_text('{"type":"user","content":"nothing here"}\n')
    assert _dispatcher(tmp_path, held_out_canaries=(CANARY,)).held_out_seen(stream) == CANARY
    assert _dispatcher(tmp_path, held_out_canaries=(CANARY,)).held_out_seen(clean) is None
    assert _dispatcher(tmp_path).held_out_seen(stream) is None


def _install_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, temp: Path | None, **config: Any
) -> list[str]:
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
    monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
    dispatcher = ClaudeDispatcher(
        config=make_config(**config),
        run=SimpleNamespace(subtask_branch=lambda subtask: f"b/{subtask}"),  # type: ignore[arg-type]
        store_root=tmp_path / "store",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=tmp_path / "reviews",
    )
    request = SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role="control",
        spec_path=".physgate/specs/s1.md",
        module_dir="modules/control",
        model="claude-opus-5-5",
        repair_instruction=None,
        bounds=SCRIPTED_BOUNDS,
    )
    sdir = tmp_path / f"sdir-{len(list(tmp_path.glob('sdir-*')))}"
    dispatcher._install(request, tmp_path / "worktree", sdir, temp)
    return seen[0]


def _values(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == flag]


def test_every_role_session_is_installed_with_every_held_out_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = ("/elsewhere/heldout-a", "/elsewhere/heldout-b")
    argv = _install_argv(tmp_path, monkeypatch, temp=None, held_out=roots)
    assert _values(argv, "--held-out") == list(roots)


def test_a_role_session_inside_the_os_layer_is_taken_offline_when_the_run_asks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp = Path("/tmp/pg-0123456789ab")
    offline = _install_argv(tmp_path, monkeypatch, temp=temp, network="none")
    assert _values(offline, "--os-layer-network") == ["none"]
    opened = _install_argv(tmp_path, monkeypatch, temp=temp, network="open")
    assert "--os-layer-network" not in opened
    # Without the layer nothing can take a shell offline; the run records both facts.
    absent = _install_argv(tmp_path, monkeypatch, temp=None, network="none")
    assert "--os-layer-network" not in absent


def test_every_reviewer_is_installed_with_every_held_out_root(tmp_path: Path) -> None:
    from physgate.reviewers.claude import ReviewerSetup

    setup = ReviewerSetup.of_run(
        make_config(held_out=("/elsewhere/heldout",)),
        review_root=tmp_path / "rs",
        repo=tmp_path / "target",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=tmp_path / "harness",
    )
    assert setup.held_out == ("/elsewhere/heldout",)


def test_a_reviewer_s_session_is_installed_with_every_held_out_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.reviewers import claude
    from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
    from physgate.reviewers.rubric import Rubric

    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(claude, "harness_protection", lambda: [])
    setup = ReviewerSetup.of_run(
        make_config(held_out=("/elsewhere/heldout",)),
        review_root=tmp_path / "rs",
        repo=tmp_path / "target",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=tmp_path / "harness",
    )
    reviewer = ClaudeReviewer(
        role="electrical", setup=setup, rubric=Rubric(role="electrical", text="r", sha256="0" * 64)
    )
    packet = SimpleNamespace(read_root=str(tmp_path / "packet"), required_reading=())
    sdir = tmp_path / "review"
    sdir.mkdir()
    reviewer._install(packet, sdir)  # type: ignore[arg-type]
    assert _values(seen[0], "--held-out") == ["/elsewhere/heldout"]


ABSENT = Absent(reason="stand-in: no sandbox here")
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")


def test_none_where_no_os_layer_runs_is_recorded_in_the_manifest_never_silently() -> None:
    """Only the OS layer takes a shell offline: without it ``none`` is recorded as unenforced."""
    unenforced = make_config(network="none", os_layer=ABSENT, network_enforced=False)
    assert b'"network_enforced":false' in unenforced.canonical_bytes()
    enforced = make_config(network="none", os_layer=PRESENT, network_enforced=True)
    assert enforced.sha256() != unenforced.sha256()
    for silent in (
        {"network": "none", "os_layer": ABSENT},  # not said at all
        {"network": "none", "os_layer": ABSENT, "network_enforced": True},  # said wrongly
        {"network": "none", "os_layer": PRESENT, "network_enforced": False},
        {"network": "open", "os_layer": ABSENT, "network_enforced": False},  # nothing asked
    ):
        with pytest.raises(ValidationError, match="network"):
            make_config(**silent)


def test_whether_none_is_enforced_is_measured_never_taken_from_the_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    import physgate.orchestrator.cli as cli

    monkeypatch.setattr(cli, "binary_version", lambda: "2.1.301")
    monkeypatch.setattr(cli, "head_of", lambda *_: "c" * 40)
    monkeypatch.setattr(cli, "judge_here", lambda **_: ABSENT)
    monkeypatch.setattr(cli, "claude_binary", lambda: "/nonexistent/claude")
    recorded = json.loads(make_config().model_dump_json())
    measured: tuple[str, ...] = (
        "run_id",
        "seed",
        "brief_sha256",
        "target_head",
        "claude_version",
        "endpoint",
    )
    measured += ("harness", "git_binary", "os_layer")
    params = {k: v for k, v in recorded.items() if k not in measured}
    params |= {"network": "none", "network_enforced": True}  # a claim, overruled
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_text("brief\n")
    args = argparse.Namespace(
        params=tmp_path / "params.json",
        brief=tmp_path / "brief.md",
        run_id="run-1",
        seed=7,
        target=tmp_path,
    )
    assert cli._config(args).network_enforced is False


def test_none_where_no_os_layer_runs_is_said_on_stderr_and_in_the_run_s_event(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import UTC, datetime

    from physgate.orchestrator import cli
    from physgate.orchestrator.common import utc_stamp
    from physgate.orchestrator.events import Envelope
    from physgate.oslayer.policy import NETWORK_UNENFORCED

    stamp = utc_stamp(datetime(2026, 10, 17, tzinfo=UTC))
    envelope = Envelope(seq=0, ts=stamp, run_id="run-1", gate_mode="on")
    offline = make_config(network="none", os_layer=ABSENT, network_enforced=False)
    cli._say_os_layer(ABSENT, offline.network)
    assert NETWORK_UNENFORCED in capsys.readouterr().err
    assert cli._os_layer_checked(envelope, offline, ABSENT).network_enforced is False
    assert cli._os_layer_checked(envelope, offline, PRESENT).network_enforced is True
    for layer, network in ((PRESENT, "none"), (ABSENT, "open")):
        cli._say_os_layer(layer, network)  # type: ignore[arg-type]
        assert NETWORK_UNENFORCED not in capsys.readouterr().err
    assert cli._os_layer_checked(envelope, make_config(), ABSENT).network_enforced is None


def test_an_offline_run_records_the_services_listening_on_loopback_at_its_start(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import UTC, datetime

    from physgate.orchestrator import cli
    from physgate.orchestrator.common import utc_stamp
    from physgate.orchestrator.events import Envelope

    stamp = utc_stamp(datetime(2026, 10, 18, tzinfo=UTC))
    envelope = Envelope(seq=0, ts=stamp, run_id="run-1", gate_mode="on")
    offline = make_config(network="none", os_layer=PRESENT, network_enforced=True)
    event = cli._os_layer_checked(envelope, offline, PRESENT, listening=lambda: (631, 8811))
    assert event.loopback_listeners == (631, 8811)
    unread = cli._os_layer_checked(envelope, offline, PRESENT, listening=lambda: None)
    assert unread.loopback_listeners is None and unread.loopback_listeners_read is False
    # An open run reads nothing: the record is about what an offline session is kept from.
    calls: list[int] = []
    opened = cli._os_layer_checked(
        envelope, make_config(), PRESENT, listening=lambda: calls.append(1) or ()
    )
    assert calls == [] and opened.loopback_listeners is None
    cli._say_listeners(offline.network, (631, 8811))
    assert "2 services listen on this machine's loopback" in capsys.readouterr().err


DIGEST = "d" * 64


def test_each_held_out_root_is_recorded_with_its_digest_and_the_digest_is_in_the_run_s_id() -> None:
    held = make_config(held_out=("/elsewhere/heldout",), held_out_sha256=(DIGEST,))
    other = make_config(held_out=("/elsewhere/heldout",), held_out_sha256=("e" * 64,))
    assert b'"held_out_sha256":["' + DIGEST.encode() + b'"]' in held.canonical_bytes()
    assert held.sha256() != other.sha256()
    assert b"held_out_sha256" not in make_config().canonical_bytes()


@pytest.mark.parametrize(
    "change",
    [
        {"held_out": ("/elsewhere/heldout",), "held_out_sha256": ()},
        {"held_out": (), "held_out_sha256": (DIGEST,)},
        {"held_out": ("/a", "/b"), "held_out_sha256": (DIGEST,)},
        {"held_out": ("/elsewhere/heldout",), "held_out_sha256": ("not-a-digest",)},
    ],
    ids=["a root without its digest", "a digest without a root", "one short", "malformed"],
)
def test_a_root_and_its_digest_come_in_pairs(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_config(**change)


def test_a_run_recorded_before_the_digest_reads_as_none_with_its_id_unchanged(
    tmp_path: Path,
) -> None:
    recorded = make_config()
    (tmp_path / "run.json").write_bytes(recorded.canonical_bytes())
    loaded = load_run_config(tmp_path / "run.json")
    assert loaded.held_out_sha256 == ()
    assert loaded.sha256() == recorded.sha256()
