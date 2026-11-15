"""The authoring runner and the blind check, with the session replaced by a scripted one.

The fake session writes into its worktree what an author (or a checker) would, so every
step after it runs for real: staging, the reference check, the seeded draw, the split into a
version of the tier-set store, the evidence moved inside the role's root, and the counts-only
output.
"""

from __future__ import annotations

import dataclasses
import json
import os
import random
import shutil
from pathlib import Path
from typing import Any

import pytest
from control_fixtures import GOOD_PID, control_task, controller

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role import validate as validate_module
from physgate.evaluation.per_role.arms.raw import RawSetup
from physgate.evaluation.per_role.author_session import (
    QUESTIONS,
    AuthoringPlan,
    AuthorProgress,
    author,
    blind_check,
)
from physgate.evaluation.per_role.validate import id_digest
from physgate.evaluation.tiers import store as store_module
from physgate.evaluation.tiers.authoring import TIERS, AuthoringError
from physgate.evaluation.tiers.canaries import root_canaries
from physgate.evaluation.tiers.manifest import VERSION_NAME
from physgate.evaluation.tiers.store import pool_dir
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.run_config import RunBounds
from physgate.oslayer.probe import Absent

UNSTABLE = controller([1.0], [1.0], gain=0.1)
SECRET_BRIEF = "Hold the plant 10/(s^2-2s+3) inside its margin; task {n}."
#: Task names in words: a digit in a brief that equals a reference's coefficient is a leak.
WORDS = "abcdefghijklmnopqrstuvwxyz"


def _setup(root: Path, model: str = "claude-sonnet-5") -> RawSetup:
    return RawSetup(
        binary="claude",
        claude_version="2.1.301",
        model=model,
        effort="high",
        max_output_tokens=64000,
        thinking_display="summarized",
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=10,
            infra_retry_delays_s=(),
        ),
        credential=Credential("api_key", "k"),
        base_url="http://127.0.0.1:9",
        install_bin=Path("/nonexistent"),
        role_python=None,
        held_out=(str(root),),
        held_out_canaries=(),
        network="none",
        os_layer=Absent(reason="a unit test"),
    )


def _write_task(directory: Path, n: int, *, good: dict[str, Any] = GOOD_PID) -> None:
    task = json.loads(control_task().model_dump_json())
    task.update(id=directory.name, brief=SECRET_BRIEF.format(n=WORDS[n]))
    (directory / "references" / "good").mkdir(parents=True)
    (directory / "references" / "bad_unstable").mkdir(parents=True)
    (directory / "task.json").write_text(json.dumps(task))
    (directory / "references" / "good" / "answer.json").write_text(json.dumps(good))
    (directory / "references" / "bad_unstable" / "answer.json").write_text(json.dumps(UNSTABLE))
    (directory / "references" / "bad_unstable" / "expect.json").write_text('{"fails": "stable"}')


class FakeSession:
    """Stands in for ``run_session``: writes what the scripted session would, records calls."""

    def __init__(self, write: Any, *, session_id: str = "s-1", checking: bool = True) -> None:
        self.write = write
        self.session_id, self.checking = session_id, checking
        self.calls: list[dict[str, Any]] = []
        #: The setup each call was given, as the session would be installed from it.
        self.setups: list[RawSetup] = []

    def __call__(
        self,
        prompt: str,
        setup: RawSetup,
        work: Path,
        *,
        cap: int,
        files: Any = None,
        check: Any = None,
    ) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "model": setup.model, "files": files, "cap": cap})
        self.setups.append(setup)
        worktree = work / "worktree"
        (work / "session").mkdir(parents=True)
        worktree.mkdir()
        (worktree / ".git").mkdir()
        for name, data in (files or {}).items():
            (worktree / name).write_bytes(data)
        (work / "session" / "stdout.jsonl").write_text("the stream\n")
        # As the real session directory: the interpreter's link beside the stream.
        (work / "session" / "bin").mkdir()
        os.symlink("/usr/bin/python3", work / "session" / "bin" / "python3")
        self.write(worktree)
        # The watch asks the checkpoint at each reading; here once, after the writing.
        self.stopped_for = check(1234) if check is not None and self.checking else None
        return {
            "session_id": self.session_id,
            "end": self.stopped_for or "ended",
            "tokens": 1234,
            "cap": cap,
            "wall_clock_s": 1.5,
            "held_out_seen": False,
        }


