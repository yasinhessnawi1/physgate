"""A protected trial's raw session on the real binary: nothing beside its worktree is reached.

No model is called and no real credential is read: the endpoint is the scripted one, the key its
dummy, the tasks stand-ins. One held-out trial runs through the real raw arm under this
machine's OS layer, in its own directory in the store's withheld work root. The session is
withheld the work root whole, by rule, but for its worktree in its own place there, on both
layers: the hooks' exception and the OS layer's opening are the worktree alone.

While the session runs, the test (not the session, not the runner) marks four places: the
harness's directory beside the session's place, there at the install; a new entry in the work
root; a new entry in the trial's directory beside the place; and a new entry inside the place
itself, beside the worktree. Each is a file holding a mark of its own. The session then tries
each, as the Read tool, as a shell the hooks read, as a shell whose path they cannot read off the
command, through ``..`` from its own worktree, through a symbolic link and a hard link it makes,
by moving its own worktree and reading through the new name, by writing there, and, only where
the volume ignores case, by another case of the path. The runner is also asked for a second
trial's place while the session lives, and refuses it.

Every attempt is held to what it met, never only to the mark's absence: a hook refusal (its
rule named), an OS-layer denial (its error text, in a shell whose read of the worktree's own file
succeeded in the same command), or the content. Before the attempts, and again after the last
one while the session still runs, the test itself reads the mark at the very path each attempt
uses, so a wrong ``..`` depth, a path that is not there or a mark taken away between cannot pass
for a denial. The whole record, per attempt (``record_property``, and a JSON report where
``PHYSGATE_OSLAYER_REPORT`` names a directory), is the measurement of the macOS rule order and
the Linux bind order: it says, per platform, which layer met each attempt.

Real binary only, on each platform: the carve is otherwise shown at configuration level alone.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import secrets
import shutil
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

BASELINE_TESTS = Path(__file__).resolve().parents[2] / "unit" / "evaluation" / "baseline"
if str(BASELINE_TESTS) not in sys.path:
    sys.path.insert(0, str(BASELINE_TESTS))

from baseline_fixtures import PRICES, SCORED, harness_run, run_set, stand_in_store  # noqa: E402

from physgate.evaluation.baseline import runner  # noqa: E402
from physgate.evaluation.baseline.runner import (  # noqa: E402
    BASELINE_DIR,
    HARNESS,
    PLACE,
    BaselineError,
    run_baseline,
    setup_from_run,
)
from physgate.evaluation.observe.cost import load_price_sheet  # noqa: E402
from physgate.evaluation.per_role.arms.raw import RawSetup, run_raw  # noqa: E402
from physgate.evaluation.tiers.store import work_root  # noqa: E402
from physgate.evaluation.tiers.task import Role, Task  # noqa: E402
from physgate.hooks import reasons  # noqa: E402
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
#: The worktree's own file, written by the session first and read back by every later shell.
OWN = "own.txt"
#: The hook layer's refusals, by the rule's name: each reason's opening words, as a tool result
#: quotes them.
HOOK_RULES = {
    name: " ".join(value.split())[:60]
    for name, value in vars(reasons).items()
    if name.endswith("_REASON") and isinstance(value, str)
}
#: An OS-layer denial, by the class of its error text. ``hidden`` (no such file) is a denial
#: only because the test read the mark at that same path itself, before and after.
OS_DENIALS = {
    "operation not permitted": "not_permitted",
    "permission denied": "permission_denied",
    "read-only file system": "read_only",
    "no such file or directory": "hidden",
    # Linux: the worktree is a mount point in the sandbox, which no rename moves.
    "device or resource busy": "mount_point",
}
#: What the binary says to a Read of a file it has read already, unchanged: the content reached it.
ALREADY_READ = "file unchanged since your last Read"
_RC = re.compile(r"@@rc=(\d+)")
_CONTROL = re.compile(r"@@control=(\S*)")


@dataclass
class Attempt:
    """One thing the session tries, and what the test knows of its target."""

    group: str
    label: str
    step: dict[str, Any]
    #: The path the attempt uses, as it spells it (``..`` kept), or the link's target for an
    #: attempt through a link the session makes: the test reads the mark there itself.
    path: str | None
    #: The mark at ``path``; empty for an attempt with no file to read (a move, a new file).
    mark: str = ""
    #: Whether a shell attempt reads the worktree's own file in the same command (a control).
    shell: bool = False
    #: For an attempt that makes or moves a file (no mark to read): the directory it would land
    #: in, which the test proves is there itself, so "no such file" there is a denial.
    parent: str | None = None
    #: The test's own read of the mark at ``path``, before the attempts and after the last one.
    before: bool | None = None
    after: bool | None = None
    result: str = ""
    met: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Round:
    """One held-out trial on the real binary, and every attempt its session made."""

    attempts: list[Attempt]
    own: str
    own_result: str
    late_refused: str
    late_made: bool
    case_ignored: bool
    #: Each written-to mark as the test read it after the round, by label.
    marks_after: dict[str, str]
    #: Each file a write attempt would have made, and whether it is there after the round.
    made_after: dict[str, bool]
    record: dict[str, Any]


@pytest.fixture(scope="module")
def trial(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Round]:
    """The round, made where the suite's integration trees are made (outside every writable one)."""
    named = os.environ.get("PHYSGATE_TEST_ROOT")
    root = (Path(named) if named else Path.home() / ".cache" / "pg-tests") / secrets.token_hex(6)
    root.mkdir(parents=True)
    try:
        install_bin = prepare_install(
            tmp_path_factory.mktemp("install") / "hooks", Path(__file__).resolve().parents[3]
        )
        made = _round(root, install_bin)
        _report(made.record)
        yield made
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _report(record: dict[str, Any]) -> None:
    where = os.environ.get("PHYSGATE_OSLAYER_REPORT")
    if where:
        Path(where).mkdir(parents=True, exist_ok=True)
        name = f"withheld-whole-attempts-{sys.platform}.json"
        (Path(where) / name).write_text(json.dumps(record, indent=1))


