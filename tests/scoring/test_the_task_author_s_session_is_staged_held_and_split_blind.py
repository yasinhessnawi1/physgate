"""The authoring runner and the blind check, with the session replaced by a scripted one.

The fake session writes into its worktree what an author (or a checker) would, so every
step after it runs for real: staging, the reference check, the seeded draw, the split, the
evidence moved inside the protected root, and the counts-only output.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

import pytest
from control_fixtures import GOOD_PID, control_task, controller

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.arms.raw import RawSetup
from physgate.evaluation.per_role.author_session import (
    QUESTIONS,
    AuthoringPlan,
    author,
    blind_check,
)
from physgate.evaluation.per_role.authoring import AuthoringError
from physgate.evaluation.per_role.validate import id_digest
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

    def __init__(self, write: Any) -> None:
        self.write = write
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, prompt: str, setup: RawSetup, work: Path, *, cap: int, files: Any = None
    ) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "model": setup.model, "files": files, "cap": cap})
        worktree = work / "worktree"
        (work / "session").mkdir(parents=True)
        worktree.mkdir()
        (worktree / ".git").mkdir()
        for name, data in (files or {}).items():
            (worktree / name).write_bytes(data)
        (work / "session" / "stdout.jsonl").write_text("the stream\n")
        self.write(worktree)
        return {
            "session_id": "s-1",
            "end": "ended",
            "tokens": 1234,
            "cap": cap,
            "wall_clock_s": 1.5,
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
    base = {
        "role": "control",
        "implementer_model": "claude-opus-5-5",
        "work": tmp_path / "scratch" / "work",
        "visible": tmp_path / "repo" / "visible",
        "held_out_root": tmp_path / "private" / "v1",
        "seed": 5,
        "cap": 4_000_000,
    }
    base.update(changes)
    return AuthoringPlan(**base)


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: Any, **changes: Any) -> Any:
    fake = FakeSession(write)
    monkeypatch.setattr(author_session, "run_session", fake)
    plan = _plan(tmp_path, **changes)
    (tmp_path / "scratch").mkdir(exist_ok=True)
    return plan, fake, author(plan, _setup(tmp_path / "private"))


def test_sixteen_sound_tasks_are_split_and_only_counts_and_visible_ids_leave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, fake, out = _run(tmp_path, monkeypatch, _tasks(16))
    assert out["status"] == "split" and out["held"] == 16 and out["held_out_count"] == 8
    visible = sorted(p.name for p in plan.visible.iterdir())
    held = sorted(p.name for p in (plan.held_out_root / "control").iterdir() if p.is_dir())
    assert out["visible"] == visible and len(visible) == 8 and len(held) == 8
    printed = json.dumps(out)
    for name in held:
        assert name not in printed
    assert "Hold the plant" not in printed
    assert out["held_out_check"]["references_held"] == 8
    assert out["visible_check"]["ids"] == visible
    # The author was told the brief and nothing else, on its own model.
    assert fake.calls[0]["model"] == "claude-sonnet-5" and fake.calls[0]["files"] is None
    assert "exactly 16 tasks" in fake.calls[0]["prompt"]


def test_the_session_s_stream_is_kept_inside_the_protected_root_and_its_work_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, _ = _run(tmp_path, monkeypatch, _tasks(16))
    kept = plan.held_out_root / "control.author" / "s-1"
    assert (kept / "stdout.jsonl").read_text() == "the stream\n"
    assert json.loads((kept / "record.json").read_text())["tokens"] == 1234
    assert not plan.work.exists()
    assert (plan.held_out_root / "control.canaries.json").is_file()


def test_with_fewer_sound_tasks_than_two_tiers_nothing_is_kept_but_the_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, out = _run(tmp_path, monkeypatch, _tasks(16, broken=1))
    assert out["status"] == "too_few_held" and out["held"] == 15 and out["written"] == 16
    assert not plan.visible.exists()
    assert not (plan.held_out_root / "control").exists()
    assert not plan.work.exists()


def test_from_more_sound_tasks_the_tiers_are_drawn_by_the_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = []
    for attempt in ("a", "b"):
        base = tmp_path / attempt
        base.mkdir()
        plan, _, out = _run(base, monkeypatch, _tasks(20, broken=2), count=20)
        assert out["held"] == 18 and out["status"] == "split"
        chosen = {p.name for p in plan.visible.iterdir()}
        chosen |= {p.name for p in (plan.held_out_root / "control").iterdir() if p.is_dir()}
        runs.append(chosen)
        assert len(chosen) == 16 and not chosen & {"control.t00", "control.t01"}
    assert runs[0] == runs[1]
    held = sorted(f"control.t{n:02d}" for n in range(2, 20))
    random.Random(5).shuffle(held)
    assert runs[0] == set(held[:16])


def test_a_task_whose_brief_gives_its_answer_away_is_never_drawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(worktree: Path) -> None:
        _tasks(17)(worktree)
        task = json.loads((worktree / "control.t16" / "task.json").read_text())
        task["brief"] = "Try 1.02 s^2 + 2.04 s + 4 over 0.01 s^2 + s."
        (worktree / "control.t16" / "task.json").write_text(json.dumps(task))

    plan, _, out = _run(tmp_path, monkeypatch, write, count=17)
    assert out["held"] == 16 and out["status"] == "split"
    placed = {p.name for p in plan.visible.iterdir()}
    placed |= {p.name for p in (plan.held_out_root / "control").iterdir()}
    assert "control.t16" not in placed


def test_a_task_holding_a_link_is_refused_as_files_and_never_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "elsewhere.txt"
    secret.write_text("not the author's")

    def write(worktree: Path) -> None:
        _tasks(17)(worktree)
        os.symlink(secret, worktree / "control.t16" / "references" / "good" / "extra.txt")

    plan, _, out = _run(tmp_path, monkeypatch, write, count=17)
    assert out["refused_as_files"] == 1 and out["held"] == 16 and out["status"] == "split"


def test_an_author_on_the_implementers_model_is_refused_before_any_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSession(_tasks(16))
    monkeypatch.setattr(author_session, "run_session", fake)
    with pytest.raises(AuthoringError, match="implementers' own model"):
        author(_plan(tmp_path), _setup(tmp_path / "private", model="claude-opus-5-5"))
    assert fake.calls == []


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"work": "private/v1/work"}, "inside a held-out root"),
        ({"visible": "private/visible"}, "inside a held-out root"),
        ({"held_out_root": "elsewhere/v1"}, "does not withhold the protected root"),
        ({"count": 12}, "at least 16"),
    ],
)
def test_a_plan_that_would_expose_or_short_a_tier_is_refused_before_any_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any], match: str
) -> None:
    fake = FakeSession(_tasks(16))
    monkeypatch.setattr(author_session, "run_session", fake)
    resolved = {k: (tmp_path / v if isinstance(v, str) else v) for k, v in changes.items()}
    with pytest.raises(AuthoringError, match=match):
        author(_plan(tmp_path, **resolved), _setup(tmp_path / "private"))
    assert fake.calls == []


def test_a_held_out_tier_already_there_is_never_written_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "private" / "v1" / "control").mkdir(parents=True)
    fake = FakeSession(_tasks(16))
    monkeypatch.setattr(author_session, "run_session", fake)
    with pytest.raises(AuthoringError, match="made new for each session"):
        author(_plan(tmp_path), _setup(tmp_path / "private"))
    assert fake.calls == []


# ------------------------------------------------------------------- the blind check


def _held_tier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AuthoringPlan:
    plan, _, _ = _run(tmp_path, monkeypatch, _tasks(16))
    return plan


def _answers(value: Any) -> Any:
    def write(worktree: Path) -> None:
        keys = list(json.loads((worktree / "tasks.json").read_text()))
        answers = value(keys) if callable(value) else value
        (worktree / "answers.json").write_text(json.dumps(answers))

    return write


def _check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: Any) -> tuple[Any, Any]:
    plan = _held_tier(tmp_path, monkeypatch)
    fake = FakeSession(write)
    monkeypatch.setattr(author_session, "run_session", fake)
    out = blind_check(
        plan.held_out_root / "control",
        _setup(tmp_path / "private"),
        tmp_path / "scratch" / "check",
        implementer_model="claude-opus-5-5",
        cap=500_000,
        evidence=plan.held_out_root / "control.check",
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
    assert not (tmp_path / "scratch" / "check").exists()
    held = tmp_path / "private" / "v1"
    assert (held / "control.check" / "s-1" / "stdout.jsonl").is_file()


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
    plan = _held_tier(tmp_path, monkeypatch)
    with pytest.raises(AuthoringError, match="implementers' own model"):
        blind_check(
            plan.held_out_root / "control",
            _setup(tmp_path / "private", model="claude-opus-5-5"),
            tmp_path / "scratch" / "check",
            implementer_model="claude-opus-5-5",
            cap=1,
            evidence=plan.held_out_root / "control.check",
        )


def test_the_id_digest_is_what_flags_are_printed_as() -> None:
    assert id_digest("control.t00") == id_digest("control.t00") != id_digest("control.t01")


# ------------------------------------------- links and a cleanup that must fail closed


def test_a_task_holding_a_hard_link_is_refused_as_files_and_never_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(worktree: Path) -> None:
        _tasks(17)(worktree)
        shared = worktree / "control.t16" / "references" / "good" / "answer.json"
        os.link(shared, worktree / "shared-elsewhere.json")

    plan, _, out = _run(tmp_path, monkeypatch, write, count=17)
    assert out["refused_as_files"] == 1 and out["held"] == 16 and out["status"] == "split"
    placed = {p.name for p in plan.visible.iterdir()}
    placed |= {p.name for p in (plan.held_out_root / "control").iterdir()}
    assert "control.t16" not in placed


def test_every_staged_file_is_a_new_file_copied_by_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, _ = _run(tmp_path, monkeypatch, _tasks(16))
    for tier in (plan.visible, plan.held_out_root / "control"):
        for path in tier.rglob("*"):
            assert not path.is_symlink()
            assert path.is_dir() or path.stat().st_nlink == 1


def test_a_split_that_fails_part_way_leaves_no_task_outside_the_protected_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def half_a_split(staging: Path, visible: Path, held_out: Path, *, seed: int) -> Any:
        visible.mkdir(parents=True)
        first = sorted(staging.iterdir())[0]
        (visible / first.name).mkdir()
        (visible / first.name / "task.json").write_bytes((first / "task.json").read_bytes())
        held_out.mkdir(parents=True)
        raise OSError("the disk filled part-way")

    monkeypatch.setattr(author_session, "split", half_a_split)
    with pytest.raises(OSError, match="part-way"):
        _run(tmp_path, monkeypatch, _tasks(16))
    plan = _plan(tmp_path)
    assert not plan.visible.exists()
    assert not (plan.held_out_root / "control").exists()
    assert not plan.work.exists()
    assert list((plan.held_out_root / "control.author").glob("*/stdout.jsonl"))


def test_a_failing_session_leaves_nothing_it_wrote_outside_the_protected_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(worktree: Path) -> None:
        _tasks(16)(worktree)
        raise RuntimeError("the session's end failed")

    with pytest.raises(RuntimeError, match="end failed"):
        _run(tmp_path, monkeypatch, write)
    plan = _plan(tmp_path)
    assert not plan.work.exists()
    assert list((plan.held_out_root / "control.author").glob("*/stdout.jsonl"))


def test_a_cleanup_that_cannot_remove_the_work_refuses_loudly_and_reports_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = author_session.shutil.rmtree

    def stuck(path: Any, *args: Any, **kwargs: Any) -> None:
        if Path(path).name == "work":
            raise PermissionError(f"cannot remove {path}")
        real(path, *args, **kwargs)

    monkeypatch.setattr(author_session.shutil, "rmtree", stuck)
    with pytest.raises(AuthoringError, match="could not be removed"):
        _run(tmp_path, monkeypatch, _tasks(16))


def test_half_a_tier_that_cannot_be_removed_refuses_loudly_after_securing_the_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def half_a_split(staging: Path, visible: Path, held_out: Path, *, seed: int) -> Any:
        visible.mkdir(parents=True)
        raise OSError("the disk filled part-way")

    real = author_session.shutil.rmtree

    def stuck(path: Any, *args: Any, **kwargs: Any) -> None:
        if Path(path).name == "visible":
            raise PermissionError(f"cannot remove {path}")
        real(path, *args, **kwargs)

    monkeypatch.setattr(author_session, "split", half_a_split)
    monkeypatch.setattr(author_session.shutil, "rmtree", stuck)
    with pytest.raises(AuthoringError, match="visible") as raised:
        _run(tmp_path, monkeypatch, _tasks(16))
    assert "remove these by hand" in str(raised.value)
    plan = _plan(tmp_path)
    assert not plan.work.exists()
    assert list((plan.held_out_root / "control.author").glob("*/stdout.jsonl"))


def test_a_failing_check_session_leaves_no_held_out_task_outside_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(worktree: Path) -> None:
        raise RuntimeError("the check's session failed")

    with pytest.raises(RuntimeError, match="check's session failed"):
        _check(tmp_path, monkeypatch, write)
    assert not (tmp_path / "scratch" / "check").exists()
    assert list((tmp_path / "private" / "v1" / "control.check").glob("*/stdout.jsonl"))


def test_what_is_validated_shares_no_file_with_what_the_session_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file shared with the worktree could be changed, after its check, by anything the
    # session left behind; staging is checked as it is when it is validated.
    seen: list[tuple[str, int]] = []
    real = author_session.sound

    def inspecting(staging: Path) -> list[str]:
        seen.extend((str(p), p.lstat().st_nlink) for p in staging.rglob("*") if not p.is_dir())
        return real(staging)

    monkeypatch.setattr(author_session, "sound", inspecting)
    _run(tmp_path, monkeypatch, _tasks(16))
    assert seen and all(links == 1 for _, links in seen)


def test_a_tier_reached_through_a_link_is_refused_before_any_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "linked").symlink_to(tmp_path / "real")
    fake = FakeSession(_tasks(16))
    monkeypatch.setattr(author_session, "run_session", fake)
    plan = _plan(tmp_path, visible=tmp_path / "linked" / "visible")
    with pytest.raises(AuthoringError, match="reached through a link"):
        author(plan, _setup(tmp_path / "private"))
    assert fake.calls == []