def _tasks(count: int, broken: int = 0) -> Any:
    def write(worktree: Path) -> None:
        for n in range(count):
            _write_task(
                worktree / f"control.t{n:02d}", n, good=UNSTABLE if n < broken else GOOD_PID
            )
        (worktree / "notes.txt").write_text("the author's own notes, never staged")

    return write


def _plan(tmp_path: Path, **changes: Any) -> AuthoringPlan:
    base: dict[str, Any] = {
        "role": "control",
        "implementer_model": "claude-opus-5-5",
        "work": tmp_path / "scratch" / "work",
        "store": tmp_path / "private" / "store",
        "seed": 5,
        "cap": 4_000_000,
    }
    base.update(changes)
    return AuthoringPlan(**base)


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write: Any,
    session_id: str = "s-1",
    checking: bool = True,
    **changes: Any,
) -> Any:
    fake = FakeSession(write, session_id=session_id, checking=checking)
    monkeypatch.setattr(author_session, "run_session", fake)
    plan = _plan(tmp_path, **changes)
    (tmp_path / "scratch").mkdir(exist_ok=True)
    return plan, fake, author(plan, _setup(tmp_path / "private"))


def _versions(plan: AuthoringPlan) -> list[Path]:
    """Every version of the role's tiers in the store."""
    if not plan.root.is_dir():
        return []
    return sorted(p for p in plan.root.iterdir() if VERSION_NAME.fullmatch(p.name))


def _tier(plan: AuthoringPlan, name: str) -> Path:
    """The tier ``name`` of the one version the store holds."""
    (version,) = _versions(plan)
    return version / name


def _placed(plan: AuthoringPlan) -> set[str]:
    """Every task the split placed, in any of the three tiers of any version."""
    placed: set[str] = set()
    for version in _versions(plan):
        for name in TIERS:
            placed |= {p.name for p in (version / name).iterdir() if p.is_dir()}
    return placed


def _pooled(plan: AuthoringPlan) -> list[str]:
    """The tasks the role's pool holds."""
    pool = pool_dir(plan.store, plan.role)
    return sorted(p.name for p in pool.iterdir() if p.is_dir()) if pool.is_dir() else []


def _unfinished(plan: AuthoringPlan) -> list[str]:
    """Every version still being written, or a pool already drawn from, in the role's root."""
    if not plan.root.is_dir():
        return []
    names = [p.name for p in plan.root.iterdir() if p.name.startswith(".version-")]
    withheld = plan.root / "withheld"
    spent = [f"withheld/{p.name}" for p in withheld.glob("pool.spent")] if withheld.is_dir() else []
    return sorted(names + spent)


def test_twenty_four_sound_tasks_are_split_and_only_counts_and_visible_ids_leave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, fake, out = _run(tmp_path, monkeypatch, _tasks(24))
    assert out["status"] == "split" and out["held"] == 24 and out["held_out_count"] == 8
    visible = sorted(p.name for p in _tier(plan, "visible").iterdir())
    held = sorted(p.name for p in _tier(plan, "held_out").iterdir() if p.is_dir())
    assert out["visible"] == visible and len(visible) == 8 and len(held) == 8
    printed = json.dumps(out)
    for name in held:
        assert name not in printed
    assert "Hold the plant" not in printed
    assert out["held_out_check"]["references_held"] == 8
    assert out["visible_check"]["ids"] == visible
    # The author was told the brief and nothing else, on its own model.
    assert fake.calls[0]["model"] == "claude-sonnet-5" and fake.calls[0]["files"] is None
    assert "up to 24 tasks" in fake.calls[0]["prompt"]
    # Every task held while the session ran, and the checkpoint let it run on.
    assert out["held_while_running"] == 24 and fake.stopped_for is None
    assert out["session"]["per_task_cap"] == 500_000