def _score(_task: Task, _answer: Path) -> dict[str, Any]:
    return dict(SCORED)


def _hidden(path: Path | str) -> str:
    """A shell word that is ``path`` once the shell runs it, with no path in its text."""
    return f'"$(printf %s {base64.b64encode(str(path).encode()).decode()} | base64 -d)"'


def _shell(cwd: str, body: str) -> dict[str, Any]:
    """A Bash step: ``body``, its exit status, and a read of the worktree's own file after it."""
    command = (
        f'{body}; echo "@@rc=$?"; '
        f"printf '@@control=%s\\n' \"$(cat \"{cwd}/{OWN}\" 2>&1 | tr -d ' ')\""
    )
    return tool("Bash", command=command, description="x")


def _reads(group: str, cwd: str, target: Path, dotted: str, mark: str) -> list[Attempt]:
    """Read, a shell the hooks read, a hidden shell and ``..``: four ways to one marked file."""
    return [
        Attempt(group, "read", tool("Read", file_path=str(target)), str(target), mark),
        Attempt(
            group,
            "shell",
            _shell(cwd, f'cat "{target}" 2>&1'),
            str(target),
            mark,
            shell=True,
        ),
        Attempt(
            group,
            "hidden_shell",
            _shell(cwd, f"cat {_hidden(target)} 2>&1"),
            str(target),
            mark,
            shell=True,
        ),
        Attempt(group, "read_dotted", tool("Read", file_path=dotted), dotted, mark),
        Attempt(
            group,
            "hidden_shell_dotted",
            _shell(cwd, f"cat {_hidden(dotted)} 2>&1"),
            dotted,
            mark,
            shell=True,
        ),
    ]


