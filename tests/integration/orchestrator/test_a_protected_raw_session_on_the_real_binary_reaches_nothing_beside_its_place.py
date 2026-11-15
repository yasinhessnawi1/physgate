"""A protected trial's raw session on the real binary: nothing beside its own place is reached.

No model is called and no real credential is read: the endpoint is the scripted one, the key its
dummy, the tasks stand-ins. One held-out trial runs through the real raw arm under this
machine's OS layer, in its own directory in the store's withheld work root. Its held-out list is
the run's, with its own place taken out of the work root: the entries beside the way down to it,
as they were when the session was installed, are withheld in the work root's stead.

While the session runs, two marked files are made by the test (not by the session): one in the
harness's directory beside the session's place, which was there at the install, and one in a
new entry of the work root, made after it. The session tries each: by the Read tool, by a shell
the hooks read, by a shell whose path they cannot read off the command, through ``..`` from its
own place, through a link it makes, and, where the volume ignores case, by another case of the
path. The rows hold what reached the session and record what each attempt met
(``record_property``).

Real binary only, on each platform: the carve is otherwise shown at configuration level alone.
"""

from __future__ import annotations

import base64
import contextlib
import os
import secrets
import shutil
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

BASELINE_TESTS = Path(__file__).resolve().parents[2] / "unit" / "evaluation" / "baseline"
if str(BASELINE_TESTS) not in sys.path:
    sys.path.insert(0, str(BASELINE_TESTS))

from baseline_fixtures import PRICES, SCORED, harness_run, run_set, stand_in_store  # noqa: E402

from physgate.evaluation.baseline.runner import (  # noqa: E402
    BASELINE_DIR,
    HARNESS,
    PLACE,
    run_baseline,
    setup_from_run,
)
from physgate.evaluation.observe.cost import load_price_sheet  # noqa: E402
from physgate.evaluation.per_role.arms.raw import RawSetup  # noqa: E402
from physgate.evaluation.tiers.store import withheld_root, work_root  # noqa: E402
from physgate.evaluation.tiers.task import Role, Task  # noqa: E402
from physgate.orchestrator.binaries import measure  # noqa: E402
from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.decompose import binary_version  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import claude_binary, session_search_path  # noqa: E402
from physgate.orchestrator.run_config import RunConfig, endpoint_of, network_enforced  # noqa: E402
from physgate.oslayer.probe import judge_here  # noqa: E402

pytestmark = pytest.mark.integration

NO_CACHE_WRITES = {"cache_creation_input_tokens": 0}
MARKED = "marked.txt"
#: How many attempts reach for the harness's directory beside the place, then for the new entry.
BESIDE, LATE = 6, 3


@dataclass(frozen=True)
class Attempts:
    """One held-out trial on the real binary, and what each of its session's attempts met."""

    #: The tool result of each attempt, in the script's order.
    results: list[str]
    #: What the hidden shells wrote into the session's own worktree, by file name.
    wrote: dict[str, str]
    beside: str
    late: str
    #: Whether the late entry was made while the session ran, and whether the volume ignores case.
    late_made: bool
    case_ignored: bool


@pytest.fixture(scope="module")
def attempts(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Attempts]:
    """The round, made where the suite's integration trees are made (outside every writable one)."""
    named = os.environ.get("PHYSGATE_TEST_ROOT")
    root = (Path(named) if named else Path.home() / ".cache" / "pg-tests") / secrets.token_hex(6)
    root.mkdir(parents=True)
    try:
        install_bin = prepare_install(
            tmp_path_factory.mktemp("install") / "hooks", Path(__file__).resolve().parents[3]
        )
        yield _round(root, install_bin)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _score(_task: Task, _answer: Path) -> dict[str, Any]:
    return dict(SCORED)


def _hidden(path: Path) -> str:
    """A shell word that is ``path`` once the shell runs it, with no path in its text."""
    return f'"$(printf %s {base64.b64encode(str(path).encode()).decode()} | base64 -d)"'


def _steps(cwd: str, beside: Path, late: Path) -> list[dict[str, Any]]:
    """The session's attempts, once its working directory (``<trial>/place/worktree``) is known."""
    dotted = f"{cwd}/../../{HARNESS}/{MARKED}"
    other_case = beside.parent.parent / HARNESS.upper() / MARKED
    return [
        {**step, "usage": NO_CACHE_WRITES}
        for step in (
            # Beside the place, there at the install: the harness's directory.
            tool("Read", file_path=str(beside)),
            tool("Read", file_path=dotted),
            tool("Bash", command=f'cat "{dotted}"; echo DOTTED $?', description="x"),
            tool(
                "Bash",
                command=f'cat {_hidden(beside)} > "{cwd}/hidden.txt" 2>&1; echo HIDDEN $?',
                description="x",
            ),
            tool(
                "Bash",
                command=(
                    f'ln -s {_hidden(beside.parent)} "{cwd}/h"; '
                    f'cat "{cwd}/h/{MARKED}" > "{cwd}/linked.txt" 2>&1; echo LINKED $?'
                ),
                description="x",
            ),
            tool("Read", file_path=str(other_case)),
            # In the work root, made after the install.
            tool("Read", file_path=str(late)),
            tool("Bash", command=f'cat "{late}"; echo LATE $?', description="x"),
            tool(
                "Bash",
                command=f'cat {_hidden(late)} > "{cwd}/late.txt" 2>&1; echo LATE-HIDDEN $?',
                description="x",
            ),
            text("done"),
        )
    ]


