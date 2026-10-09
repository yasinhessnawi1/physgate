"""A run's configuration: every input that decides what the run does, written once.

Nothing here has a default. A seed, a model string, a bound or the gate mode read
from a default inside a function is an input nobody chose and nobody recorded, so
a run that lacks one does not start. The file is written once, before the first
action, and a resumed run refuses to continue under a configuration that is not
byte-for-byte the recorded one (ARCH-145: any run is reproducible from its
recorded configuration).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

import physgate
from physgate.orchestrator.common import (
    AuthMode,
    GateMode,
    ModelString,
    NonEmptyStr,
    first_problem,
)
from physgate.orchestrator.exceptions import GitError, RunConfigError
from physgate.orchestrator.git import git
from physgate.orchestrator.role_python import RolePython


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ModelStrings(_Frozen):
    """Every model a run may call, by what calls it."""

    decomposition: ModelString
    roles: dict[NonEmptyStr, ModelString]
    reviewers: dict[NonEmptyStr, ModelString]


class RunBounds(_Frozen):
    """The limits a session runs under. Required, like the seed; none has a default.

    Values proposed when the orchestrator was designed: on the scripted endpoint
    0 retries, 120 s, 20 turns and no infrastructure retries; for a real model 0
    retries, 1800 s, 150 turns and delays of 60 s then 300 s. The retry count of
    0 is measured (the binary's own retries hid requests from the count and held
    one session open for minutes). **The real-model wall clock, turn limit and
    retry delays are judgement** until a real run's recorded durations replace
    them. An experiment that reads these numbers freezes its own values.
    """

    binary_max_retries: Annotated[int, Field(ge=0)]
    session_wall_clock_s: Annotated[float, Field(gt=0)]
    session_max_turns: Annotated[int, Field(ge=1)]
    infra_retry_delays_s: tuple[Annotated[float, Field(ge=0)], ...]


#: The endpoint the run's model calls go to: ``default`` for the binary's own, or
#: an http(s) URL with no credentials, query or fragment in it.
Endpoint = Annotated[
    str, StringConstraints(pattern=r"^(default|https?://[^/?#@\s]+(/[^?#@\s]*)?)$")
]


#: An http(s) URL, taken apart without a network library (the orchestrator imports
#: none): scheme, optional userinfo (dropped), host, optional port, optional path,
#: then anything from ``?`` or ``#`` on (dropped).
_URL = re.compile(
    r"^(?P<scheme>https?)://(?:[^@/?#]*@)?"
    r"(?P<host>\[[0-9A-Fa-f:.]+\]|[^:/?#@\[\]\s]+)"
    r"(?::(?P<port>[0-9]{1,5}))?(?P<path>/[^?#\s]*)?(?:[?#]\S*)?$",
    re.IGNORECASE,
)


def endpoint_of(base_url: str | None) -> str:
    """The endpoint a run records for ``ANTHROPIC_BASE_URL``: never the secret, always the place.

    Which provider answered (the default, a proxy, the scripted local endpoint)
    decides what a run's numbers mean, so it is recorded like a model string.
    Userinfo, query and fragment are dropped, since a key can travel in any of
    them; an unset or empty value is ``default``.

    Raises:
        RunConfigError: the value is not an http(s) URL with a host.
    """
    if not base_url:
        return "default"
    found = _URL.match(base_url)
    if not found:
        msg = "ANTHROPIC_BASE_URL is not an http(s) URL with a host"
        raise RunConfigError(msg)
    port = f":{found['port']}" if found["port"] else ""
    path = (found["path"] or "").rstrip("/")
    return f"{found['scheme'].lower()}://{found['host'].lower()}{port}{path}"


def require_endpoint(config: RunConfig, base_url: str | None) -> None:
    """Refuse to drive a run against an endpoint other than the one it recorded.

    Raises:
        RunConfigError: the endpoint differs, or the value is not a URL.
    """
    now = endpoint_of(base_url)
    if now != config.endpoint:
        msg = "the endpoint differs from the one this run recorded"
        raise RunConfigError(msg, recorded=config.endpoint, now=now)


Sha1 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

#: The effort levels the pinned binary's ``--effort`` accepts. The binary sends
#: the level it resolves in every request (``output_config.effort``); left
#: unset it takes a default from a model catalog that can change without the
#: binary's version changing, so a run names its level and passes it.
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class HarnessState(_Frozen):
    """The source checkout the orchestrator ran from, as it was when the run was recorded.

    A number is only as reproducible as the code that produced it: the commit, whether
    the tree held anything uncommitted, and a digest of what it held. ``commit`` is
    ``None`` only when there is no git checkout at all, which is never clean.
    """

    commit: Sha1 | None
    clean: bool
    #: A digest of the uncommitted changes (the diff against the commit and every
    #: untracked file not ignored, by path and content); ``None`` on a clean tree.
    uncommitted_sha256: Sha256 | None

    @model_validator(mode="after")
    def _clean_means_nothing_uncommitted(self) -> HarnessState:
        if self.commit is None and (self.clean or self.uncommitted_sha256 is not None):
            msg = "a harness with no checkout is recorded as not clean, with no digest"
            raise ValueError(msg)
        if self.commit is not None and self.clean != (self.uncommitted_sha256 is None):
            msg = "a clean tree has no uncommitted digest, and a dirty one has one"
            raise ValueError(msg)
        return self


def harness_root() -> Path | None:
    """The source checkout this orchestrator runs from, or ``None`` if it runs from none.

    Read from where the running package itself lives, so it names the checkout whose
    gate, curated library and experiments this run is judged by.
    """
    root = Path(physgate.__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").exists() else None


def harness_state(root: Path | None) -> HarnessState:
    """What the checkout at ``root`` is now: its commit, and anything not committed.

    ``root`` is ``None`` when the orchestrator does not run from a source checkout.

    Raises:
        RunConfigError: git failed on a checkout that exists.
    """
    try:
        inside = root is not None and git(root, "rev-parse", "--is-inside-work-tree", check=False)
    except OSError as exc:  # no git on this machine: the checkout cannot be read at all
        msg = "git is not available to read the harness checkout"
        raise RunConfigError(msg, root=str(root), reason=str(exc)) from None
    if root is None or not inside:
        return HarnessState(commit=None, clean=False, uncommitted_sha256=None)
    try:
        commit = git(root, "rev-parse", "HEAD").strip()
        diff = git(root, "diff", "--binary", "HEAD")
        untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    except GitError as exc:
        msg = "the harness checkout could not be read"
        raise RunConfigError(msg, root=str(root), reason=str(exc)) from None
    digest = hashlib.sha256(diff.encode())
    files = sorted(name for name in untracked if name)
    for name in files:
        digest.update(b"\0" + name.encode() + b"\0")
        digest.update(hashlib.sha256((root / name).read_bytes()).digest())
    clean = not diff and not files
    return HarnessState(
        commit=commit, clean=clean, uncommitted_sha256=None if clean else digest.hexdigest()
    )


#: How a role session's reasoning appears in its trajectory (``--thinking-display``).
ThinkingDisplay = Literal["summarized", "omitted"]


class RunConfig(_Frozen):
    """Everything a run is reproduced from."""

    run_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    seed: int
    brief_sha256: Sha256
    gate_mode: GateMode
    models: ModelStrings
    bounds: RunBounds
    token_ceiling: Annotated[int, Field(gt=0)]
    claude_version: NonEmptyStr
    target_head: Sha1
    endpoint: Endpoint
    auth: AuthMode
    #: Whether this run's numbers may be reported. A reportable run starts only from
    #: a clean checkout with a commit, so every number it produces names the code.
    reportable: bool
    harness: HarnessState
    #: Passed to every invocation as ``--effort``.
    effort: Effort
    #: Passed to every invocation as ``CLAUDE_CODE_MAX_OUTPUT_TOKENS``: the request's
    #: ``max_tokens``, otherwise a catalog default like the effort level.
    max_output_tokens: Annotated[int, Field(gt=0)]
    #: Passed to every role session as ``--thinking-display``. ``summarized`` puts a
    #: summary of the session's reasoning into its trajectory, which its reviewer reads;
    #: the binary's own default leaves the reasoning out. A run recorded before this
    #: field existed ran with the default, and reads as ``omitted``.
    thinking_display: ThinkingDisplay
    #: The interpreter role sessions find as ``python3``, as measured when the run was
    #: configured (``role_python.measure``), or ``None`` for none: the parameters name a
    #: path or null. A run recorded before the field existed named none, and reads so.
    role_python: RolePython | None

    @model_validator(mode="after")
    def _reportable_needs_a_clean_commit(self) -> RunConfig:
        if self.reportable and (self.harness.commit is None or not self.harness.clean):
            msg = "a reportable run starts only from a clean checkout with a commit"
            raise ValueError(msg)
        return self

    def canonical_bytes(self) -> bytes:
        """The recorded form: stable key order, so equal configs are equal bytes.

        ``thinking_display`` is left out when it is ``omitted``, what every run before
        the field existed ran with, and ``role_python`` when it is ``None``, so their
        recorded digests still name them.
        """
        exclude = set()
        if self.thinking_display == "omitted":
            exclude.add("thinking_display")
        if self.role_python is None:
            exclude.add("role_python")
        return self.model_dump_json(indent=None, exclude=exclude or None).encode() + b"\n"

    def sha256(self) -> str:
        """Digest of the recorded form, carried on the run's first event."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def require_reportable(harness: HarnessState, *, reportable: bool) -> None:
    """Refuse a reportable run from a checkout that is dirty or has no commit.

    Called before the configuration is built, so the refusal says what is wrong
    with the checkout rather than which field failed validation.

    Raises:
        RunConfigError: the run is reportable and the checkout cannot back its numbers.
    """
    if not reportable:
        return
    if harness.commit is None:
        msg = "a reportable run needs the harness to run from a git checkout with a commit"
        raise RunConfigError(msg)
    if not harness.clean:
        msg = "a reportable run starts only from a clean checkout; commit the changes first"
        raise RunConfigError(msg, uncommitted_sha256=str(harness.uncommitted_sha256))


