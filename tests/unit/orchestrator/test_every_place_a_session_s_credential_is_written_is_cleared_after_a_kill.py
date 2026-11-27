"""Every place a session's credential is written is found and cleared after a kill.

A session's credential is a file in its own place for as long as it runs, and the session's end
removes it; a stop signal removes it too. A process killed outright removes nothing, so the next
command on the run, or the next start of its round, clears the place of every session nothing
runs as any more. That sweep used to visit the run's role sessions and its reviewers alone: a
decomposition killed outright while its planner's call ran left the planner's login file in the
decomposition's call directory (round one's, its retry's, a later round's), and nothing removed
it, since a cut decomposition's directory is never decomposed again. Now one function finds every
place of every kind, and every clean-up after a kill clears what it finds.

Every credential here is a dummy, and no file's content is read but to see that it is gone.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from physgate.cli import main
from physgate.evaluation import harness_round
from physgate.evaluation.per_role.arms import raw
from physgate.orchestrator import cli as orchestrator_cli
from physgate.orchestrator import credentials, dispatch, stop_signals
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.credentials import LOGIN_FILE, write_login
from physgate.orchestrator.design_rounds import retry_dir, round_dir
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.stop_signals import credential_places, remove_left_credentials

DUMMY = "dummy-not-a-credential"


def _logins(top: Path) -> list[str]:
    """Every login file beneath ``top``, by its path beneath it."""
    return sorted(str(p.relative_to(top)) for p in top.rglob(LOGIN_FILE))


def _planner_places(run_dir: Path) -> list[Path]:
    """The call directories a decomposition's planner runs in: round one's, retries, round two's."""
    return [
        round_dir(run_dir, 1),
        retry_dir(run_dir, 1),
        round_dir(run_dir, 2),
        retry_dir(run_dir, 2),
    ]


def _killed_decomposition(base: Path) -> Path:
    """A decomposition's directory as a kill inside each of its planner's calls leaves it."""
    run_dir = base / "runs" / "round-a" / "0001-1"
    for where in _planner_places(run_dir):
        write_login(where / "config", DUMMY, place="plan_call")
    (run_dir / "review").mkdir()
    return run_dir


def _next_command(base: Path, run_dir: Path, command: str) -> None:
    """What comes after the kill: the round's restart, or a command a person types."""
    if command == "the round's restart":
        harness_round._deal_with(base / "place", 1, 1, run_dir)
        return
    if command == "decompose":
        (base / "p.json").write_text("{}\n")
        argv = ["decompose", str(base / "brief.md"), "--seed", "1", "--run-id", "r"]
        argv += ["--params", str(base / "p.json"), "--target", str(base / "t")]
        argv += ["--review-root", str(run_dir / "review")]
    else:
        argv = [command, "--run-dir", str(run_dir), "--target", str(base / "target")]
        argv += ["--install", str(base / "install"), "--review-root", str(run_dir / "review")]
    # Each refuses the directory for its own reason (no parameters, no run): the sweep runs first.
    main([*argv, "--run-dir", str(run_dir)] if command == "decompose" else argv, Registrations())


@pytest.mark.parametrize("command", ["the round's restart", "run", "resume", "decompose"])
def test_a_decomposition_killed_while_its_planner_ran_leaves_no_credential_after_the_next_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    base = Path(os.path.realpath(tmp_path))
    run_dir = _killed_decomposition(base)
    assert len(_logins(run_dir)) == 4
    _next_command(base, run_dir, command)
    assert _logins(run_dir) == [], f"{command}: the planner's login file was left"


def test_a_planner_still_running_after_its_decompose_was_killed_is_stopped_and_its_login_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    base = Path(os.path.realpath(tmp_path))
    run_dir = _killed_decomposition(base)
    workdir = round_dir(run_dir, 2)
    # The planner as its call starts it: its own settings and its id on its command line. Its
    # decompose was killed outright, so nothing will read its answer, and it runs on.
    planner = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)", "--settings"]
        + [str(workdir / "settings.json"), "--session-id", str(uuid.uuid4())]
    )
    try:
        remove_left_credentials(run_dir, run_dir / "review")
        deadline = time.monotonic() + 30
        while planner.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert planner.poll() is not None, "the planner a killed decompose left still runs"
        assert _logins(run_dir) == [], "the login file of a planner a kill left stays"
    finally:
        if planner.poll() is None:
            planner.kill()
        planner.wait()


# --- one function knows every place, as the writers name it -----------------------------------

WRITERS = ("write_login", "write_key_helper")


