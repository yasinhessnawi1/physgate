"""Integration's session reads its issued state in full before it may use any other tool.

The dispatcher writes the issued state the request carries into the session's own directory, which
lies outside the worktree (so no attempt's commit holds it, and nothing reaches the run branch) and
which sessions may not write; it reads the bytes back and holds them to the request's digest and
length before the session is installed, and adds the file to the required reading, the mechanism
the specification is read through. The hook layer then refuses every tool but Read until the file
has been read whole. That a read is whole is proved by the reading check and the document's form
together: the check counts the file read only when the Read tool has returned every one of its
lines at its current content, and no line of the document is longer than the transcript's width,
which the pinned binary's Read tool returns whole (measured here: every line comes back to the
model as written). A request with no issued state is installed exactly as before.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import test_a_role_session_reads_every_interface_contract_of_its_run as contracts
from scripted_endpoint import Script, serving, text, tool

from physgate.hooks.config import SessionConfig
from physgate.hooks.reading import outstanding
from physgate.knowledge import loader
from physgate.orchestrator import dispatch as dispatch_module
from physgate.orchestrator.dispatch import ClaudeDispatcher, issued_state_path, role_prompt
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.integration_state import STATE_NAME
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.protocols import IssuedState
from physgate.oslayer.probe import Present
from physgate.reviewers.transcript import CONTINUED, WIDTH

pytestmark = pytest.mark.integration

needs_binary = pytest.mark.skipif(
    not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
    reason="no Claude Code binary on this machine",
)

#: A document of the issued state's form: short lines, and one cut at the transcript's width.
LONG = "y" * (2 * WIDTH + 17)
DOCUMENT = "\n".join(
    [
        "# Integration's issued state",
        "",
        'The run\'s gate mode is "observe".',
        LONG[:WIDTH] + CONTINUED,
        LONG[WIDTH : 2 * WIDTH] + CONTINUED,
        LONG[2 * WIDTH :],
        "",
    ]
)


def state_of(text_: str) -> IssuedState:
    data = text_.encode("utf-8")
    return IssuedState(text=text_, sha256=hashlib.sha256(data).hexdigest(), length=len(data))


def with_state(request: SessionRequest, state: IssuedState | None) -> SessionRequest:
    return request.model_copy(update={"issued_state": state})


def _setup(tmp_path: Path) -> tuple[Any, Any, str, str]:
    run, cfg, subtask_id = contracts._decompose(  # noqa: SLF001 - the rig's own
        tmp_path,
        tuple(contracts._interface(i) for i in contracts.INTERFACES),  # noqa: SLF001
    )
    issued = contracts._git(run.repo, "rev-parse", run.run_branch).strip()  # noqa: SLF001
    return run, cfg, subtask_id, issued


def test_the_integration_session_cannot_act_before_reading_its_state(tmp_path: Path) -> None:
    run, cfg, subtask_id, issued = _setup(tmp_path)
    request = with_state(contracts._request(cfg, subtask_id, issued), state_of(DOCUMENT))  # noqa: SLF001
    worktree = run.open_subtask(subtask_id)
    sdir = run.run_dir / "sessions" / "probe"
    installed = contracts._dispatcher(cfg, run, contracts._dev_physgate_binary())._install(  # noqa: SLF001
        request, worktree, sdir, None
    )
    path = issued_state_path(sdir)
    # Written in the session's own directory, outside the worktree, byte for byte.
    assert path.read_bytes() == DOCUMENT.encode("utf-8")
    assert not path.is_relative_to(worktree)
    written = SessionConfig.model_validate_json(Path(installed.config).read_text())
    assert str(path) in written.required_reading
    assert str(path) not in written.always_loaded
    # The hook layer's own reading check: outstanding until read, like the specification.
    hook_input = dispatch_module._Input(session_id="probe-session")  # noqa: SLF001
    assert str(path) in outstanding(written, hook_input)
    # The session is told where it is.
    assert str(path) in role_prompt(request, path)


def test_a_state_whose_bytes_on_disk_are_not_the_requests_is_refused_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, cfg, subtask_id, issued = _setup(tmp_path)
    request = with_state(contracts._request(cfg, subtask_id, issued), state_of(DOCUMENT))  # noqa: SLF001
    worktree = run.open_subtask(subtask_id)
    sdir = run.run_dir / "sessions" / "probe"

    def torn(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True)
        path.write_bytes(data[:-1])

    monkeypatch.setattr(dispatch_module, "write_issued_state", torn)
    with pytest.raises(InvocationError, match="issued state"):
        contracts._dispatcher(cfg, run, contracts._dev_physgate_binary())._install(  # noqa: SLF001
            request, worktree, sdir, None
        )
    assert not (sdir / "session").exists()


def test_a_request_with_no_state_is_installed_exactly_as_before(tmp_path: Path) -> None:
    run, cfg, subtask_id, issued = _setup(tmp_path)
    worktree = run.open_subtask(subtask_id)
    configs = []
    for name, state in (("without", None), ("with", state_of(DOCUMENT))):
        sdir = run.run_dir / "sessions" / name
        request = with_state(contracts._request(cfg, subtask_id, issued), state)  # noqa: SLF001
        installed = contracts._dispatcher(cfg, run, contracts._dev_physgate_binary())._install(  # noqa: SLF001
            request, worktree, sdir, None
        )
        configs.append(SessionConfig.model_validate_json(Path(installed.config).read_text()))
    without, with_ = configs
    assert not issued_state_path(run.run_dir / "sessions" / "without").parent.exists()
    path = str(issued_state_path(run.run_dir / "sessions" / "with"))
    # The one file more, and nothing else: the installer keeps the reading in its own order.
    assert sorted(with_.required_reading) == sorted([*without.required_reading, path])


def _steps(worktree: Path, subtask_id: str, state: Path | None) -> list[dict[str, Any]]:
    role = contracts.ROLE
    return [
        *(tool("Read", file_path=str(worktree / p)) for p in loader.always_loaded(role)),
        tool("Read", file_path=str(worktree / f".physgate/specs/{subtask_id}.md")),
        *(
            tool("Read", file_path=str(worktree / contracts._contract(i)))
            for i in contracts.INTERFACES
        ),  # noqa: SLF001
        *([tool("Read", file_path=str(state))] if state is not None else []),
        tool("Bash", command="echo early > modules/power/early.py"),
        text("done"),
    ]


@pytest.fixture(params=["as this machine runs it", "with the OS layer off"])
def layer(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "with the OS layer off":
        monkeypatch.setattr(ClaudeDispatcher, "_layer_on", lambda self: False)
    return str(request.param)


@needs_binary
def test_a_session_that_skips_its_state_cannot_make_a_tool_call(
    tmp_path: Path, install_bin: Path, layer: str
) -> None:
    run, cfg, subtask_id, issued = _setup(tmp_path)
    worktree = run.subtask_worktree(subtask_id)
    request = with_state(contracts._request(cfg, subtask_id, issued), state_of(DOCUMENT))  # noqa: SLF001
    steps = _steps(worktree, subtask_id, None)
    with serving(Script(main=steps)) as (api, url):
        report = contracts._dispatcher(cfg, run, install_bin, url).run(request)  # noqa: SLF001
    refused = api.requests[len(steps) - 1].last_user
    assert "Required reading is not complete" in refused
    assert STATE_NAME in refused
    assert not (worktree / "modules" / "power" / "early.py").exists()
    assert not report.reading_verified


@needs_binary
def test_a_session_that_reads_its_state_works_and_is_shown_every_line_whole(
    tmp_path: Path, install_bin: Path, layer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test above, and the measurement the whole-read claim rests on."""
    run, cfg, subtask_id, issued = _setup(tmp_path)
    worktree = run.subtask_worktree(subtask_id)
    request = with_state(contracts._request(cfg, subtask_id, issued), state_of(DOCUMENT))  # noqa: SLF001
    # The session's directory is named by the id the dispatcher mints; fixed here, so the
    # script can name the file the session reads.
    fixed = uuid.UUID("00000000-0000-4000-8000-00000000b3b3")
    monkeypatch.setattr(dispatch_module, "uuid", SimpleNamespace(uuid4=lambda: fixed))
    path = issued_state_path(run.run_dir / "sessions" / str(fixed))
    steps = _steps(worktree, subtask_id, path)
    with serving(Script(main=steps)) as (api, url):
        dispatcher = contracts._dispatcher(cfg, run, install_bin, url)  # noqa: SLF001
        on = isinstance(dispatcher.os_layer(), Present) and layer == "as this machine runs it"
        report = dispatcher.run(request)
    read_at = next(i for i, step in enumerate(steps) if json.dumps(step).find(str(path)) >= 0)
    shown = api.requests[read_at + 1].last_user
    for line in DOCUMENT.splitlines():
        assert line in shown, f"a line of {len(line)} characters came back cut (layer on: {on})"
    assert "Required reading is not complete" not in api.requests[len(steps) - 1].last_user
    assert (worktree / "modules" / "power" / "early.py").exists()
    assert report.reading_verified


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from physgate.orchestrator.install import prepare_install

    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)