def _attempts(
    cwd: str, places: dict[str, Path], marks: dict[str, str], case_ignored: bool
) -> list[Attempt]:
    """Every attempt, once the session's working directory (``<trial>/place/worktree``) is known."""
    beside, late = places["beside"], places["late"]
    by_place, in_place = places["by_the_place"], places["in_the_place"]
    found: list[Attempt] = []
    # Beside the place, there at the install: the harness's directory.
    found += _reads("beside", cwd, beside, f"{cwd}/../../{HARNESS}/{MARKED}", marks["beside"])
    found.append(
        Attempt(
            "beside",
            "symlink_shell",
            _shell(
                cwd, f'ln -s {_hidden(beside.parent)} "{cwd}/h" 2>&1; cat "{cwd}/h/{MARKED}" 2>&1'
            ),
            str(beside),
            marks["beside"],
            shell=True,
        )
    )
    # In the work root, made by the test after the install: on no list taken then.
    found += _reads("late", cwd, late, f"{cwd}/../../../{late.parent.name}/{MARKED}", marks["late"])
    found += [
        Attempt(
            "late",
            "cd_dotted_shell",
            _shell(cwd, f'cd "{cwd}" && cat ../../../{late.parent.name}/{MARKED} 2>&1'),
            f"{cwd}/../../../{late.parent.name}/{MARKED}",
            marks["late"],
            shell=True,
        ),
        Attempt(
            "late",
            "symlink_shell",
            _shell(
                cwd, f'ln -s {_hidden(late.parent)} "{cwd}/l" 2>&1; cat "{cwd}/l/{MARKED}" 2>&1'
            ),
            str(late),
            marks["late"],
            shell=True,
        ),
        Attempt(
            "late",
            "read_symlink",
            tool("Read", file_path=f"{cwd}/l/{MARKED}"),
            str(late),
            marks["late"],
        ),
    ]
    if case_ignored:
        for group, target in (("beside", beside), ("late", late)):
            other = target.parent.parent / target.parent.name.upper() / MARKED
            found.append(
                Attempt(
                    group,
                    "read_other_case",
                    tool("Read", file_path=str(other)),
                    str(other),
                    marks[group],
                )
            )
    # In the trial's directory, beside the place, made after the install.
    found += _reads(
        "by_the_place",
        cwd,
        by_place,
        f"{cwd}/../../{by_place.parent.name}/{MARKED}",
        marks["by_the_place"],
    )
    # Inside the place, beside the worktree, made after the install: both layers open the
    # worktree alone, never the place.
    found += _reads(
        "in_the_place",
        cwd,
        in_place,
        f"{cwd}/../{in_place.parent.name}/{MARKED}",
        marks["in_the_place"],
    )
    # The session's own directory, beside the worktree in its place: its records, its login.
    own_session = places["own_session"]
    found += [
        Attempt(
            "own_session",
            "read",
            tool("Read", file_path=str(own_session)),
            str(own_session),
            marks["own_session"],
        ),
        Attempt(
            "own_session",
            "hidden_shell",
            _shell(cwd, f"cat {_hidden(own_session)} 2>&1"),
            str(own_session),
            marks["own_session"],
            shell=True,
        ),
    ]
    # A hard link the session makes in its worktree to a marked file outside it, then read.
    for n, (group, target) in enumerate(
        (("late", late), ("by_the_place", by_place), ("in_the_place", in_place))
    ):
        link = f"{cwd}/hard-{n}"
        found.append(
            Attempt(
                "hard_link",
                f"{group}_link_shell",
                _shell(cwd, f'ln {_hidden(target)} "{link}" 2>&1; cat "{link}" 2>&1'),
                str(target),
                marks[group],
                shell=True,
                extra={"link": link},
            )
        )
        found.append(
            Attempt(
                "hard_link",
                f"{group}_link_read",
                tool("Read", file_path=link),
                str(target),
                marks[group],
                extra={"link": link, "made_by": f"{group}_link_shell"},
            )
        )
    # A write to each late entry: the marked file itself, and a new file beside it.
    for group, target in (("late", late), ("by_the_place", by_place), ("in_the_place", in_place)):
        new = target.parent / "new.txt"
        found += [
            Attempt(
                "write",
                f"{group}_hidden_overwrite",
                _shell(cwd, f"echo OVERWRITTEN > {_hidden(target)} 2>&1"),
                str(target),
                marks[group],
                shell=True,
            ),
            Attempt(
                "write",
                f"{group}_hidden_new",
                _shell(cwd, f"echo NEW > {_hidden(new)} 2>&1"),
                None,
                shell=True,
                parent=str(new.parent),
                extra={"made": str(new)},
            ),
            Attempt(
                "write",
                f"{group}_write_tool",
                tool("Write", file_path=str(target), content="OVERWRITTEN"),
                str(target),
                marks[group],
            ),
        ]
    # Last, since one that succeeded would move the working directory: the worktree moved, then
    # a read through its new name (its own file, and the late entry through ``..``).
    place = Path(cwd).parent
    for label, new_name in (
        ("in_the_place", f"{place}/moved"),
        ("to_the_shared_temp", f"/tmp/pg-moved-{secrets.token_hex(4)}"),
    ):
        found.append(
            Attempt(
                "move",
                f"{label}_hidden_mv",
                _shell(
                    cwd,
                    f'mv {_hidden(cwd)} {_hidden(new_name)} 2>&1; echo "@@mv=$?"; '
                    f'cat "{new_name}/{OWN}" 2>&1; '
                    f'cat "{new_name}/../../../{late.parent.name}/{MARKED}" 2>&1',
                ),
                None,
                shell=True,
                parent=str(Path(new_name).parent),
                extra={"moved_to": new_name},
            )
        )
    found.append(
        Attempt(
            "move",
            "in_the_place_mv",
            _shell(cwd, f'mv "{cwd}" "{place}/moved-seen" 2>&1; echo "@@mv=$?"'),
            None,
            shell=True,
            parent=str(place),
            extra={"moved_to": f"{place}/moved-seen"},
        )
    )
    return found