def test_the_session_s_stream_is_kept_inside_the_protected_root_and_its_work_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, _ = _run(tmp_path, monkeypatch, _tasks(24))
    kept = plan.root / "withheld" / "author" / "s-1"
    assert (kept / "stdout.jsonl").read_text() == "the stream\n"
    assert json.loads((kept / "record.json").read_text())["tokens"] == 1234
    assert not plan.work.exists()
    assert (_tier(plan, "held_out") / "canaries.json").is_file()


def test_with_fewer_sound_tasks_than_two_tiers_they_are_pooled_inside_the_protected_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, out = _run(tmp_path, monkeypatch, _tasks(24, broken=1))
    assert out["status"] == "pooled" and out["held"] == 23 and out["written"] == 24
    assert out["pooled"] == 23 and out["pool"] == 23
    assert out["refused_because"]["good_fails:max_real_pole"] == 1
    assert "control.t" not in json.dumps(out)
    assert _versions(plan) == []
    assert not plan.work.exists()
    pool = pool_dir(plan.store, plan.role)
    assert _pooled(plan) == [f"control.t{n:02d}" for n in range(1, 24)]
    assert all(
        p.is_dir() or (not p.is_symlink() and p.stat().st_nlink == 1) for p in pool.rglob("*")
    )


def test_a_further_session_adds_to_the_pool_and_the_tiers_are_cut_from_it_by_the_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, first = _run(tmp_path, monkeypatch, _tasks(10, broken=1))
    assert first["status"] == "pooled" and first["pool"] == 9

    def write(worktree: Path) -> None:
        for n in range(10, 26):
            _write_task(worktree / f"control.t{n:02d}", n)
        _write_task(worktree / "control.t05", 5)  # an id the pool already holds

    plan, fake, out = _run(
        tmp_path,
        monkeypatch,
        write,
        session_id="s-2",
        work=tmp_path / "scratch" / "work2",
        id_prefix="b2.",
    )
    assert 'beginning with "b2."' in fake.calls[0]["prompt"]
    assert out["status"] == "split" and out["held"] == 17 and out["pooled"] == 16
    assert out["refused_because"] == {"id_already_pooled": 1}
    assert out["held_out_count"] == 8
    # The pool never outlives the split: the one task the draw did not take goes with it.
    assert out["pool"] == 0 and out["left_with_the_pool"] == 1
    assert not pool_dir(plan.store, plan.role).exists()
    placed = _placed(plan)
    everything = sorted(f"control.t{n:02d}" for n in range(1, 26))
    assert len(placed) == 24
    random.Random(5).shuffle(everything)
    assert placed == set(everything[:24])
    assert _unfinished(plan) == []
    assert out["held_out_check"]["references_held"] == 8


def test_the_session_s_links_never_reach_the_protected_root_and_a_root_with_one_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, out = _run(tmp_path, monkeypatch, _tasks(10))
    assert out["status"] == "pooled"
    root = plan.root
    assert not [
        p for p in root.rglob("*") if p.is_symlink() or p.is_file() and p.stat().st_nlink != 1
    ]
    kept = root / "withheld" / "author" / "s-1"
    assert (kept / "stdout.jsonl").read_text() == "the stream\n"
    dropped = json.loads((kept / "record.json").read_text())["evidence_dropped"]
    assert len(dropped) == 1 and dropped[0].endswith("/bin/python3")
    # Had the link been kept, the next session would be refused every tool call: the
    # runner surveys the root as that session's tripwire will, and refuses first.
    os.symlink("/usr/bin/python3", kept / "python3")

    def more(worktree: Path) -> None:
        for n in range(10, 24):
            _write_task(worktree / f"control.t{n:02d}", n)

    fake = FakeSession(more, session_id="s-2")
    monkeypatch.setattr(author_session, "run_session", fake)
    second = _plan(tmp_path, work=tmp_path / "scratch" / "work2")
    with pytest.raises(AuthoringError, match="refused every tool call") as caught:
        author(second, _setup(tmp_path / "private"))
    assert "python3" in str(caught.value) and fake.calls == []
    # With the link gone, the same session runs and completes the tiers from the pool.
    (kept / "python3").unlink()
    assert author(second, _setup(tmp_path / "private"))["status"] == "split"