def require_harness(config: RunConfig, now: HarnessState) -> None:
    """Refuse to drive a run on code other than the code it recorded.

    Raises:
        RunConfigError: the checkout's commit, cleanliness or uncommitted changes differ.
    """
    if now != config.harness:
        mine, theirs = now.model_dump(), config.harness.model_dump()
        changed = sorted(key for key in theirs if theirs[key] != mine[key])
        msg = "the harness checkout differs from the one this run recorded"
        raise RunConfigError(msg, changed=",".join(changed))


def write_run_config(path: Path, config: RunConfig) -> None:
    """Write ``config`` to ``path``, once, synced.

    Raises:
        RunConfigError: a configuration is already recorded there.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        msg = "a run configuration is already recorded; a run's configuration is written once"
        raise RunConfigError(msg, path=str(path)) from None
    try:
        os.write(fd, config.canonical_bytes())
        os.fsync(fd)
    finally:
        os.close(fd)


def load_run_config(path: Path) -> RunConfig:
    """Read the recorded configuration back.

    Raises:
        RunConfigError: there is none, or it is not a valid configuration.
    """
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        msg = "no run configuration is recorded"
        raise RunConfigError(msg, path=str(path)) from None
    try:
        recorded = json.loads(raw)
    except ValueError:  # not JSON, or not UTF-8: left to the validation below to refuse
        recorded = None
    if isinstance(recorded, dict) and "thinking_display" not in recorded:
        # Recorded before the field existed: the binary's default, which is ``omitted``.
        recorded = {**recorded, "thinking_display": "omitted"}
        raw = json.dumps(recorded).encode()
    if isinstance(recorded, dict) and "role_python" not in recorded:
        # Recorded before the field existed: no interpreter was named.
        raw = json.dumps({**recorded, "role_python": None}).encode()
    try:
        return RunConfig.model_validate_json(raw)
    except ValidationError as exc:
        msg = "the recorded run configuration is not valid"
        raise RunConfigError(msg, path=str(path), reason=first_problem(exc)) from None


def require_recorded(path: Path, config: RunConfig) -> RunConfig:
    """Return the recorded configuration if ``config`` is exactly it.

    What a resume calls before anything else: a run continued under different
    inputs is a different run wearing the first one's name.

    Raises:
        RunConfigError: nothing is recorded, or ``config`` differs from it; the
            message names every field that differs.
    """
    recorded = load_run_config(path)
    if recorded.canonical_bytes() != config.canonical_bytes():
        mine, theirs = config.model_dump(), recorded.model_dump()
        changed = sorted(key for key in theirs if theirs[key] != mine.get(key))
        msg = "the configuration differs from the one this run recorded"
        raise RunConfigError(msg, path=str(path), changed=",".join(changed))
    return recorded
