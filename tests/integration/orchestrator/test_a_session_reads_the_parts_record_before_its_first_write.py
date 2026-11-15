"""A session of a run that asked about parts reads the record's files before it may write.

The dispatcher renders the record the request carries into files in the session's own directory,
outside the worktree (so no attempt's commit holds them and nothing reaches the run branch),
holds the record's bytes to the digest and length the release line named before anything is
installed, and adds each file to the required reading, the mechanism the specification is read
through. A request with no record is installed exactly as before.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import test_a_role_session_reads_every_interface_contract_of_its_run as contracts

from physgate.hooks.config import SessionConfig
from physgate.hooks.reading import outstanding
from physgate.orchestrator import dispatch as dispatch_module
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.parts_reading import parts_files
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.protocols import IssuedState

pytestmark = pytest.mark.integration

RECORD = json.dumps(
    {
        "components": [
            {
                "node": "power.motor",
                "label": "the motor",
                "choice": "make",
                "declared": {},
                "texts": ["printed in PETG"],
            }
        ]
    },
    sort_keys=True,
    separators=(",", ":"),
).encode()


def held_of(data: bytes = RECORD) -> IssuedState:
    return IssuedState(
        text=data.decode(), sha256=hashlib.sha256(data).hexdigest(), length=len(data)
    )


def with_record(request: SessionRequest, held: IssuedState | None) -> SessionRequest:
    return request.model_copy(update={"parts_record": held})


def _setup(tmp_path: Path) -> tuple[Any, Any, str, str]:
    run, cfg, subtask_id = contracts._decompose(  # noqa: SLF001 - the rig's own
        tmp_path,
        tuple(contracts._interface(i) for i in contracts.INTERFACES),  # noqa: SLF001
    )
    issued = contracts._git(run.repo, "rev-parse", run.run_branch).strip()  # noqa: SLF001
    return run, cfg, subtask_id, issued


def _install(run: Any, cfg: Any, request: SessionRequest, worktree: Path, sdir: Path) -> Any:  # noqa: ANN401
    return contracts._dispatcher(cfg, run, contracts._dev_physgate_binary())._install(  # noqa: SLF001
        request, worktree, sdir, None, own_temp=Path("/var/tmp/pgs/0123456789")
    )


def _paths(sdir: Path) -> list[Path]:
    return [sdir / "parts" / name for name, _ in parts_files(RECORD)]


def test_the_session_cannot_act_before_reading_the_parts_record(tmp_path: Path) -> None:
    run, cfg, subtask_id, issued = _setup(tmp_path)
    request = with_record(contracts._request(cfg, subtask_id, issued), held_of())  # noqa: SLF001
    worktree = run.open_subtask(subtask_id)
    sdir = run.run_dir / "sessions" / "probe"
    installed = _install(run, cfg, request, worktree, sdir)
    written = SessionConfig.model_validate_json(Path(installed.config).read_text())
    hook_input = dispatch_module._Input(session_id="probe-session")  # noqa: SLF001
    for path, (_, data) in zip(_paths(sdir), parts_files(RECORD), strict=True):
        assert path.read_bytes() == data
        assert not path.is_relative_to(worktree)
        assert str(path) in written.required_reading
        assert str(path) not in written.always_loaded
        assert str(path) in outstanding(written, hook_input)


@pytest.mark.parametrize("what", ["a byte short", "another record"])
def test_a_record_that_is_not_the_requests_is_refused_before_install(
    tmp_path: Path, what: str
) -> None:
    run, cfg, subtask_id, issued = _setup(tmp_path)
    held = held_of()
    if what == "another record":
        other = RECORD.replace(b"PETG", b"steel")
        held = held.model_copy(update={"text": other.decode()})
    else:
        held = held.model_copy(update={"text": RECORD[:-1].decode()})
    request = with_record(contracts._request(cfg, subtask_id, issued), held)  # noqa: SLF001
    worktree = run.open_subtask(subtask_id)
    sdir = run.run_dir / "sessions" / "probe"
    with pytest.raises(InvocationError, match="parts record"):
        _install(run, cfg, request, worktree, sdir)
    assert not (sdir / "session").exists()


def test_a_request_with_no_record_is_installed_exactly_as_before(tmp_path: Path) -> None:
    run, cfg, subtask_id, issued = _setup(tmp_path)
    worktree = run.open_subtask(subtask_id)
    configs = []
    for name, held in (("without", None), ("with", held_of())):
        sdir = run.run_dir / "sessions" / name
        request = with_record(contracts._request(cfg, subtask_id, issued), held)  # noqa: SLF001
        installed = _install(run, cfg, request, worktree, sdir)
        configs.append(SessionConfig.model_validate_json(Path(installed.config).read_text()))
    without, with_ = configs
    assert not (run.run_dir / "sessions" / "without" / "parts").exists()
    added = [str(p) for p in _paths(run.run_dir / "sessions" / "with")]
    assert sorted(with_.required_reading) == sorted([*without.required_reading, *added])