def test_the_checkpoint_holds_each_task_as_it_is_written_and_stops_a_session_off_pace(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    progress = AuthorProgress(worktree, tmp_path / "checks", cap=8_000_000, per_task=1_000_000)
    assert progress.check(100) is None
    assert progress.check(2_000_000) is None  # a quarter of the cap: not yet past it
    assert progress.check(2_000_001) == "no_task_held"
    _write_task(worktree / "control.t00", 0)
    assert progress.check(2_100_000) is None and progress.held == {"control.t00"}
    assert progress.check(3_100_000) is None  # the per-task cap, not yet past it
    assert progress.check(3_100_001) == "task_cap"
    # A task whose reference fails does not hold, and does not reset the pace.
    _write_task(worktree / "control.t01", 1, good=UNSTABLE)
    assert progress.check(3_100_001) == "task_cap" and progress.held == {"control.t00"}
    # A task broken after it held is no longer held; an unchanged one is not checked again.
    checked = progress.checked
    (worktree / "control.t00" / "task.json").write_text("{")
    assert progress.check(3_000_000) is None and progress.held == set()
    assert progress.checked == checked + 1
    assert progress.check(3_000_000) is None and progress.checked == checked + 1
    # The scorer ran on copies, each removed; the worktree is as the author left it.
    assert not any((tmp_path / "checks").iterdir())
    assert (worktree / "control.t00" / "task.json").read_text() == "{"


def test_from_more_sound_tasks_the_tiers_are_drawn_by_the_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = []
    for attempt in ("a", "b"):
        base = tmp_path / attempt
        base.mkdir()
        plan, _, out = _run(base, monkeypatch, _tasks(26, broken=1), count=26)
        assert out["held"] == 25 and out["status"] == "split"
        chosen = _placed(plan)
        runs.append(chosen)
        assert len(chosen) == 24 and "control.t00" not in chosen
    assert runs[0] == runs[1]
    held = sorted(f"control.t{n:02d}" for n in range(1, 26))
    random.Random(5).shuffle(held)
    assert runs[0] == set(held[:24])


def test_a_task_whose_brief_gives_its_answer_away_is_never_drawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(worktree: Path) -> None:
        _tasks(25)(worktree)
        task = json.loads((worktree / "control.t24" / "task.json").read_text())
        task["brief"] = "Try 1.02 s^2 + 2.04 s + 4 over 0.01 s^2 + s."
        (worktree / "control.t24" / "task.json").write_text(json.dumps(task))

    plan, _, out = _run(tmp_path, monkeypatch, write, count=25)
    assert out["held"] == 24 and out["status"] == "split"
    placed = _placed(plan)
    assert "control.t24" not in placed


def test_a_task_holding_a_link_is_refused_as_files_and_never_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "elsewhere.txt"
    secret.write_text("not the author's")

    def write(worktree: Path) -> None:
        _tasks(25)(worktree)
        os.symlink(secret, worktree / "control.t24" / "references" / "good" / "extra.txt")

    plan, _, out = _run(tmp_path, monkeypatch, write, count=25)
    assert out["refused_as_files"] == 1 and out["held"] == 24 and out["status"] == "split"


def test_an_author_on_the_implementers_model_is_refused_before_any_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSession(_tasks(24))
    monkeypatch.setattr(author_session, "run_session", fake)
    with pytest.raises(AuthoringError, match="implementers' own model"):
        author(_plan(tmp_path), _setup(tmp_path / "private", model="claude-opus-5-5"))
    assert fake.calls == []


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"work": "private/store/work"}, "inside a held-out root"),
        ({"work": "private/work"}, "inside a held-out root"),
        ({"store": "elsewhere/store"}, "does not withhold the tier-set store"),
        ({"count": 0}, "at least one task"),
        ({"cap": 8_000_001}, "at most 8000000 tokens"),
        ({"per_task_cap": 4_000_001}, "no more than the session's cap"),
        ({"per_task_cap": 0}, "no more than the session's cap"),
    ],
)
def test_a_plan_that_would_expose_or_short_a_tier_is_refused_before_any_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any], match: str
) -> None:
    fake = FakeSession(_tasks(24))
    monkeypatch.setattr(author_session, "run_session", fake)
    resolved = {k: (tmp_path / v if isinstance(v, str) else v) for k, v in changes.items()}
    with pytest.raises(AuthoringError, match=match):
        author(_plan(tmp_path, **resolved), _setup(tmp_path / "private"))
    assert fake.calls == []


