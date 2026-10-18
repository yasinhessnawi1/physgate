"""The Claude Code engine: the binary's headless mode, with the vendor's API or another endpoint.

It holds the run's credential and endpoint and turns them, with what the caller decided for a
session, into the binary's command line and an environment built from nothing
(``invocation``), with the credential where the binary reads it (``credentials``): an API key
through a helper script the hook layer's settings name, a subscription as the binary's own
login file. A subscription is delivered only to the vendor's own endpoint: no engine is built
for any other. It reads the stream the binary wrote (``stream``), takes the structured answer
and the account from its result, stops the session's whole tree, and says which layers hold
around each profile (``layers``).
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

from physgate.engines.base import (
    Captured,
    EngineRecord,
    Launch,
    LayersHeld,
    ModelIdentity,
    Profile,
    Started,
)
from physgate.engines.claude_code.layers import layers_held
from physgate.engines.claude_code.stream import read_captured
from physgate.orchestrator.accounting import require_matching_totals
from physgate.orchestrator.credentials import (
    VENDOR_ENDPOINTS,
    Credential,
    remove_secrets,
    require_vendor_endpoint,
    write_key_helper,
    write_login,
)
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.invocation import (
    REVIEWER_ENV,
    decomposition_argv,
    isolated_env,
    reviewer_argv,
    role_argv,
)
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.run_config import endpoint_of
from physgate.orchestrator.session_files import redact
from physgate.oslayer.probe import Absent, Present
from physgate.reviewers.ending import SessionEnd, await_session

#: The harness's register name, as a run records it.
HARNESS = "claude-code"
#: The vendor behind the default endpoint, and the provider every other endpoint is recorded
#: as until a provider of its own is registered for it.
VENDOR = "anthropic"
UNREGISTERED = "unregistered"


class ClaudeCodeEngine:
    """Claude Code with one credential and one endpoint: the engine every session here runs on."""

    def __init__(self, *, base_url: str | None, credential: Credential) -> None:
        """Run sessions against ``base_url`` (the binary's default if unset) with ``credential``.

        Raises:
            CredentialEndpointError: a subscription, with an endpoint not its vendor's own.
            RunConfigError: ``base_url`` is not an http(s) URL with a host.
        """
        endpoint = endpoint_of(base_url)
        # A subscription only to its vendor's own endpoint: no engine exists for another.
        require_vendor_endpoint(credential.mode, endpoint)
        self._base_url = base_url
        self._credential = credential
        self._endpoint = endpoint

    @property
    def endpoint(self) -> str:
        """Where the sessions' model calls go, as a run records it."""
        return self._endpoint

    @property
    def provider(self) -> str:
        """The vendor at its own endpoint; any other endpoint's provider is not registered."""
        return VENDOR if self._endpoint in VENDOR_ENDPOINTS else UNREGISTERED

    def credential_settings(self, state_dir: Path) -> tuple[str, ...]:
        """An API key's helper script, written into ``state_dir``, for the settings to name.

        A subscription names nothing here: its login is written when the session starts.
        """
        if self._credential.mode != "api_key":
            return ()
        helper = write_key_helper(state_dir, self._credential.secret)
        return ("--api-key-helper", str(helper))

    def start(self, launch: Launch) -> Started:
        """The binary's command line and environment for ``launch``, its login written first.

        A role and a reviewer session take the hook layer's spawn arguments and environment;
        a reviewer's environment also switches compaction off. The decomposition call takes
        an API key in its environment, since it runs under no settings that name a helper.
        """
        if self._credential.mode == "subscription":
            write_login(launch.config_dir, self._credential.secret, endpoint=self._endpoint)
        env = isolated_env(
            home=launch.home,
            config_dir=launch.config_dir,
            binary=launch.binary,
            claude_version=launch.version,
            max_retries=launch.max_retries,
            max_output_tokens=launch.max_output_tokens,
            base_url=self._base_url,
            api_key=(
                self._credential.secret
                if launch.kind == "decomposition" and self._credential.mode == "api_key"
                else None
            ),
        )
        env.update(launch.spawn_env)
        if launch.kind == "reviewer":
            env.update(REVIEWER_ENV)
        return Started(argv=_argv(launch), env=env)

    def stream(self, path: Path) -> Captured:
        """The stream as the binary wrote it, through its first result."""
        return read_captured(path)

    def verdict(self, captured: Captured) -> object | None:
        """The structured answer the binary put on its result, if any."""
        return (captured.result or {}).get("structured_output")

    def cost(self, captured: Captured) -> tuple[MessageUsage, ...]:
        """Each message's final usage, held to the totals on the binary's result."""
        require_matching_totals(captured.result, captured.usage)
        return captured.usage

    def stop(
        self, process: subprocess.Popen[bytes], started: str | None, wall_clock_s: float
    ) -> SessionEnd:
        """Wait within the wall clock, then stop the session's whole tree."""
        return await_session(process, started, wall_clock_s)

    def release(self, state_dir: Path, config_dir: Path, stream: Path | None) -> None:
        """Remove the credential's files, whichever mode wrote them; redact it from ``stream``."""
        remove_secrets(state_dir, config_dir)
        if stream is not None:
            redact(stream, self._credential.secret)

    def layers(
        self,
        profile: Profile,
        *,
        version: str,
        os_layer: Present | Absent,
        enforcement_tree: str,
    ) -> LayersHeld:
        """Which layers hold around ``profile``'s sessions on ``version`` (``layers``)."""
        return layers_held(
            profile, version=version, os_layer=os_layer, enforcement_tree=enforcement_tree
        )

    def record(
        self,
        *,
        version: str,
        models: Iterable[str],
        os_layer: Present | Absent,
        enforcement_tree: str,
    ) -> EngineRecord:
        """The engine as a run records it, for ``version`` and every model string it sends."""
        provider = self.provider
        return EngineRecord(
            harness=HARNESS,
            version=version,
            provider=provider,
            endpoint=self._endpoint,
            models=tuple(
                ModelIdentity(
                    request_name=name,
                    provider=provider,
                    # At the vendor's own endpoint a model string names the vendor's model;
                    # behind any other endpoint, any model may answer to it.
                    identity=f"{VENDOR}/{name}" if provider == VENDOR else None,
                )
                for name in sorted(set(models))
            ),
            role=self.layers(
                "role", version=version, os_layer=os_layer, enforcement_tree=enforcement_tree
            ),
            reviewer=self.layers(
                "reviewer", version=version, os_layer=os_layer, enforcement_tree=enforcement_tree
            ),
        )


def _argv(launch: Launch) -> list[str]:
    """The binary's command line for one session of ``launch``'s kind."""
    if launch.kind == "decomposition":
        if launch.schema is None or launch.settings is None or launch.debug_file is None:
            msg = "the decomposition call names its schema, its settings and its debug log"
            raise InvocationError(msg, kind=launch.kind)
        return decomposition_argv(
            launch.binary,
            prompt=launch.prompt,
            schema=launch.schema,
            model=launch.model,
            session_id=launch.session_id,
            settings=launch.settings,
            effort=launch.effort,
            debug_file=launch.debug_file,
        )
    if launch.kind == "reviewer":
        if launch.schema is None:
            msg = "a reviewer session names the schema its verdict is held to"
            raise InvocationError(msg, kind=launch.kind)
        return reviewer_argv(
            launch.binary,
            prompt=launch.prompt,
            spawn_args=launch.spawn_args,
            schema=launch.schema,
            model=launch.model,
            session_id=launch.session_id,
            max_turns=launch.max_turns,
            effort=launch.effort,
        )
    if launch.thinking_display is None:
        msg = "a role session names how its reasoning appears in its stream"
        raise InvocationError(msg, kind=launch.kind)
    return role_argv(
        launch.binary,
        prompt=launch.prompt,
        spawn_args=launch.spawn_args,
        model=launch.model,
        session_id=launch.session_id,
        max_turns=launch.max_turns,
        effort=launch.effort,
        thinking_display=launch.thinking_display,
    )
