"""The engine interface: one session's start, stream, verdict, cost, stop, and the layers held.

An engine is an agent harness at a pinned version, with a model at a provider and an
endpoint. What runs a session (the dispatcher, a reviewer, the decomposition) holds an
:class:`Engine` and asks it for everything that depends on the harness: how the session is
started and where its credential is put, how its stream is read, what its structured answer
and its account are, how it is stopped and its credential taken away again. What the session
is for, and every check made around it, stays with the caller.

**The layers held.** A run records, per session profile, which of the system's layers hold
around a session on this engine (:class:`LayersHeld`), with the measurement behind each claim.
A layer is recorded as held only where a measurement on this harness version showed it held;
a harness that cannot be held by a layer says so, rather than being listed as if it were.

This module names no harness and no vendor: a test holds it, and every other core module, to
that.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.trajectory import Seal
from physgate.oslayer.probe import Absent, Present
from physgate.reviewers.ending import SessionEnd

#: The kinds of agent session the system runs: a role's, which writes and runs commands,
#: and a reviewer's, which reads and answers once. The layers held are recorded for each.
Profile = Literal["role", "reviewer"]

#: Every kind of session an engine starts: an agent session of a profile, or the run's one
#: decomposition call, which has no tools at all.
SessionKind = Literal["role", "reviewer", "decomposition"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class LayersHeld(_Frozen):
    """Which of the system's layers hold around one profile's sessions on one engine.

    Recorded with every run, so a number names what protected the sessions that produced
    it. A layer the harness cannot hold is recorded as absent; one no measurement on this
    harness version has shown to hold is recorded as unmeasured, never as held.
    """

    #: The pre-execution hooks: held only with the measurement that showed zero reach.
    pre_exec_hooks: Literal["held", "unmeasured", "absent"]
    #: How the hooks see a tool call: through the harness's own tools, through tools the
    #: system provides in their place, or not at all.
    route: Literal["native", "provided_tools", "none"]
    #: What happens when a hook cannot decide: the call is refused (closed), refused with
    #: known exceptions (``residuals``), or let through (open).
    hook_failure: Literal["closed", "closed_with_residual", "open"]
    #: Known gaps in what is held, each with the measurement that found it.
    residuals: tuple[NonEmptyStr, ...]
    #: Who holds the session to its profile's tools: the harness, the hooks, both, nobody.
    closed_tool_list: Literal["harness", "hook", "both", "absent"]
    #: When the sentinel checks the protected roots: after every call, or at the end only.
    sentinel: Literal["per_call", "end_only"]
    #: What runs the session's shell commands inside the operating system's sandbox.
    os_layer: Literal["harness_sandbox", "outside_sandbox", "absent"]
    #: Why the OS layer is absent, when it is.
    os_layer_reason: NonEmptyStr | None
    #: Whether the required reading is enforced before any other call (ARCH-020).
    mandatory_reading: Literal["held", "absent"]
    #: How a structured verdict is held to its schema, if the profile gives one.
    verdict_schema: Literal["native", "provided_tool", "absent"]
    #: What the session's cost is reconciled against: the runtime's own total, the
    #: provider's figure, the tokens priced from a sheet alone, or an estimate.
    cost_basis: Literal["runtime_total", "provider_reported", "priced_from_tokens", "estimate"]
    #: The measurement that showed the hooks held on this harness version: an experiment
    #: and what it ran on. ``None`` unless the hooks are recorded as held.
    bypass_evidence: NonEmptyStr | None

    @model_validator(mode="after")
    def _a_claim_names_its_evidence(self) -> LayersHeld:
        if (self.pre_exec_hooks == "held") != (self.bypass_evidence is not None):
            msg = "hooks are recorded as held exactly when a measurement is named for them"
            raise ValueError(msg)
        if (self.os_layer == "absent") != (self.os_layer_reason is not None):
            msg = "an absent OS layer says why, and a present one gives no reason"
            raise ValueError(msg)
        if self.hook_failure == "closed_with_residual" and not self.residuals:
            msg = "a hook layer closed with residuals names them"
            raise ValueError(msg)
        return self


class ModelIdentity(_Frozen):
    """A model string as a provider is sent it, and the model it is."""

    #: The string the provider is sent.
    request_name: NonEmptyStr
    #: Who serves it.
    provider: NonEmptyStr
    #: The model it is, as ``vendor/model``, when the engine knows the provider; ``None``
    #: for an endpoint it does not know, whose answers may come from any model.
    identity: NonEmptyStr | None


class EngineRecord(_Frozen):
    """The engine a run's sessions ran on, as the run records it (ARCH-145)."""

    #: The agent harness, by its register name.
    harness: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$")]
    #: The harness version every session was held to.
    version: NonEmptyStr
    #: The model provider behind the endpoint.
    provider: NonEmptyStr
    #: Where the sessions' model calls went, as the run records it: never a secret.
    endpoint: NonEmptyStr
    #: Every model string the run sends, with the model it is; sorted, each once.
    models: tuple[ModelIdentity, ...]
    #: The layers held around a role's sessions, and around a reviewer's.
    role: LayersHeld
    reviewer: LayersHeld

    @model_validator(mode="after")
    def _each_model_once_in_order(self) -> EngineRecord:
        names = [m.request_name for m in self.models]
        if names != sorted(set(names)):
            msg = "the record names each model string once, sorted"
            raise ValueError(msg)
        return self


