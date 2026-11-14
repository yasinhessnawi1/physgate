"""A baseline round through the real binary, driven by the scripted endpoint: stand-in tasks only.

No model is called and no real credential is read: the endpoint is the scripted one, the key its
dummy. The store is the unit rows' marked stand-in, split by the real split: every field of a
task but its brief carries a marker, so a plain search finds what of a protected task reached a
place. The harness runs are laid out as the loop writes them, recording the binary's own version,
this machine's OS layer and the scripted endpoint. One trial of each tier runs through the real
raw arm (:func:`~physgate.evaluation.per_role.arms.raw.run_raw`), whose scripted session prints
its environment and writes an answer, and a stand-in scorer scores it.

The round is checked end to end: each session was told its brief and nothing else of its task
(every request the binary sent, including the environment it printed back); nothing the round
wrote outside the store's withheld places names a protected task; the protected trials, whole,
lie beneath the withheld root and the visible one in the round's directory; the pair was held
equal (the round would have stopped otherwise); and the record counts one pass in each tier.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

BASELINE_TESTS = Path(__file__).resolve().parents[2] / "unit" / "evaluation" / "baseline"
if str(BASELINE_TESTS) not in sys.path:
    sys.path.insert(0, str(BASELINE_TESTS))

from baseline_fixtures import (  # noqa: E402
    PRICES,
    SCORED,
    StandInStore,
    harness_run,
    run_set,
    stand_in_store,
)
from task_fixtures import controller  # noqa: E402

from physgate.evaluation.baseline.record import (  # noqa: E402
    BASELINE_RECORD,
    TIERS_RECORD,
    BaselineRecord,
)
from physgate.evaluation.baseline.runner import (  # noqa: E402
    BASELINE_DIR,
    TRIALS,
    run_baseline,
    setup_from_run,
)
from physgate.evaluation.observe.cost import load_price_sheet  # noqa: E402
from physgate.evaluation.per_role.arms.raw import RawSetup  # noqa: E402
from physgate.evaluation.tiers.store import role_root, version_dir, withheld_root  # noqa: E402
from physgate.evaluation.tiers.task import Role, Task  # noqa: E402
from physgate.orchestrator.binaries import measure  # noqa: E402
from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.decompose import binary_version  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import claude_binary, session_search_path  # noqa: E402
from physgate.orchestrator.run_config import RunConfig, endpoint_of, network_enforced  # noqa: E402
from physgate.oslayer.probe import judge_here  # noqa: E402

pytestmark = pytest.mark.integration

TIERS = ("visible", "validation", "held_out")
#: What the session prints, so its environment comes back to the endpoint as a tool result.
SHOW_ENVIRONMENT = "env; echo ENVIRONMENT-SHOWN"
NO_CACHE_WRITES = {"cache_creation_input_tokens": 0}


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(
        tmp_path_factory.mktemp("install") / "hooks", Path(__file__).resolve().parents[3]
    )


def _score(task: Task, answer: Path) -> dict[str, Any]:
    assert json.loads(answer.read_text()) == controller()
    return dict(SCORED)


def _where(path: Path, root: Path, data: bytes, forbidden: list[str]) -> str:
    """Which file holds a marker, and the text around its first one."""
    found = next(m for m in forbidden if m.encode() in data).encode()
    at = data.index(found)
    return f"{path.relative_to(root)} holds a protected task: {data[max(0, at - 160) : at + 40]!r}"


def _files(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def _snapshot(path: Path) -> bool:
    """Whether ``path`` is the hook sentinel's snapshot of the withheld roots.

    The snapshot lists each entry beneath the withheld roots by path, so a protected task's
    directory, and so its id. It lies in the hook layer's own state beneath the session's
    directories, which the session's tools are refused (``sessions_root``): no input the session
    is given. The rows below set it aside by name and hold it apart in a row of its own.
    """
    return path.name == "baseline.json" and path.parent.name == "sentinel" and "state" in path.parts


@dataclass(frozen=True)
class Round:
    """One round on the real binary, and what was seen of it."""

    made: StandInStore
    tasks: list[Task]
    forbidden: list[str]
    record: BaselineRecord
    out: Path
    told: list[str]
    failures: list[str]
    keys: list[tuple[bool, bool]]
    #: Every file the round wrote or changed outside the store's withheld places.
    written: dict[Path, bytes]


@pytest.fixture(scope="module")
def round_(install_bin: Path) -> Iterator[Round]:
    """The round, made where the suite's integration trees are made.

    Outside every place the OS layer makes writable (``tests/conftest.py``), since the hook
    installer refuses a session there.
    """
    named = os.environ.get("PHYSGATE_TEST_ROOT")
    root = (Path(named) if named else Path.home() / ".cache" / "pg-tests") / secrets.token_hex(6)
    root.mkdir(parents=True)
    try:
        yield _round(root, install_bin)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _round(root: Path, install_bin: Path) -> Round:
    made = stand_in_store(root / "made", marked=True)
    tasks = [made.tasks[tier][0] for tier in TIERS]
    protected = tasks[1:]
    forbidden = [t.id.removeprefix("control.") for t in protected]
    forbidden += [str(t.canary) for t in protected]
    binary = claude_binary()
    version = binary_version(binary)
    layer = judge_here(claude_version=version, search_path=session_search_path(binary))
    # No cache writes: the scripted endpoint gives no split of them by time to live, which the
    # price sheet asks of every write it prices.
    steps = [
        {**step, "usage": NO_CACHE_WRITES}
        for step in (
            tool("Bash", command=SHOW_ENVIRONMENT, description="x"),
            tool("Write", file_path="{cwd}/answer.json", content=json.dumps(controller())),
            text("done"),
        )
    ]
    out = root / "round"
    with serving(Script(main=steps)) as (api, url):
        recorded: dict[str, Any] = {
            "claude_version": version,
            "os_layer": layer.model_dump(),
            "network_enforced": network_enforced("none", layer),
            "endpoint": endpoint_of(url),
            "auth": "api_key",
            # The build the raw sessions run: the harness runs must have recorded it.
            "binary": measure(binary).model_dump(),
        }
        runs = run_set(*((harness_run(root / "runs", t, made, **recorded), 0) for t in tasks))

        def setup_for(config: RunConfig, role: Role) -> RawSetup:
            return setup_from_run(
                config,
                role,
                binary=binary,
                credential=Credential("api_key", DUMMY_KEY),
                install_bin=install_bin,
                os_layer=layer,
                role_python=None,
                base_url=url,
            )

        before = _files(root)
        record = run_baseline(
            store=made.store,
            role="control",
            version=made.version,
            runs=runs,
            out=out,
            setup_for=setup_for,
            score=_score,
            prices=load_price_sheet(PRICES),
            base_url=url,
            sleep=lambda _s: None,
        )
        told = [r.last_user + "\n" + r.after_user for r in api.requests]
        keys = [(r.carried_dummy_key, r.carried_other_credential) for r in api.requests]
        failures = list(api.failures)
    directory = version_dir(made.store, "control", made.version)
    withheld = [withheld_root(made.store, "control"), directory / "validation"]
    withheld.append(directory / "held_out")
    written = {
        p: data
        for p, data in _files(root).items()
        if before.get(p) != data and not any(p.is_relative_to(w) for w in withheld)
    }
    return Round(made, tasks, forbidden, record, out, told, failures, keys, written)


def test_a_round_on_the_real_binary_tells_each_session_its_brief_alone_and_keeps_protected_trials_in_the_store(  # noqa: E501
    round_: Round,
) -> None:
    made, forbidden, record, out = round_.made, round_.forbidden, round_.record, round_.out
    assert round_.failures == []
    assert round_.keys and all(dummy and not other for dummy, other in round_.keys)
    # What each session was told: its brief, then what its own tools printed back.
    for task in round_.tasks:
        assert any(task.brief in t for t in round_.told), "a session was not told its brief"
    shown = sum("ENVIRONMENT-SHOWN" in t for t in round_.told)
    assert shown >= len(round_.tasks), "no environment came back"
    assert not [m for m in forbidden for t in round_.told if m in t]
    # The round: one pass in each tier, the pair held equal or it would have stopped.
    for tier in TIERS:
        counts = record.counts[tier]  # type: ignore[index]
        assert (counts.trials, counts.passed, counts.excluded) == (1, 1, 0), tier
    # Protected trials, whole, beneath the withheld root; their sessions' own files hold nothing
    # of their tasks but the sentinel's snapshot; the visible one in the round's directory.
    beneath = withheld_root(made.store, "control") / BASELINE_DIR / record.id
    assert len(list(beneath.glob("*/harness/raw.json"))) == 2
    sessions = [
        p
        for trial in beneath.iterdir()
        if trial.is_dir()
        for p in (trial / "place").rglob("*")
        if p.is_file() and not p.is_symlink()
    ]
    assert any(p.name == "stdout.jsonl" for p in sessions)
    assert any(_snapshot(p) for p in sessions), "the snapshot is not where it is set aside"
    for path in (p for p in sessions if not _snapshot(p)):
        data = path.read_bytes()
        assert not [m for m in forbidden if m.encode() in data], _where(
            path, beneath, data, forbidden
        )
    assert len((out / TRIALS).read_text().splitlines()) == 1
    # The round's directory holds the visible trial alone: a protected one was never made there.
    (visible,) = list((out / "work").iterdir())
    visible_ids = {t.id for t in round_.tasks if t.tier == "visible"}
    assert json.loads((visible / "harness" / "raw.json").read_text())["task"] in visible_ids
    assert not list((role_root(made.store, "control") / "work").iterdir())
    assert not list(role_root(made.store, "control").glob("*.working"))
    assert {out / TRIALS, out / BASELINE_RECORD, out / TIERS_RECORD} <= set(round_.written)
    for path, data in round_.written.items():
        if not _snapshot(path):
            assert not [m for m in forbidden if m.encode() in data], f"{path} names a task"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Open, and to be closed before the first real round: the hook sentinel's change-detection "
        "snapshot of the withheld roots keeps, for each protected entry, its path (and so a "
        "protected task's id), its file name, size, mtime and sha256, though none of its content; "
        "a visible trial's raw session leaves that snapshot in the round's visible directory, and "
        "every harness role session takes the same snapshot in its run directory."
    ),
)
def test_no_session_s_sentinel_snapshot_in_a_visible_place_names_a_protected_task(
    round_: Round,
) -> None:
    snapshots = [(p, d) for p, d in round_.written.items() if _snapshot(p)]
    assert snapshots, "the visible trial's session left no snapshot"
    for path, data in snapshots:
        assert not [m for m in round_.forbidden if m.encode() in data], f"{path} names a task"