def _test_reads(path: str | None, mark: str) -> bool | None:
    """Whether the test itself reads ``mark`` at ``path``, spelt as the attempt spells it."""
    if path is None or not mark:
        return None
    try:
        with open(path, encoding="utf-8") as found:  # noqa: PTH123 - the path exactly as spelt
            return found.read() == mark
    except OSError:
        return False


def _met(attempt: Attempt, own: str) -> str:
    """What the attempt met: ``reached``, ``hook:<rule>``, ``os:<class>``, or what else it was."""
    told = attempt.result
    if attempt.mark and attempt.mark in told:
        return "reached"
    if not attempt.shell and ALREADY_READ in told:
        return "reached:read before, unchanged"
    flat = " ".join(told.split())
    for rule, opening in HOOK_RULES.items():
        if opening and opening in flat:
            return f"hook:{rule}"
    if attempt.shell:
        rc = _RC.search(told)
        control = _CONTROL.search(told)
        if rc is None:
            return f"other:the shell did not run ({flat[-160:]})"
        if control is None or control.group(1) != own:
            return f"other:the worktree's own file was not read in the same shell ({flat[-160:]})"
        if attempt.group == "move":
            moved = re.search(r"@@mv=(\d+)", told)
            if moved is None or moved.group(1) == "0":
                return "reached:moved"
        elif rc.group(1) == "0":
            return f"other:the command succeeded ({flat[-160:]})"
        for text_, kind in OS_DENIALS.items():
            if text_ in told.casefold():
                return f"os:{kind}"
        return f"other:no denial text ({flat[-160:]})"
    return f"other:{flat[-200:]}"