def _writer_calls() -> list[tuple[str, int, str | None]]:
    """Every call of a credential writer in the package's source: file, line, the place it names."""
    import ast

    import physgate

    found: list[tuple[str, int, str | None]] = []
    top = Path(physgate.__file__).resolve().parent
    for path in sorted(top.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in WRITERS:
                continue
            named = [k.value for k in node.keywords if k.arg == "place"]
            value = named[0].value if named and isinstance(named[0], ast.Constant) else None
            found.append((str(path.relative_to(top)), node.lineno, value))
    return found


def test_every_credential_writer_names_a_kind_of_place_the_one_finder_knows() -> None:
    calls = _writer_calls()
    assert calls, "no writer of a credential was found in the source"
    unknown = [c for c in calls if c[2] not in credentials.CREDENTIAL_PLACES]
    assert unknown == [], f"a credential is written where the finder does not look: {unknown}"
    # Each kind a writer names has its finder, and each finder a kind some writer names.
    assert set(stop_signals._FINDERS) == set(credentials.CREDENTIAL_PLACES)
    assert {c[2] for c in calls} == set(credentials.CREDENTIAL_PLACES)


def test_a_writer_asked_for_a_kind_of_place_the_finder_does_not_know_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    with pytest.raises(InvocationError, match="the sweep after a kill finds"):
        write_login(tmp_path / "config", DUMMY, place="somewhere_else")  # type: ignore[arg-type]
    with pytest.raises(InvocationError, match="the sweep after a kill finds"):
        credentials.write_key_helper(tmp_path / "state", DUMMY, place="")  # type: ignore[arg-type]
    assert not (tmp_path / "config").exists() and not (tmp_path / "state").exists()


def _a_place_of_each_kind(base: Path) -> dict[str, tuple[Path, Path, Path | None]]:
    """For each kind, a place made by the code its writer writes through: (root, config, review)."""
    from physgate.evaluation.tiers.store import PLACE
    from physgate.orchestrator.decomposition_review import REVIEW_SESSION, review_spawned

    run_dir = base / "run"
    role = run_dir / "sessions" / str(uuid.uuid4())
    module_review = base / "reviews" / str(uuid.uuid4()) / "session"
    module_review.mkdir(parents=True)
    (module_review / dispatch.OWNER_NAME).write_text(json.dumps({"run_id": "run-a"}))
    (run_dir / "run.json").parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({"run_id": "run-a"}))
    # The plan's review, as its spawn records it before the opening (``review_spawned``).
    plan_run = base / "decomposed"
    plan_sid = str(uuid.uuid4())
    review_spawned(plan_run, review_root=base / "plan-reviews")(plan_sid, 999_999, "never")
    assert (plan_run / REVIEW_SESSION).is_file()
    plan_review = base / "plan-reviews" / plan_sid / "session"
    trial = base / "trial"
    return {
        "role_session": (run_dir, role / "config", None),
        "review_session (a module's)": (run_dir, module_review / "config", base / "reviews"),
        "review_session (the plan's)": (plan_run, plan_review / "config", None),
        "plan_call (round one)": (plan_run, round_dir(plan_run, 1) / "config", None),
        "plan_call (its retry)": (plan_run, retry_dir(plan_run, 1) / "config", None),
        "plan_call (round three)": (plan_run, round_dir(plan_run, 3) / "config", None),
        "plan_call (round three's retry)": (plan_run, retry_dir(plan_run, 3) / "config", None),
        "raw_session": (trial, trial / PLACE / "session" / "config", None),
    }


@pytest.mark.parametrize(
    "kind",
    [
        "role_session",
        "review_session (a module's)",
        "review_session (the plan's)",
        "plan_call (round one)",
        "plan_call (its retry)",
        "plan_call (round three)",
        "plan_call (round three's retry)",
        "raw_session",
    ],
)
def test_every_kind_of_place_is_found_where_its_writer_writes_and_cleared_by_the_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    base = Path(os.path.realpath(tmp_path))
    root, config, review_root = _a_place_of_each_kind(base)[kind]
    place = kind.split()[0]
    write_login(config, DUMMY, place=place)  # type: ignore[arg-type]
    (config.parent / "state").mkdir()
    credentials.write_key_helper(config.parent / "state", DUMMY, place=place)  # type: ignore[arg-type]
    found = credential_places(root, review_root)
    assert (config.parent / "state", config) in {(s.state, s.config) for s in found}, found
    assert {s.place for s in found if s.config == config} == {place}
    if place == "raw_session":
        # A raw trial's place is cleared by its own round, which knows its session has ended.
        raw._clean(config.parent.parent, config.parent, DUMMY, ())
    else:
        remove_left_credentials(root, review_root)
    assert _logins(base) == [], f"{kind}: its login file was left"
    assert not (config.parent / "state" / credentials.KEY_FILE).exists(), (
        f"{kind}: its key was left"
    )


def test_a_planner_s_login_is_left_while_its_decompose_still_drives_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    base = Path(os.path.realpath(tmp_path))
    run_dir = _killed_decomposition(base)
    before = _logins(run_dir)
    planner = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)", "--settings"]
        + [str(round_dir(run_dir, 2) / "settings.json")]
    )
    fd = os.open(run_dir, os.O_RDONLY)
    try:
        # What a decompose that drives the directory holds while its calls run.
        fcntl.flock(fd, fcntl.LOCK_SH)
        assert remove_left_credentials(run_dir, run_dir / "review") == ()
        assert planner.poll() is None, "a planner its live decompose runs was stopped"
        assert _logins(run_dir) == before
    finally:
        os.close(fd)
        planner.kill()
        planner.wait()


def test_decompose_holds_its_directory_s_lock_around_its_calls_and_its_review() -> None:
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(orchestrator_cli._decompose_run)))
    held = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and getattr(item.context_expr.func, "id", None) == "driving"
            for item in node.items
        )
    ]
    assert len(held) == 1, "decompose holds no lock on its directory"
    inside = {getattr(n.func, "id", None) for n in ast.walk(held[0]) if isinstance(n, ast.Call)}
    assert {"decompose_in_rounds", "_plan_reviewer"} <= inside, inside