def _round(root: Path, install_bin: Path) -> Attempts:
    made = stand_in_store(root / "made")
    task = made.tasks["held_out"][0]
    binary = claude_binary()
    version = binary_version(binary)
    layer = judge_here(claude_version=version, search_path=session_search_path(binary))
    beside_text = f"BESIDE-{secrets.token_hex(8)}"
    late_text = f"LATE-{secrets.token_hex(8)}"
    late_dir = work_root(made.store, "control") / f"late-{secrets.token_hex(4)}"
    planned: list[dict[str, Any]] = []
    seen: dict[str, Path] = {}
    with serving(Script(main=[text("done")])) as (api, url):

        def attempts(_thread: str, cwd: str, done: int) -> dict[str, Any] | None:
            if not planned:
                # The session is installed and running: make the two marked files now.
                trial = Path(cwd).parent.parent
                beside = trial / HARNESS / MARKED
                beside.write_text(beside_text)
                late_dir.mkdir()
                (late_dir / MARKED).write_text(late_text)
                seen.update(trial=trial, beside=beside)
                planned.extend(_steps(cwd, beside, late_dir / MARKED))
            return planned[done] if done < len(planned) else text("done")

        api.on_request = attempts
        recorded: dict[str, Any] = {
            "claude_version": version,
            "os_layer": layer.model_dump(),
            "network_enforced": network_enforced("none", layer),
            "endpoint": endpoint_of(url),
            "auth": "api_key",
            "binary": measure(binary).model_dump(),
        }
        runs = run_set((harness_run(root / "runs", task, made, **recorded), 0))

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

        # The rows read what the trial left, whether the round was refused or not.
        with contextlib.suppress(Exception):
            run_baseline(
                store=made.store,
                role="control",
                version=made.version,
                runs=runs,
                out=root / "round",
                setup_for=setup_for,
                score=_score,
                prices=load_price_sheet(PRICES),
                base_url=url,
                sleep=lambda _s: None,
            )
        results = [r.last_user for r in api.requests if r.tool_results]
    # The protected trial is secured beneath the withheld root once it ends, or left in place.
    secured = list((withheld_root(made.store, "control") / BASELINE_DIR).glob(f"*/*/{PLACE}"))
    places = [*secured, *([seen["trial"] / PLACE] if "trial" in seen else [])]
    worktree = next((p / "worktree" for p in places if (p / "worktree").is_dir()), None)
    wrote = {}
    if worktree is not None:
        for name in ("hidden.txt", "linked.txt", "late.txt"):
            made_file = worktree / name
            wrote[name] = made_file.read_text(errors="replace") if made_file.is_file() else ""
    return Attempts(
        results=results[: BESIDE + LATE],
        wrote=wrote,
        beside=beside_text,
        late=late_text,
        late_made=(late_dir / MARKED).is_file(),
        case_ignored=(late_dir.parent / late_dir.name.upper()).exists(),
    )


def test_a_protected_session_reaches_nothing_beside_its_place_however_it_names_it(
    attempts: Attempts, record_property: Callable[[str, object], None]
) -> None:
    """The harness's directory beside the place is withheld, by ``..``, a link and a case too."""
    for n, result in enumerate(attempts.results[:BESIDE]):
        record_property(f"beside_attempt_{n + 1}", result[-400:])
    record_property("case_ignored", attempts.case_ignored)
    assert len(attempts.results) == BESIDE + LATE, "the session did not make every attempt"
    for result in attempts.results[:BESIDE]:
        assert attempts.beside not in result, "the session read beside its place"
    assert "HIDDEN" in attempts.results[3] and "LINKED" in attempts.results[4]
    # The shells ran and wrote what they met into the session's own worktree: refusals only.
    assert "hidden.txt" in attempts.wrote and "linked.txt" in attempts.wrote, attempts.wrote
    assert attempts.beside not in attempts.wrote["hidden.txt"]
    assert attempts.beside not in attempts.wrote["linked.txt"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Open: a session's withheld list is taken when it is installed, so an entry made in the "
        "store's work root after that is not on it; to be withheld by rule, not by list, or a "
        "second trial's creation refused while a session lives, before the first real round."
    ),
)
def test_an_entry_made_in_the_work_root_after_the_session_s_install_is_not_reached(
    attempts: Attempts, record_property: Callable[[str, object], None]
) -> None:
    for n, result in enumerate(attempts.results[BESIDE:]):
        record_property(f"late_attempt_{n + 1}", result[-400:])
    assert attempts.late_made, "the late entry was not made while the session ran"
    assert len(attempts.results) == BESIDE + LATE, "the session did not make every attempt"
    assert "LATE-HIDDEN" in attempts.results[-1]
    for result in attempts.results[BESIDE:]:
        assert attempts.late not in result, "the session read an entry made after its install"
    assert attempts.late not in attempts.wrote.get("late.txt", "")
