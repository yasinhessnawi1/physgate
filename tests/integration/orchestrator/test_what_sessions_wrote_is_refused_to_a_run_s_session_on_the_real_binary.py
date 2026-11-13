"""What sessions wrote is refused to a run's session, for real: hooks and the OS layer.

A session started as a run's are, withholding a version's two protected tiers and the role's
withheld root, tries to read an authoring session's stream kept under that root: by the file
tool, by a plain command, and by a command whose path is built at run time, which the shell
parser cannot see and only the OS layer refuses. Driven by the scripted endpoint, so no model
is called and none can decline. The last form needs the OS layer; it runs in CI's OS-layer job.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.evaluation.per_role.arms.raw import RawSetup, run_session
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import binary_version
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.invocation import claude_binary, session_search_path
from physgate.orchestrator.run_config import RunBounds
from physgate.oslayer.probe import Absent, judge_here

pytestmark = pytest.mark.integration

SECRET = "a held-out brief an author wrote, never to be read"
VERSION = "a" * 64


def _api(name: str) -> Any:
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(
        tmp_path_factory.mktemp("install") / "hooks", Path(__file__).resolve().parents[3]
    )


def _store(tmp_path: Path) -> tuple[Path, tuple[Path, ...]]:
    """A store with one stream under the withheld root; the stream and the run's roots."""
    store = tmp_path.resolve() / "private" / "store"
    stream = (
        _api("physgate.evaluation.tiers.store.author_evidence")(store, "control")
        / "s-1"
        / "stdout.jsonl"
    )
    stream.parent.mkdir(parents=True)
    stream.write_text('{"type": "assistant", "text": "' + SECRET + '"}\n')
    version = store / "control" / VERSION
    for tier in ("held_out", "validation"):
        (version / tier).mkdir(parents=True)
    withheld = _api("physgate.evaluation.tiers.store.withheld_root")(store, "control")
    return stream, (version / "held_out", version / "validation", withheld)


def _setup(install_bin: Path, url: str, held: tuple[Path, ...]) -> RawSetup:
    binary = claude_binary()
    version = binary_version(binary)
    return RawSetup(
        binary=binary,
        claude_version=version,
        model="claude-sonnet-5",
        effort="high",
        max_output_tokens=4000,
        thinking_display="summarized",
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=10,
            infra_retry_delays_s=(),
        ),
        credential=Credential("api_key", DUMMY_KEY),
        base_url=url,
        install_bin=install_bin,
        role_python=None,
        held_out=tuple(str(r) for r in held),
        held_out_canaries=("e" * 32,),
        network="none",
        os_layer=judge_here(claude_version=version, search_path=session_search_path(binary)),
    )


def _attempts(stream: Path) -> list[tuple[str, dict[str, Any]]]:
    inside = stream.relative_to(stream.parents[2])
    built = f"d=$(printf %s {stream.parents[3]}/with)held; cat $d/{inside}"
    return [
        ("read tool", tool("Read", file_path=str(stream))),
        ("shell", tool("Bash", command=f"cat {stream}", description="x")),
        ("a path built at run time", tool("Bash", command=built, description="x")),
    ]


@pytest.mark.parametrize("attempt", [0, 1, 2], ids=["read tool", "shell", "built at run time"])
def test_a_run_s_session_is_refused_an_author_s_stream_under_the_withheld_root(
    tmp_path: Path, install_bin: Path, attempt: int
) -> None:
    stream, held = _store(tmp_path)
    name, step = _attempts(stream)[attempt]
    work = tmp_path / "work"
    with serving(Script(main=[step, text("done")])) as (api, url):
        setup = _setup(install_bin, url, held)
        if attempt == 2 and isinstance(setup.os_layer, Absent):
            pytest.skip(f"only the OS layer refuses a path built at run time: {setup.os_layer}")
        run_session("Read what you are asked to.", setup, work, cap=10**9)
        told = " ".join(r.last_user for r in api.requests)
    assert SECRET not in told, f"{name}: a run's session was shown what an author wrote"
    assert SECRET not in (work / "session" / "stdout.jsonl").read_text()


def test_a_run_s_session_cannot_read_a_check_started_while_it_runs(
    tmp_path: Path, install_bin: Path
) -> None:
    """The work root is there before the run starts, so a check made under it later is denied.

    The run withholds a version's tiers, the withheld root and the work root, made with the
    role's root and empty at its start. Once the session's first command is running, a check
    starts: its copy of the held-out tasks appears under the work root. The command, waiting,
    then reads it by a path built at run time, which only the OS layer can refuse; on Linux
    this is bubblewrap's deny of a directory that was there, and empty, when it started. A
    file made just after the copy, outside every withheld root, is read, to show the command
    ran after both were there. (What the run's sentinel then does with the check's new work
    under a root the run withholds is not this row's question.)
    """
    import threading
    import time

    store = tmp_path.resolve() / "private" / "store"
    root = _api("physgate.evaluation.tiers.store.make_role_root")(store / "control")
    version = root / VERSION
    for tier in ("held_out", "validation"):
        (version / tier).mkdir(parents=True)
    works = _api("physgate.evaluation.tiers.store.work_root")(store, "control")
    assert works.is_dir() and not any(works.iterdir()), "the work root is not there, empty"
    held = (version / "held_out", version / "validation", root / "withheld", works)
    copy = works / "check-0" / "worktree" / "tasks.json"
    shown = "a file outside every withheld root, read once the check had started"
    beside = tmp_path.resolve() / "open" / "check-0" / "tasks.json"
    command = (
        f"sleep 4; d=$(printf %s {works.parent}/wo)rk; cat $d/check-0/worktree/tasks.json; "
        f"cat {beside}"
    )

    def check_starts() -> None:
        time.sleep(1.5)
        for place, words in ((copy, SECRET), (beside, shown)):
            place.parent.mkdir(parents=True)
            place.write_text(words)

    started: list[threading.Thread] = []

    def on_request(_thread: str, _cwd: str, done: int) -> None:
        if done == 0 and not started:
            started.append(threading.Thread(target=check_starts, daemon=True))
            started[0].start()

    work = tmp_path / "work"
    with serving(Script(main=[tool("Bash", command=command, description="x"), text("done")])) as (
        api,
        url,
    ):
        api.on_request = on_request
        setup = _setup(install_bin, url, held)
        if isinstance(setup.os_layer, Absent):
            pytest.skip(f"only the OS layer refuses a path built at run time: {setup.os_layer}")
        run_session("Read what you are asked to.", setup, work, cap=10**9)
        told = " ".join(r.last_user for r in api.requests)
    assert started and not started[0].is_alive(), "the check never started"
    assert shown in told, "the command did not run after the check started"
    assert SECRET not in told, "a run's session read a check started while it ran"
