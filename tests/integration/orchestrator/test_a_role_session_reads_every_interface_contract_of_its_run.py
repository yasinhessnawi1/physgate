"""A role session is shown the interfaces it designs against before it may do anything else.

ARCH-020's required set is the role's standards and skill, the module specification and
the interface contracts touching the module. The decomposition writes each interface node
it planned into the run branch as a contract file beside the specifications, in the same
commit, and dispatch adds every contract that commit issued to the session's required
reading, so the hook layer refuses every tool but Read until each one has been read.

Until the plan names an interface's consumers, every interface of the run is required of
every session: a superset of "touching", never a subset.

Where a run issued no contract (a request without a specification commit, or a commit from
before contracts were issued), the installer is handed exactly the reading it was handed
before, byte for byte.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from git_rig import config, run_layout, target_repo
from knowledge_fixture import build_fixture_library
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.hooks.config import SessionConfig
from physgate.hooks.reading import outstanding
from physgate.knowledge import loader
from physgate.orchestrator import dispatch as dispatch_module
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import Outcome, Plan, PlannedModule, mint_id, start_run
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.exceptions import DecompositionError, InvocationError
from physgate.orchestrator.git import commit_all, head_of
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import RunConfig, write_run_config
from physgate.state.schema import Node
from physgate.state.store import Store

pytestmark = pytest.mark.integration

needs_binary = pytest.mark.skipif(
    not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
    reason="no Claude Code binary on this machine",
)

ROLE = "electrical"
MODULE = "power"
INTERFACES = ("iface.bus", "iface.supply")


def _interface(node_id: str) -> Node:
    return Node.model_validate(
        {
            "id": node_id,
            "kind": "interface",
            "domain": ROLE,
            "owner_role": ROLE,
            "quantities": {
                "supply_voltage": {
                    "value": 12.0,
                    "unit": "V",
                    "source": "decomposition",
                    "written_by": ROLE,
                }
            },
            "requirements": [],
            "constrains": [],
            "model": None,
            "geometry_hash": "sha256:0",
            "updated": "2026-10-21T00:00:00Z",
        }
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def _decompose(root: Path, interfaces: tuple[Node, ...]) -> tuple[RunGit, RunConfig, str]:
    """Start a run from a fixed plan, as the decomposition does after its one call."""
    repo = target_repo(root)
    cfg = config().model_copy(update={"target_head": head_of(repo, "master")})
    plan = Plan(
        modules=(
            PlannedModule(name=MODULE, role=ROLE, module_dir="modules/power", spec="Size it.\n"),
        ),
        interface_nodes=interfaces,
    )
    outcome = Outcome(
        session_id="no-call",
        ok=True,
        cause=None,
        detail="",
        plan=plan,
        usage=(),
        model="claude-sonnet-5",
        num_turns=1,
    )
    run_dir = root / "run"
    start_run(
        outcome,
        config=cfg,
        run_dir=run_dir,
        target_repo=repo,
        library=build_fixture_library(root / "library"),
    ).close()
    run = RunGit(repo=repo, run_dir=run_dir, run_id=cfg.run_id)
    return run, cfg, mint_id(cfg.seed, 0, MODULE)


def _request(cfg: RunConfig, subtask_id: str, spec_commit: str | None) -> SessionRequest:
    return SessionRequest(
        subtask_id=subtask_id,
        attempt=1,
        assigned_role=ROLE,
        spec_path=f".physgate/specs/{subtask_id}.md",
        module_dir="modules/power",
        model="claude-sonnet-5",
        repair_instruction=None,
        bounds=cfg.bounds,
        spec_commit=spec_commit,
    )


def _dispatcher(
    cfg: RunConfig, run: RunGit, install_bin: Path, base_url: str | None = None
) -> ClaudeDispatcher:
    return ClaudeDispatcher(
        config=cfg,
        run=run,
        store_root=run.run_dir / "store",
        install_bin=install_bin,
        binary=claude_binary() if base_url is not None else "unused-by-install",
        base_url=base_url,
        credential=Credential("api_key", DUMMY_KEY),
        review_root=Path("/nonexistent/review-scratch"),
    )


def _dev_physgate_binary() -> Path:
    return Path(sys.executable).parent / "physgate"


def _contract(node_id: str) -> str:
    return f".physgate/interfaces/{node_id}.json"


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)


@pytest.mark.parametrize("count", [1, 2])
def test_decomposition_issues_each_interface_node_as_a_contract_beside_the_specs(
    tmp_path: Path, count: int
) -> None:
    nodes = tuple(_interface(i) for i in INTERFACES[:count])
    run, _, subtask_id = _decompose(tmp_path, nodes)
    issued = _git(run.repo, "rev-parse", run.run_branch).strip()
    # One commit issues the specifications and the contracts together.
    in_commit = set(_git(run.repo, "show", "--name-only", "--format=", issued).split())
    assert f".physgate/specs/{subtask_id}.md" in in_commit
    contracts = {_contract(n.id) for n in nodes}
    assert contracts <= in_commit
    listed = set(
        _git(run.repo, "ls-tree", "-r", "--name-only", issued, ".physgate/interfaces/").split()
    )
    assert listed == contracts
    for node in nodes:
        shown = _git(run.repo, "show", f"{issued}:{_contract(node.id)}")
        assert Node.model_validate(json.loads(shown)) == node
        assert shown.endswith("\n")


def test_an_interface_id_that_is_no_node_id_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    # The contract's file name is built from the id, so an id carrying a separator would
    # put a file outside the contracts' directory.
    escaping = _interface("iface.bus").model_copy(update={"id": "../../escaped.bus"})
    with pytest.raises(DecompositionError, match="interface node"):
        _decompose(tmp_path, (escaping,))
    repo = tmp_path / "target"
    assert _git(repo, "branch", "--list", "physgate/*").strip() == ""
    assert not (tmp_path / "run" / "run.json").exists()


def test_the_installed_session_config_requires_every_interface_contract_of_the_run(
    tmp_path: Path,
) -> None:
    run, cfg, subtask_id = _decompose(tmp_path, tuple(_interface(i) for i in INTERFACES))
    issued = _git(run.repo, "rev-parse", run.run_branch).strip()
    request = _request(cfg, subtask_id, issued)
    worktree = run.open_subtask(subtask_id)
    installed = _dispatcher(cfg, run, _dev_physgate_binary())._install(  # noqa: SLF001 - the thing under test
        request, worktree, run.run_dir / "sessions" / "probe", None
    )
    written = SessionConfig.model_validate_json(Path(installed.config).read_text())
    contracts = {str(worktree / _contract(i)) for i in INTERFACES}
    assert contracts <= set(written.required_reading)
    # Required, never always-loaded: the contracts do not count against the role's ceiling.
    assert not contracts & set(written.always_loaded)
    # The hook layer's own reading check: each contract is outstanding until it is read.
    hook_input = dispatch_module._Input(session_id="probe-session")  # noqa: SLF001
    assert contracts <= set(outstanding(written, hook_input))
    for path in contracts:
        assert Path(path).is_file()


@needs_binary
def test_a_session_that_skips_an_interface_contract_cannot_make_a_tool_call(
    tmp_path: Path, install_bin: Path
) -> None:
    run, cfg, subtask_id = _decompose(tmp_path, tuple(_interface(i) for i in INTERFACES))
    issued = _git(run.repo, "rev-parse", run.run_branch).strip()
    worktree = run.subtask_worktree(subtask_id)
    early = worktree / "modules" / "power" / "early.py"
    steps: list[dict[str, Any]] = [
        *(tool("Read", file_path=str(worktree / p)) for p in loader.always_loaded(ROLE)),
        tool("Read", file_path=str(worktree / f".physgate/specs/{subtask_id}.md")),
        # The first contract is read; the second is skipped.
        tool("Read", file_path=str(worktree / _contract(INTERFACES[0]))),
        tool("Bash", command="echo early > modules/power/early.py"),
        text("done"),
    ]
    with serving(Script(main=steps)) as (api, url):
        report = _dispatcher(cfg, run, install_bin, url).run(_request(cfg, subtask_id, issued))
    refused = api.requests[len(steps) - 1].last_user
    assert "Required reading is not complete" in refused
    assert _contract(INTERFACES[1]) in refused and _contract(INTERFACES[0]) not in refused
    assert not early.exists()
    assert not report.reading_verified


@needs_binary
def test_a_session_that_reads_every_interface_contract_works(
    tmp_path: Path, install_bin: Path
) -> None:
    """The control for the test above: the same session, reading both contracts, runs."""
    run, cfg, subtask_id = _decompose(tmp_path, tuple(_interface(i) for i in INTERFACES))
    issued = _git(run.repo, "rev-parse", run.run_branch).strip()
    worktree = run.subtask_worktree(subtask_id)
    steps: list[dict[str, Any]] = [
        *(tool("Read", file_path=str(worktree / p)) for p in loader.always_loaded(ROLE)),
        tool("Read", file_path=str(worktree / f".physgate/specs/{subtask_id}.md")),
        *(tool("Read", file_path=str(worktree / _contract(i))) for i in INTERFACES),
        tool("Bash", command="echo early > modules/power/early.py"),
        text("done"),
    ]
    with serving(Script(main=steps)) as (api, url):
        report = _dispatcher(cfg, run, install_bin, url).run(_request(cfg, subtask_id, issued))
    assert "Required reading is not complete" not in api.requests[len(steps) - 1].last_user
    assert (worktree / "modules" / "power" / "early.py").exists()
    assert report.reading_verified


def _no_contract_layout(root: Path) -> tuple[RunGit, str]:
    """A run branch whose specification commit issued no contract."""
    run = run_layout(root)
    (run.integration / ".physgate" / "specs").mkdir(parents=True)
    (run.integration / ".physgate" / "specs" / "s1.md").write_text("Size the driver.\n")
    for relative in loader.always_loaded(ROLE):
        path = run.integration / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relative.name}\n\nFixture content.\n")
    issued = commit_all(run.integration, "specifications\n")
    Store(run.run_dir / "store").close()
    return run, issued


def test_where_no_contract_was_issued_the_installer_gets_the_reading_it_always_got(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, issued = _no_contract_layout(tmp_path)
    cfg = config()
    # Installed without the OS layer, as the run's recorded configuration allows.
    write_run_config(run.run_dir / "run.json", cfg)
    worktree = run.open_subtask("s1")
    seen: list[list[str]] = []
    real_run = subprocess.run

    def recording(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401 - subprocess.run's own
        seen.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr("physgate.orchestrator.dispatch.subprocess.run", recording)
    configs = []
    for name, spec_commit in (("without", None), ("with", issued)):
        sdir = run.run_dir / "sessions" / name
        installed = _dispatcher(cfg, run, _dev_physgate_binary())._install(  # noqa: SLF001
            _request(cfg, "s1", spec_commit), worktree, sdir, None
        )
        configs.append(Path(installed.config).read_bytes().replace(str(sdir).encode(), b"<s>"))
    installs = [argv for argv in seen if argv[1:3] == ["hooks", "install"]]
    assert len(installs) == 2
    without, with_commit = (
        [a.replace(str(run.run_dir / "sessions" / n), "<s>") for a in argv]
        for argv, n in zip(installs, ("without", "with"), strict=True)
    )
    # The reading exactly as dispatch built it before contracts existed: same files, same order.
    before = [
        arg
        for path in loader.required_reading(ROLE, Path(".physgate/specs/s1.md"))
        for arg in ("--reading", str(worktree / path))
    ]
    reading = [
        arg
        for i, flag in enumerate(with_commit)
        if flag == "--reading"
        for arg in (flag, with_commit[i + 1])
    ]
    assert reading == before
    assert without == with_commit
    assert configs[0] == configs[1]


def test_a_decomposed_run_s_session_with_no_specification_commit_is_refused(
    tmp_path: Path,
) -> None:
    """Fail closed: a run that recorded interface contracts installs no session without them."""
    run, cfg, subtask_id = _decompose(tmp_path, (_interface(INTERFACES[0]),))
    worktree = run.open_subtask(subtask_id)
    sdir = run.run_dir / "sessions" / "probe"
    with pytest.raises(InvocationError, match="interface contracts"):
        _dispatcher(cfg, run, _dev_physgate_binary())._install(  # noqa: SLF001 - the thing under test
            _request(cfg, subtask_id, None), worktree, sdir, None
        )
    assert not (sdir / "session").exists()