def test_a_work_directory_already_there_is_refused_before_any_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "scratch" / "work").mkdir(parents=True)
    fake = FakeSession(_tasks(24))
    monkeypatch.setattr(author_session, "run_session", fake)
    with pytest.raises(AuthoringError, match="made new for each session"):
        author(_plan(tmp_path), _setup(tmp_path / "private"))
    assert fake.calls == []


# ------------------------------------------------------------------- the blind check


def _held_tier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[AuthoringPlan, str]:
    """A plan whose author has cut a version, and that version's id."""
    plan: AuthoringPlan
    plan, _, out = _run(tmp_path, monkeypatch, _tasks(24))
    return plan, str(out["version"])


def _answers(value: Any) -> Any:
    def write(worktree: Path) -> None:
        keys = list(json.loads((worktree / "tasks.json").read_text()))
        answers = value(keys) if callable(value) else value
        (worktree / "answers.json").write_text(json.dumps(answers))

    return write


def _store_api(name: str) -> Any:  # noqa: ANN401
    """``store.<name>``, or the row fails: what it names is not built yet."""
    found = getattr(store_module, name, None)
    if found is None:
        pytest.fail(f"physgate.evaluation.tiers.store.{name} is not built")
    return found


def check_work(store: Path, name: str = "check") -> Path:
    """Where a blind check on ``store``'s control root works: under the role's work root."""
    return Path(_store_api("work_root")(store, "control")) / name


def check_setup(store: Path, base: RawSetup, name: str = "check") -> RawSetup:
    """``base`` withholding what the command's blind check working in ``name`` withholds.

    All of the role's root but that check's own work (:func:`check_work`).
    """
    try:
        roots = _store_api("check_roots")(store, "control", check_work(store, name))
    except TypeError as exc:
        pytest.fail(f"the check's roots are not given its own work: {exc}")
    return dataclasses.replace(base, held_out=tuple(str(p) for p in roots))


def _check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: Any) -> tuple[Any, Any]:
    plan, version = _held_tier(tmp_path, monkeypatch)
    fake = FakeSession(write)
    monkeypatch.setattr(author_session, "run_session", fake)
    # The check looks for every canary under the root, as the command gives it them.
    setup = dataclasses.replace(
        check_setup(plan.store, _setup(tmp_path / "private")),
        held_out_canaries=root_canaries(plan.root),
    )
    out = blind_check(
        plan.store,
        plan.role,
        version,
        setup,
        check_work(plan.store),
        implementer_model="claude-opus-5-5",
        cap=500_000,
    )
    return out, fake


def test_the_check_reads_its_tasks_from_a_file_by_digest_and_answers_in_booleans_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def answers(keys: list[str]) -> dict[str, Any]:
        found = {k: dict.fromkeys(QUESTIONS, True) for k in keys}
        found[sorted(keys)[0]]["unambiguous"] = False
        return found

    out, fake = _check(tmp_path, monkeypatch, _answers(answers))
    call = fake.calls[0]
    bundle = json.loads(call["files"]["tasks.json"])
    assert len(bundle) == 8 and all(len(k) == 16 for k in bundle)
    text = json.dumps(bundle)
    assert "references" not in text and "canary" not in text and "control.t" not in text
    assert "Hold the plant" not in call["prompt"]  # the content is in the file, not argv
    assert out["answered"] and out["tasks"] == 8 and out["all_yes"] == 7
    assert out["flagged"] == [sorted(bundle)[0]]
    assert not check_work(_plan(tmp_path).store).exists()
    assert (_plan(tmp_path).root / "withheld" / "check" / "s-1" / "stdout.jsonl").is_file()


