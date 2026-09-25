"""What a hook reads from its configuration and its event, as interfaces.

Imported for type checking only. At run time a hook receives the lean objects
built by :mod:`physgate.hooks.lean`; in tests it may receive the pydantic models
from :mod:`physgate.hooks.config`. Both have these attributes, which is all a
hook relies on, so the checks are written once against the interface.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class RootView(Protocol):
    """A protected root."""

    @property
    def path(self) -> str: ...  # noqa: D102

    @property
    def reason(self) -> str: ...  # noqa: D102

    @property
    def watch(self) -> str: ...  # noqa: D102


class ExperimentView(Protocol):
    """The frozen-experiment rule."""

    @property
    def root(self) -> str: ...  # noqa: D102

    @property
    def frozen_marker(self) -> str: ...  # noqa: D102

    @property
    def always_frozen_name(self) -> str: ...  # noqa: D102


class InstallationView(Protocol):
    """Where the hook code runs from."""

    @property
    def interpreter(self) -> str: ...  # noqa: D102

    @property
    def package_dir(self) -> str: ...  # noqa: D102

    @property
    def environment_root(self) -> str: ...  # noqa: D102

    @property
    def base_prefix(self) -> str: ...  # noqa: D102


class ConfigView(Protocol):
    """The session configuration."""

    @property
    def profile(self) -> str: ...  # noqa: D102

    @property
    def role(self) -> str | None: ...  # noqa: D102

    @property
    def worktree(self) -> str: ...  # noqa: D102

    @property
    def own_branch(self) -> str | None: ...  # noqa: D102

    @property
    def store_root(self) -> str | None: ...  # noqa: D102

    @property
    def state_dir(self) -> str: ...  # noqa: D102

    @property
    def protected_roots(self) -> Sequence[RootView]: ...  # noqa: D102

    @property
    def experiments(self) -> Sequence[ExperimentView]: ...  # noqa: D102

    @property
    def held_out(self) -> Sequence[str]: ...  # noqa: D102

    @property
    def required_reading(self) -> Sequence[str]: ...  # noqa: D102

    @property
    def always_loaded(self) -> Sequence[str]: ...  # noqa: D102

    @property
    def token_ceiling(self) -> int: ...  # noqa: D102

    @property
    def tools_allowed(self) -> Sequence[str]: ...  # noqa: D102

    @property
    def installation(self) -> InstallationView: ...  # noqa: D102

    @property
    def watchdog_seconds(self) -> int: ...  # noqa: D102

    @property
    def hook_timeout_seconds(self) -> int: ...  # noqa: D102


class InputView(Protocol):
    """The event description Claude Code hands a hook."""

    @property
    def session_id(self) -> str: ...  # noqa: D102

    @property
    def cwd(self) -> str: ...  # noqa: D102

    @property
    def hook_event_name(self) -> str: ...  # noqa: D102

    @property
    def tool_name(self) -> str | None: ...  # noqa: D102

    @property
    def tool_input(self) -> Mapping[str, Any] | None: ...  # noqa: D102

    @property
    def tool_response(self) -> Any: ...  # noqa: D102, ANN401 - the tool's own shape

    @property
    def agent_id(self) -> str | None: ...  # noqa: D102