def _round(root: Path, install_bin: Path) -> Round:
    made = stand_in_store(root / "made")
    task = made.tasks["held_out"][0]
    binary = claude_binary()
    version = binary_version(binary)
    layer = judge_here(claude_version=version, search_path=session_search_path(binary))
    own = f"OWN-{secrets.token_hex(8)}"
    marks = {
        g: f"{g.upper()}-{secrets.token_hex(8)}"
        for g in ("beside", "late", "by_the_place", "in_the_place")
    }
    late_round, late_name = "late", "0009-1"
    asked = work_root(made.store, "control") / f"{BASELINE_DIR}-{late_round}-{late_name}"
    late_dir = work_root(made.store, "control") / f"late-{secrets.token_hex(4)}"
    state: dict[str, Any] = {"refused": ""}
    planned: list[Attempt] = []
    places: dict[str, Path] = {}
    with serving(Script(main=[text("done")])) as (api, url):

        def attempts(_thread: str, cwd: str, done: int) -> dict[str, Any] | None:
            if not planned and "steps" not in state:
                # The session is installed and running: the test marks the four places (not the
                # session, not the runner) and asks the runner for a second trial's place, refused.
                trial = Path(cwd).parent.parent
                places.update(
                    beside=trial / HARNESS / MARKED,
                    late=late_dir / MARKED,
                    by_the_place=trial / f"late-{secrets.token_hex(4)}" / MARKED,
                    in_the_place=trial / PLACE / f"late-{secrets.token_hex(4)}" / MARKED,
                )
                for group, path in places.items():
                    if group != "beside":  # made before the install, by the arm below
                        path.parent.mkdir(mode=0o700, exist_ok=True)
                        path.write_text(marks[group])
                # The session's own directory, beside its worktree: its records and its login.
                places["own_session"] = Path(cwd).parent / "session" / "process.json"
                marks["own_session"] = _read_or_empty(str(places["own_session"]))
                try:
                    with runner.trial_place(made.store, "control", late_round, late_name):
                        state["refused"] = ""
                except BaselineError as exc:
                    state["refused"] = str(exc.context.get("refused_because"))
                state["case_ignored"] = (late_dir.parent / late_dir.name.upper()).exists()
                planned.extend(_attempts(cwd, places, marks, state["case_ignored"]))
                for attempt in planned:
                    attempt.before = _test_reads(attempt.path, attempt.mark)
                    if attempt.parent is not None:
                        attempt.extra["parent_there"] = os.path.isdir(attempt.parent)
                state["steps"] = [
                    _shell(cwd, f'echo {own} > "{cwd}/{OWN}" && cat "{cwd}/{OWN}"'),
                    *(a.step for a in planned),
                ]
                # Where the writes begin (one that went through would change a mark).
                state["writes"] = 1 + next(
                    n for n, a in enumerate(planned) if a.group in {"write", "move"}
                )
            steps: list[dict[str, Any]] = state["steps"]
            if done >= state["writes"] and "after" not in state:
                # Every read has been answered, no write tried yet, and the session still runs:
                # the test reads every mark again at the path each attempt used.
                state["after"] = True
                for attempt in planned:
                    if attempt.group not in {"write", "move"}:
                        attempt.after = _test_reads(attempt.path, attempt.mark)
            step = steps[done] if done < len(steps) else text("done")
            return {**step, "usage": NO_CACHE_WRITES}

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

        def arm(task: Task, given: RawSetup, work: Path, **kw: Any) -> dict[str, Any]:  # noqa: ANN401
            # The harness's directory beside the place is marked before the session is installed:
            # an entry there at the install, which the hooks' list names and keeps as it was.
            harness = kw["harness"]
            (harness / MARKED).write_text(marks["beside"])
            return run_raw(task, given, work, **kw)

        # The rows read what the trial left, whether the round was refused or not.
        with contextlib.suppress(Exception):
            run_baseline(
                arm=arm,
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
    own_result = results[0] if results else ""
    for attempt, result in zip(planned, results[1:], strict=False):
        attempt.result = result
        attempt.met = _met(attempt, own)
    by_label = {(a.group, a.label): a for a in planned}
    for attempt in planned:
        made_by = by_label.get((attempt.group, str(attempt.extra.get("made_by"))))
        if (
            made_by is not None
            and made_by.met.startswith("os:")
            and not os.path.lexists(str(attempt.extra["link"]))
            and "File does not exist" in attempt.result
        ):
            # The link was never made (its shell met the OS layer's denial): nothing to read.
            attempt.met = f"{made_by.met} (no link was made to read)"
    marks_after = {
        f"{a.group}/{a.label}": _read_or_empty(a.path)
        for a in planned
        if a.group == "write" and a.path
    }
    # The late entry in the work root is not moved with the trial: read as it is now. The others
    # moved with the trial beneath the withheld root; each was read before that (``after``).
    made_after = {
        str(a.extra["made"]): os.path.lexists(str(a.extra["made"]))
        for a in planned
        if "made" in a.extra
    }
    record = {
        "platform": sys.platform,
        "claude_version": version,
        "case_variant": "run"
        if state.get("case_ignored")
        else "not run: the volume is case-sensitive",
        "own_write_and_read_back": own in own_result,
        "attempts": [
            {
                "group": a.group,
                "attempt": a.label,
                "path": a.path,
                "test_read_before": a.before,
                "test_read_after": a.after,
                "met": a.met,
                **({"tail": a.result[-300:]} if not a.met.startswith(("hook:", "os:")) else {}),
            }
            for a in planned
        ],
    }
    return Round(
        attempts=planned,
        own=own,
        own_result=own_result,
        late_refused=state["refused"],
        late_made=asked.exists(),
        case_ignored=bool(state.get("case_ignored")),
        marks_after=marks_after,
        made_after=made_after,
        record=record,
    )


def _read_or_empty(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def _held(trial: Round, group: str, record_property: Callable[[str, object], None]) -> None:
    """Every attempt of ``group`` was made, at a path the test reads itself, and met a refusal."""
    found = [a for a in trial.attempts if a.group == group]
    for a in found:
        record_property(f"{group}/{a.label}", a.met)
    record_property("platform", sys.platform)
    record_property("case_variant", trial.record["case_variant"])
    assert found, f"no attempt of {group} was planned"
    assert trial.own in trial.own_result, (
        "the session could not write and read back its own worktree's file",
        trial.own_result[-300:],
    )
    for a in found:
        assert a.result, f"{group}/{a.label}: the session did not make the attempt"
        if a.path is not None:
            # Every attempt with a file to read has a mark there: an empty one proves nothing.
            assert a.mark, f"{group}/{a.label}: no mark to read at {a.path}"
        if a.parent is not None:
            assert a.extra.get("parent_there"), (
                f"{group}/{a.label}: the test cannot find {a.parent} itself"
            )
        if a.path is not None and a.mark:
            assert a.before, f"{group}/{a.label}: the test cannot read the mark at {a.path} itself"
            if a.after is not None:
                assert a.after, f"{group}/{a.label}: the mark at {a.path} was gone by the end"
    reached = [(a.label, a.met) for a in found if a.met.startswith("reached")]
    assert not reached, f"{group}: the session reached {reached}"
    unclassed = [(a.label, a.met) for a in found if not a.met.startswith(("hook:", "os:"))]
    assert not unclassed, f"{group}: attempts that met neither a refusal nor a denial: {unclassed}"


def test_the_harness_s_directory_beside_the_place_is_reached_by_no_route(
    trial: Round, record_property: Callable[[str, object], None]
) -> None:
    _held(trial, "beside", record_property)


def test_an_entry_made_in_the_work_root_after_the_install_is_reached_by_no_route(
    trial: Round, record_property: Callable[[str, object], None]
) -> None:
    """Withheld by rule, not by a list taken at install: Read, shells, ``..``, a link, a case."""
    _held(trial, "late", record_property)


def test_an_entry_made_beside_the_place_after_the_install_is_reached_by_no_route(
    trial: Round, record_property: Callable[[str, object], None]
) -> None:
    _held(trial, "by_the_place", record_property)


def test_an_entry_made_inside_the_place_beside_the_worktree_is_reached_by_no_route(
    trial: Round, record_property: Callable[[str, object], None]
) -> None:
    """The hook layer allows the whole place; the OS layer opens the worktree alone in it."""
    _held(trial, "in_the_place", record_property)


def test_the_session_s_own_directory_beside_its_worktree_is_reached_by_no_route(
    trial: Round, record_property: Callable[[str, object], None]
) -> None:
    """Its login and its records lie in its place, beside the worktree."""
    _held(trial, "own_session", record_property)


def test_a_hard_link_the_session_makes_to_a_marked_file_reaches_nothing(
    trial: Round, record_property: Callable[[str, object], None]
) -> None:
    _held(trial, "hard_link", record_property)


def test_a_write_to_an_entry_made_after_the_install_changes_nothing(
    trial: Round, record_property: Callable[[str, object], None]
) -> None:
    _held(trial, "write", record_property)
    changed = {k: v for k, v in trial.marks_after.items() if "OVERWRITTEN" in v}
    assert not changed, f"a write reached a marked file: {sorted(changed)}"
    new = sorted(k for k, there in trial.made_after.items() if there)
    assert not new, f"a write made a file in a late entry: {new}"


def test_the_session_cannot_move_its_own_worktree_and_read_through_the_new_name(
    trial: Round, record_property: Callable[[str, object], None]
) -> None:
    _held(trial, "move", record_property)


def test_no_second_trial_is_made_in_the_work_root_while_the_session_lives(
    trial: Round, record_property: Callable[[str, object], None]
) -> None:
    record_property("late_refused", trial.late_refused)
    assert trial.late_refused == "session_lives", "a second trial was made beside the session"
    assert not trial.late_made, "the refused creation made something in the work root"