@dataclass(frozen=True)
class Launch:
    """One session to start: what the caller decided, never how the harness is told it.

    ``spawn_args`` and ``spawn_env`` are what the hook layer's installer generated for the
    session; the engine passes them on. A field a session kind does not use is ignored.
    """

    kind: SessionKind
    #: The executable the session runs, and the version it was held to before the start.
    binary: str
    version: str
    prompt: str
    model: str
    session_id: str
    #: The session's scratch home and the harness's configuration directory: its own.
    home: Path
    config_dir: Path
    max_retries: int
    max_output_tokens: int
    effort: str
    #: The run's turn limit; the decomposition's is fixed at one.
    max_turns: int = 1
    spawn_args: tuple[str, ...] = ()
    spawn_env: Mapping[str, str] = field(default_factory=dict)
    #: The JSON schema a structured answer is held to.
    schema: str | None = None
    #: How a role session's reasoning appears in its stream.
    thinking_display: str | None = None
    #: The decomposition's own settings file and debug log.
    settings: Path | None = None
    debug_file: Path | None = None


@dataclass(frozen=True)
class Started:
    """What starts a session: its command line and its environment, built from nothing.

    The caller spawns it, held until its spawn is recorded, as it spawns every session.
    """

    argv: list[str]
    env: dict[str, str]


@dataclass(frozen=True)
class Captured:
    """A session's stream, as read once: sealed, checked, parsed from the same bytes."""

    seal: Seal
    #: Why the stream is not the runtime's alone (a tail after its result), if it is not.
    tampered: str | None
    # The runtime's result object: an untyped boundary, read only by the engine's readers.
    result: dict[str, Any] | None
    usage: tuple[MessageUsage, ...]
    #: Every model named as answering in the stream.
    answered: frozenset[str]


class Engine(Protocol):
    """An agent harness with a model provider: everything a session needs from it."""

    def credential_settings(self, state_dir: Path) -> tuple[str, ...]:
        """What the hook layer's installer must name for the session to find its credential.

        Writes any file it names into ``state_dir``, the session's own; empty when the
        credential is put down at :meth:`start` instead.
        """
        ...

    def start(self, launch: Launch) -> Started:
        """Put the session's credential where its runtime reads it, and say how to start it.

        Raises:
            CredentialEndpointError: the credential would reach an endpoint not its vendor's.
        """
        ...

    def stream(self, path: Path) -> Captured:
        """Read a session's captured stream once, as its runtime wrote it."""
        ...

    def verdict(self, captured: Captured) -> object | None:
        """The session's structured answer, if it gave one: untrusted, judged by the caller."""
        ...

    def cost(self, captured: Captured) -> tuple[MessageUsage, ...]:
        """The session's account, message by message, held to the runtime's own totals.

        Raises:
            AccountingError: the account and the runtime's totals differ.
        """
        ...

    def stop(
        self, process: subprocess.Popen[bytes], started: str | None, wall_clock_s: float
    ) -> SessionEnd:
        """Wait for a session within its wall clock, then stop everything it left running."""
        ...

    def release(self, state_dir: Path, config_dir: Path, stream: Path | None) -> None:
        """Take the session's credential away, and redact it from ``stream`` if one is named."""
        ...

    def layers(self, profile: Profile, *, version: str, os_layer: Present | Absent) -> LayersHeld:
        """Which layers hold around ``profile``'s sessions on this harness ``version``."""
        ...

    def record(
        self, *, version: str, models: Iterable[str], os_layer: Present | Absent
    ) -> EngineRecord:
        """The engine as a run records it: harness, version, provider, models, layers held."""
        ...
