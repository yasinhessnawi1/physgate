"""A session's harness side goes through one engine, and starts exactly as it did before.

The engine interface names no harness and no vendor, and the places that run a session (the
dispatcher, the reviewer, the decomposition call) build no command line, no environment and
no credential file of their own: they ask the engine. The Claude Code engine gives each kind
of session exactly the command line and the environment the binary's own builders give, its
credential where the binary reads it and nowhere else, and it says which layers hold around
each profile with the measurement behind every claim.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

from physgate.engines.base import Captured, Launch, LayersHeld
from physgate.engines.claude_code import HARNESS, ClaudeCodeEngine
from physgate.engines.claude_code.layers import HOOK_EVIDENCE, REVIEWER_HAS_NO_SHELL
from physgate.orchestrator.credentials import KEY_FILE, KEY_HELPER, LOGIN_FILE, Credential
from physgate.orchestrator.exceptions import AccountingError, CredentialEndpointError
from physgate.orchestrator.invocation import (
    PINNED_VERSIONS,
    REVIEWER_ENV,
    decomposition_argv,
    isolated_env,
    reviewer_argv,
    role_argv,
)
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.trajectory import seal
from physgate.oslayer.probe import Absent, Present

SRC = Path(__file__).resolve().parents[3] / "src" / "physgate"
KEY = "sk-ant-test-dummy-not-a-credential"
TOKEN = "sk-ant-oat01-test-dummy-not-a-credential"
SCRIPTED = "http://127.0.0.1:53817"
PRESENT = Present(mechanism="bubblewrap", claude_version="2.1.301")
ABSENT = Absent(reason="stand-in: no sandbox here")

#: Every harness and vendor a core module must not name.
HARNESS_AND_VENDOR_NAMES = re.compile(
    r"claude|anthropic|codex|cursor|deepseek|opencode|hermes|gemini|antigravity|openai|"
    r"openrouter|\bxai\b|grok",
    re.IGNORECASE,
)

#: What builds a session's start or takes its credential away: the engine's alone.
START_AND_CREDENTIAL = {
    "isolated_env",
    "role_argv",
    "reviewer_argv",
    "decomposition_argv",
    "write_login",
    "write_key_helper",
    "remove_secrets",
}
#: What reads a session's stream, its account, and stops it: the engine's alone.
STREAM_COST_STOP = {"read_captured", "require_matching_totals", "await_session", "redact"}


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.name for alias in node.names}
            names.add(f"module:{node.module}")
        elif isinstance(node, ast.Import):
            names |= {f"module:{alias.name}" for alias in node.names}
    return names


def test_the_engine_interface_names_no_harness_and_no_vendor() -> None:
    path = SRC / "engines" / "base.py"
    assert HARNESS_AND_VENDOR_NAMES.findall(path.read_text()) == []
    modules = {n for n in _imported_names(path) if n.startswith("module:")}
    assert modules, "the interface's imports were not read"
    assert not {m for m in modules if m.startswith("module:physgate.engines.")}


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [
        ("orchestrator/dispatch.py", START_AND_CREDENTIAL | STREAM_COST_STOP),
        ("reviewers/claude.py", START_AND_CREDENTIAL | STREAM_COST_STOP),
        # The decomposition reads its one answer from the bytes it holds in memory, before
        # the redacted copy is written; the engine's stream reader reads the session's file,
        # which would change what the plan says where the answer carries the credential.
        ("orchestrator/decompose.py", START_AND_CREDENTIAL | {"await_session", "redact"}),
    ],
)
def test_a_place_that_runs_a_session_asks_its_engine_for_the_harness_side(
    module: str, forbidden: set[str]
) -> None:
    imported = _imported_names(SRC / module)
    assert "Launch" in imported and "ClaudeCodeEngine" in imported
    assert imported & forbidden == set()


def test_only_the_engine_builds_a_session_s_start_or_its_credential() -> None:
    # Outside the modules that define them, only the engine imports them.
    defining = {"orchestrator/invocation.py", "orchestrator/credentials.py"}
    builders = {"isolated_env", "role_argv", "reviewer_argv", "decomposition_argv"}
    builders |= {"write_login", "write_key_helper"}
    found = {
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if str(path.relative_to(SRC)) not in defining and _imported_names(path) & builders
    }
    assert found == {"engines/claude_code/engine.py"}


def _engine(mode: str = "api_key", base_url: str | None = None) -> ClaudeCodeEngine:
    secret = KEY if mode == "api_key" else TOKEN
    return ClaudeCodeEngine(base_url=base_url, credential=Credential(mode, secret))  # type: ignore[arg-type]


def _launch(tmp_path: Path, kind: str, **extra: object) -> Launch:
    fields: dict[str, object] = {
        "kind": kind,
        "binary": "/opt/bin/claude",
        "version": "2.1.301",
        "prompt": "p",
        "model": "claude-sonnet-5",
        "session_id": "s-1",
        "home": tmp_path / "home",
        "config_dir": tmp_path / "config",
        "max_retries": 0,
        "max_output_tokens": 64000,
        "effort": "high",
        "max_turns": 20,
        "spawn_args": ("--settings", "/x/settings.json"),
        "spawn_env": {"PHYSGATE_HOOK": "1"},
        **extra,
    }
    return Launch(**fields)  # type: ignore[arg-type]


def _env(tmp_path: Path, base_url: str | None, api_key: str | None) -> dict[str, str]:
    return isolated_env(
        home=tmp_path / "home",
        config_dir=tmp_path / "config",
        binary="/opt/bin/claude",
        claude_version="2.1.301",
        max_retries=0,
        max_output_tokens=64000,
        base_url=base_url,
        api_key=api_key,
    )


@pytest.mark.parametrize("base_url", [None, SCRIPTED])
def test_a_role_session_starts_as_the_binary_s_own_builders_start_it(
    tmp_path: Path, base_url: str | None
) -> None:
    launch = _launch(tmp_path, "role", thinking_display="summarized")
    started = _engine(base_url=base_url).start(launch)
    assert started.env == {**_env(tmp_path, base_url, None), "PHYSGATE_HOOK": "1"}
    assert started.argv == role_argv(
        "/opt/bin/claude",
        prompt="p",
        spawn_args=launch.spawn_args,
        model="claude-sonnet-5",
        session_id="s-1",
        max_turns=20,
        effort="high",
        thinking_display="summarized",
    )
    assert KEY not in json.dumps(started.env) and not (tmp_path / "config").exists()


def test_a_reviewer_session_starts_with_compaction_off_and_its_schema(tmp_path: Path) -> None:
    launch = _launch(tmp_path, "reviewer", schema='{"type":"object"}')
    started = _engine(base_url=SCRIPTED).start(launch)
    assert started.env == {**_env(tmp_path, SCRIPTED, None), "PHYSGATE_HOOK": "1", **REVIEWER_ENV}
    assert started.argv == reviewer_argv(
        "/opt/bin/claude",
        prompt="p",
        spawn_args=launch.spawn_args,
        schema='{"type":"object"}',
        model="claude-sonnet-5",
        session_id="s-1",
        max_turns=20,
        effort="high",
    )


def test_the_decomposition_call_carries_a_key_in_its_environment_and_nothing_else(
    tmp_path: Path,
) -> None:
    launch = _launch(
        tmp_path,
        "decomposition",
        spawn_args=(),
        spawn_env={},
        schema="{}",
        settings=tmp_path / "settings.json",
        debug_file=tmp_path / "debug.log",
    )
    started = _engine(base_url=SCRIPTED).start(launch)
    assert started.env == _env(tmp_path, SCRIPTED, KEY)
    assert started.argv == decomposition_argv(
        "/opt/bin/claude",
        prompt="p",
        schema="{}",
        model="claude-sonnet-5",
        session_id="s-1",
        settings=tmp_path / "settings.json",
        effort="high",
        debug_file=tmp_path / "debug.log",
    )


@pytest.mark.parametrize("kind", ["role", "reviewer", "decomposition"])
def test_a_subscription_at_the_vendor_s_endpoint_is_a_login_file_and_never_in_the_environment(
    tmp_path: Path, kind: str
) -> None:
    launch = _launch(
        tmp_path,
        kind,
        thinking_display="summarized",
        schema="{}",
        settings=tmp_path / "settings.json",
        debug_file=tmp_path / "debug.log",
    )
    started = _engine("subscription").start(launch)
    assert TOKEN not in json.dumps(started.env) and TOKEN not in " ".join(started.argv)
    assert "ANTHROPIC_API_KEY" not in started.env and "ANTHROPIC_BASE_URL" not in started.env
    login = json.loads((tmp_path / "config" / LOGIN_FILE).read_text())
    assert login["claudeAiOauth"]["accessToken"] == TOKEN


@pytest.mark.parametrize(
    "base_url", [SCRIPTED, "https://api.deepseek.com/anthropic", "https://openrouter.ai/api"]
)
def test_no_engine_carries_a_subscription_to_an_endpoint_that_is_not_its_vendor_s(
    tmp_path: Path, base_url: str
) -> None:
    # Refused when the engine is built, so no session's environment is ever built for it.
    with pytest.raises(CredentialEndpointError):
        _engine("subscription", base_url)
    # The same endpoint with a key is an engine, and its sessions carry no subscription.
    started = _engine("api_key", base_url).start(_launch(tmp_path, "role", thinking_display="x"))
    assert TOKEN not in json.dumps(started.env)
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_a_key_reaches_a_session_through_a_helper_its_settings_name(tmp_path: Path) -> None:
    named = _engine().credential_settings(tmp_path)
    assert named == ("--api-key-helper", str(tmp_path / KEY_HELPER))
    assert (tmp_path / KEY_FILE).read_text() == KEY
    assert _engine("subscription").credential_settings(tmp_path / "other") == ()
    assert not (tmp_path / "other").exists()


def test_a_released_session_holds_no_credential_and_its_stream_none(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sdir = sessions / "s-1"
    (sdir / "state").mkdir(parents=True)
    engine = _engine()
    engine.credential_settings(sdir / "state")
    (sdir / "stdout.jsonl").write_text(f"the key is {KEY}\n")
    engine.release(sdir / "state", sdir / "config", sdir / "stdout.jsonl")
    assert not (sdir / "state" / KEY_FILE).exists() and not (sdir / "state" / KEY_HELPER).exists()
    assert KEY not in (sdir / "stdout.jsonl").read_text()


def _captured(result: dict[str, Any] | None, output_tokens: int) -> Captured:
    usage = Usage(
        input_tokens=5, output_tokens=output_tokens, cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )  # fmt: skip
    return Captured(
        seal=seal(b""),
        tampered=None,
        result=result,
        usage=(MessageUsage(message_id="m1", usage=usage),),
        answered=frozenset({"claude-sonnet-5"}),
    )


def test_the_verdict_is_the_structured_answer_and_the_account_is_held_to_the_totals() -> None:
    totals = {"claude-sonnet-5": {"inputTokens": 5, "outputTokens": 9}}
    result = {"type": "result", "structured_output": {"verdict": "pass"}, "modelUsage": totals}
    engine = _engine()
    assert engine.verdict(_captured(result, 9)) == {"verdict": "pass"}
    assert engine.verdict(_captured(None, 9)) is None
    assert engine.cost(_captured(result, 9)) == _captured(result, 9).usage
    with pytest.raises(AccountingError):
        engine.cost(_captured(result, 8))


#: The hook package's tree R-HK-03 measured, and another, standing for code changed since.
MEASURED = HOOK_EVIDENCE["2.1.301"].enforcement_tree
CHANGED = "0" * 40


def test_a_role_s_layers_follow_the_os_layer_and_a_reviewer_runs_no_shell() -> None:
    engine = _engine()
    role = engine.layers("role", version="2.1.301", os_layer=PRESENT, enforcement_tree=MEASURED)
    assert (role.os_layer, role.os_layer_reason) == ("harness_sandbox", None)
    assert (role.closed_tool_list, role.verdict_schema) == ("hook", "absent")
    off = engine.layers("role", version="2.1.301", os_layer=ABSENT, enforcement_tree=MEASURED)
    assert (off.os_layer, off.os_layer_reason) == ("absent", ABSENT.reason)
    reviewer = engine.layers(
        "reviewer", version="2.1.301", os_layer=PRESENT, enforcement_tree=MEASURED
    )
    assert (reviewer.os_layer, reviewer.os_layer_reason) == ("absent", REVIEWER_HAS_NO_SHELL)
    assert (reviewer.closed_tool_list, reviewer.verdict_schema) == ("both", "native")


@pytest.mark.parametrize("version", sorted(PINNED_VERSIONS))
@pytest.mark.parametrize("profile", ["role", "reviewer"])
def test_the_hooks_are_held_only_on_the_version_and_the_code_a_measurement_names(
    version: str, profile: str
) -> None:
    def layers(tree: str) -> LayersHeld:
        return _engine().layers(profile, version=version, os_layer=PRESENT, enforcement_tree=tree)  # type: ignore[arg-type]

    at_measured, changed = layers(MEASURED), layers(CHANGED)
    assert (at_measured.enforcement_tree, changed.enforcement_tree) == (MEASURED, CHANGED)
    if version in HOOK_EVIDENCE:
        evidence = HOOK_EVIDENCE[version]
        assert (at_measured.pre_exec_hooks, at_measured.hooks_compared_as) == ("held", "held")
        assert at_measured.bypass_evidence == evidence.measurement
        assert re.match(r"^R-[A-Z]+-\d\d: ", evidence.measurement)
        # The same version on other enforcement code: measured, but not on this code.
        assert changed.pre_exec_hooks == "changed_since"
        assert changed.hooks_reading == f"measured at {evidence.enforcement_tree}; changed since"
        assert changed.hooks_compared_as == "unmeasured"
        assert changed.measured_tree == evidence.enforcement_tree
    else:
        for found in (at_measured, changed):
            assert (found.pre_exec_hooks, found.bypass_evidence, found.measured_tree) == (
                "unmeasured",
                None,
                None,
            )
            assert found.hooks_compared_as == "unmeasured"
    # A version outside the pinned set is never measured, so never held.
    outside = _engine().layers(
        "role", version="2.1.999", os_layer=PRESENT, enforcement_tree=MEASURED
    )
    assert outside.pre_exec_hooks == "unmeasured"
    assert set(HOOK_EVIDENCE) <= PINNED_VERSIONS


def test_this_checkout_s_hooks_read_as_changed_since_the_measurement() -> None:
    # The hook package has changed since R-HK-03's commit, so no run on it says "held".
    from physgate.engines.enforcement import enforcement_tree

    here = enforcement_tree()
    assert here != MEASURED
    found = _engine().layers("role", version="2.1.301", os_layer=PRESENT, enforcement_tree=here)
    assert found.hooks_reading == f"measured at {MEASURED}; changed since"


def test_a_claim_without_its_evidence_or_on_other_code_is_not_a_record() -> None:
    held = _engine().layers("role", version="2.1.301", os_layer=PRESENT, enforcement_tree=MEASURED)
    assert held.pre_exec_hooks == "held"
    with pytest.raises(ValueError, match="measurement is named"):
        LayersHeld.model_validate({**held.model_dump(), "bypass_evidence": None})
    with pytest.raises(ValueError, match="measurement is named"):
        LayersHeld.model_validate({**held.model_dump(), "measured_tree": None})
    with pytest.raises(ValueError, match="measurement is named"):
        LayersHeld.model_validate({**held.model_dump(), "pre_exec_hooks": "unmeasured"})
    with pytest.raises(ValueError, match="enforcement code the measurement ran on"):
        LayersHeld.model_validate({**held.model_dump(), "enforcement_tree": CHANGED})
    with pytest.raises(ValueError, match="enforcement code the measurement ran on"):
        LayersHeld.model_validate({**held.model_dump(), "pre_exec_hooks": "changed_since"})
    with pytest.raises(ValueError, match="says why"):
        LayersHeld.model_validate({**held.model_dump(), "os_layer": "absent"})
    with pytest.raises(ValueError, match="names them"):
        LayersHeld.model_validate(
            {**held.model_dump(), "hook_failure": "closed_with_residual", "residuals": ()}
        )


def test_the_record_names_the_harness_the_provider_and_each_model_s_identity() -> None:
    models = ["claude-sonnet-5", "claude-opus-5-5", "claude-sonnet-5"]
    vendor = _engine().record(
        version="2.1.301", models=models, os_layer=PRESENT, enforcement_tree=MEASURED
    )
    assert (vendor.harness, vendor.version, vendor.provider, vendor.endpoint) == (
        HARNESS,
        "2.1.301",
        "anthropic",
        "default",
    )
    assert [(m.request_name, m.identity) for m in vendor.models] == [
        ("claude-opus-5-5", "anthropic/claude-opus-5-5"),
        ("claude-sonnet-5", "anthropic/claude-sonnet-5"),
    ]
    assert vendor.role == _engine().layers(
        "role", version="2.1.301", os_layer=PRESENT, enforcement_tree=MEASURED
    )
    # Behind an endpoint no register names, any model may answer to a string: no identity.
    other = _engine(base_url=SCRIPTED + "/").record(
        version="2.1.272", models=models, os_layer=ABSENT, enforcement_tree=MEASURED
    )
    assert (other.provider, other.endpoint) == ("unregistered", SCRIPTED)
    assert all(m.identity is None and m.provider == "unregistered" for m in other.models)
    assert other.reviewer.pre_exec_hooks == "unmeasured"