@pytest.mark.parametrize(
    "bad",
    [
        lambda keys: {k: dict.fromkeys(QUESTIONS, "yes") for k in keys},
        lambda keys: {k: {**dict.fromkeys(QUESTIONS, True), "why": "x"} for k in keys},
        lambda keys: {k: dict.fromkeys(QUESTIONS, True) for k in keys[1:]},
        lambda keys: {**{k: dict.fromkeys(QUESTIONS, True) for k in keys}, "extra": {}},
        lambda keys: [True] * len(keys),
    ],
    ids=["strings", "an explanation", "a key missing", "a key added", "not a mapping"],
)
def test_anything_but_booleans_for_exactly_the_tasks_is_no_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: Any
) -> None:
    out, _ = _check(tmp_path, monkeypatch, _answers(bad))
    assert out["answered"] is False and "flagged" not in out


def test_a_check_on_the_implementers_model_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, version = _held_tier(tmp_path, monkeypatch)
    with pytest.raises(AuthoringError, match="implementers' own model"):
        blind_check(
            plan.store,
            plan.role,
            version,
            check_setup(plan.store, _setup(tmp_path / "private", model="claude-opus-5-5")),
            check_work(plan.store),
            implementer_model="claude-opus-5-5",
            cap=1,
        )


def test_the_id_digest_is_what_flags_are_printed_as() -> None:
    assert id_digest("control.t00") == id_digest("control.t00") != id_digest("control.t01")


# ------------------------------------------- links and a cleanup that must fail closed


def test_a_task_holding_a_hard_link_is_refused_as_files_and_never_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(worktree: Path) -> None:
        _tasks(25)(worktree)
        shared = worktree / "control.t24" / "references" / "good" / "answer.json"
        os.link(shared, worktree / "shared-elsewhere.json")

    plan, _, out = _run(tmp_path, monkeypatch, write, count=25)
    assert out["refused_as_files"] == 1 and out["held"] == 24 and out["status"] == "split"
    placed = _placed(plan)
    assert "control.t24" not in placed


def test_every_staged_file_is_a_new_file_copied_by_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, _ = _run(tmp_path, monkeypatch, _tasks(24))
    for tier in (_tier(plan, name) for name in TIERS):
        for path in tier.rglob("*"):
            assert not path.is_symlink()
            assert path.is_dir() or path.stat().st_nlink == 1


def test_a_split_that_fails_part_way_leaves_no_task_outside_the_protected_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def half_a_split(
        staging: Path, visible: Path, held_out: Path, *, validation: Path, seed: int
    ) -> Any:
        visible.mkdir(parents=True)
        first = sorted(staging.iterdir())[0]
        (visible / first.name).mkdir()
        (visible / first.name / "task.json").write_bytes((first / "task.json").read_bytes())
        validation.mkdir(parents=True)
        held_out.mkdir(parents=True)
        raise OSError("the disk filled part-way")

    monkeypatch.setattr(store_module, "split", half_a_split)
    with pytest.raises(OSError, match="part-way"):
        _run(tmp_path, monkeypatch, _tasks(24))
    plan = _plan(tmp_path)
    assert _versions(plan) == [] and _unfinished(plan) == []
    # A split that did not finish leaves the pool whole, for a person or a later session.
    assert len(_pooled(plan)) == 24
    assert not plan.work.exists()
    assert list((plan.root / "withheld" / "author").glob("*/stdout.jsonl"))


def test_a_failing_session_leaves_nothing_it_wrote_outside_the_protected_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(worktree: Path) -> None:
        _tasks(24)(worktree)
        raise RuntimeError("the session's end failed")

    with pytest.raises(RuntimeError, match="end failed"):
        _run(tmp_path, monkeypatch, write)
    plan = _plan(tmp_path)
    assert not plan.work.exists()
    assert list((plan.root / "withheld" / "author").glob("*/stdout.jsonl"))


def test_a_cleanup_that_cannot_remove_the_work_refuses_loudly_and_reports_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The module's own shutil is this one: patched here, it is patched there.
    real = shutil.rmtree

    def stuck(path: Any, *args: Any, **kwargs: Any) -> None:
        if Path(path).name == "work":
            raise PermissionError(f"cannot remove {path}")
        real(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", stuck)
    with pytest.raises(AuthoringError, match="could not be removed"):
        _run(tmp_path, monkeypatch, _tasks(24))


def test_half_a_tier_that_cannot_be_removed_refuses_loudly_after_securing_the_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def half_a_split(
        staging: Path, visible: Path, held_out: Path, *, validation: Path, seed: int
    ) -> Any:
        visible.mkdir(parents=True)
        raise OSError("the disk filled part-way")

    # The module's own shutil is this one: patched here, it is patched there.
    real = shutil.rmtree

    def stuck(path: Any, *args: Any, **kwargs: Any) -> None:
        if Path(path).name.startswith(".version-"):
            raise PermissionError(f"cannot remove {path}")
        real(path, *args, **kwargs)

    monkeypatch.setattr(store_module, "split", half_a_split)
    monkeypatch.setattr(shutil, "rmtree", stuck)
    with pytest.raises(AuthoringError, match=r"\.version-") as raised:
        _run(tmp_path, monkeypatch, _tasks(24))
    assert "remove these by hand" in str(raised.value)
    plan = _plan(tmp_path)
    assert not plan.work.exists()
    assert list((plan.root / "withheld" / "author").glob("*/stdout.jsonl"))


def test_a_failing_check_session_leaves_no_held_out_task_outside_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(worktree: Path) -> None:
        raise RuntimeError("the check's session failed")

    with pytest.raises(RuntimeError, match="check's session failed"):
        _check(tmp_path, monkeypatch, write)
    assert not check_work(_plan(tmp_path).store).exists()
    assert list((_plan(tmp_path).root / "withheld" / "check").glob("*/stdout.jsonl"))


def test_what_is_validated_shares_no_file_with_what_the_session_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file shared with the worktree could be changed, after its check, by anything the
    # session left behind; staging is checked as it is when it is validated.
    seen: list[tuple[str, int]] = []
    # The author session calls the validator's own function, imported by name.
    real = validate_module.sound

    def inspecting(staging: Path) -> list[str]:
        seen.extend((str(p), p.lstat().st_nlink) for p in staging.rglob("*") if not p.is_dir())
        return real(staging)

    monkeypatch.setattr(author_session, "sound", inspecting)
    _run(tmp_path, monkeypatch, _tasks(24))
    assert seen and all(links == 1 for _, links in seen)


def test_a_tier_reached_through_a_link_is_refused_before_any_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "private").mkdir()
    (tmp_path / "linked").symlink_to(tmp_path / "private")
    fake = FakeSession(_tasks(24))
    monkeypatch.setattr(author_session, "run_session", fake)
    plan = _plan(tmp_path, store=tmp_path / "linked" / "store")
    with pytest.raises(AuthoringError, match="reached through a link"):
        author(plan, _setup(tmp_path / "private"))
    assert fake.calls == []


# ------------------------------------- staging is walked through descriptors only


def _secret(tmp_path: Path) -> Path:
    secret = tmp_path / "outside" / "secret.json"
    secret.parent.mkdir()
    secret.write_text('{"secret": "never staged"}')
    return secret


def test_a_file_swapped_for_a_link_after_it_was_listed_is_refused_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = _secret(tmp_path)
    real = author_session._classify

    swapped: list[str] = []

    def swap(name: str, dir_fd: int) -> os.stat_result:
        info = real(name, dir_fd)
        if name == "answer.json" and not swapped:
            os.unlink(name, dir_fd=dir_fd)
            os.symlink(secret, name, dir_fd=dir_fd)
            swapped.append(name)
        return info

    monkeypatch.setattr(author_session, "_classify", swap)
    plan, _, out = _run(tmp_path, monkeypatch, _tasks(25), count=25)
    assert swapped and out["refused_as_files"] == 1 and out["held"] == 24
    for tier in (_tier(plan, name) for name in TIERS):
        for path in tier.rglob("*"):
            assert path.is_dir() or "never staged" not in path.read_text()


def test_a_link_planted_where_a_staged_file_is_written_is_never_written_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = _secret(tmp_path)
    real = author_session._new_file
    planted: list[str] = []

    def plant(name: str, dir_fd: int) -> int:
        if name == "task.json" and not planted:
            os.symlink(secret, name, dir_fd=dir_fd)
            planted.append(name)
        return real(name, dir_fd)

    monkeypatch.setattr(author_session, "_new_file", plant)
    # Without the checkpoint's own staging, the first file staged is the runner's.
    _, _, out = _run(tmp_path, monkeypatch, _tasks(25), checking=False, count=25)
    assert planted and out["refused_as_files"] == 1 and out["held"] == 24
    assert secret.read_text() == '{"secret": "never staged"}'


def test_a_link_planted_where_the_staging_directory_goes_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_dir = _secret(tmp_path).parent

    def write(worktree: Path) -> None:
        _tasks(24)(worktree)
        (worktree.parent / "staging").symlink_to(secret_dir)

    with pytest.raises(OSError):
        _run(tmp_path, monkeypatch, write)
    assert sorted(p.name for p in secret_dir.iterdir()) == ["secret.json"]
    assert not _plan(tmp_path).work.exists()


def test_a_task_refused_after_its_files_were_copied_leaves_nothing_to_be_drawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The link sorts after task.json and the references, so everything a task needs has
    # been copied by the time it is met: what was copied must go, or it would be drawn.
    secret = _secret(tmp_path)

    def write(worktree: Path) -> None:
        _tasks(25)(worktree)
        os.symlink(secret, worktree / "control.t24" / "zz-last.json")

    plan, _, out = _run(tmp_path, monkeypatch, write, count=25)
    assert out["refused_as_files"] == 1 and out["held"] == 24
    placed = _placed(plan)
    assert "control.t24" not in placed


def test_a_task_holding_a_fifo_is_refused_without_waiting_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(worktree: Path) -> None:
        _tasks(25)(worktree)
        os.mkfifo(worktree / "control.t24" / "references" / "good" / "pipe")

    _, _, out = _run(tmp_path, monkeypatch, write, count=25)
    assert out["refused_as_files"] == 1 and out["held"] == 24


@pytest.mark.parametrize("command", ["author", "blind-check"])
def test_the_commands_take_a_session_s_bounds_with_a_role_session_s_defaults(
    command: str,
) -> None:
    import argparse

    from physgate.evaluation.per_role import cli

    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    common = ["--role", "control", "--store", "/s", "--work", "/w", "--cap", "1"]
    if command == "author":
        common += ["--role-python", "/p", "--seed", "1"]
    else:
        common += ["--version", "v"]
    given = parser.parse_args(["per-role", command, *common])
    assert (given.session_wall_clock_s, given.session_max_turns) == (1800.0, 150)
    if command == "author":
        assert given.count == 24, "an author is not asked for the three tiers' worth"
    assert given.binary_max_retries == 0
    longer = ["--session-wall-clock-s", "3600", "--session-max-turns", "300"]
    retries = ["--binary-max-retries", "5"]
    given = parser.parse_args(["per-role", command, *common, *longer, *retries])
    assert (given.session_wall_clock_s, given.session_max_turns) == (3600.0, 300)
    assert given.binary_max_retries == 5


def test_work_inside_a_place_withheld_from_the_author_is_refused_before_any_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    fake = FakeSession(_tasks(24))
    monkeypatch.setattr(author_session, "run_session", fake)
    setup = dataclasses.replace(
        _setup(tmp_path / "private"), withheld_reads=(str(tmp_path / "scratch"),)
    )
    with pytest.raises(AuthoringError, match="inside a held-out root"):
        author(_plan(tmp_path), setup)
    assert fake.calls == []
