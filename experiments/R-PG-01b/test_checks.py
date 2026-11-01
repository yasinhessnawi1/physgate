"""Tests of the launch's own parts on invented fixtures: checks.py, launch.sh, the watcher, the
ledger line, r3_scan_f.py's derivation and the filled facts (common.py).

Run explicitly, in the run checkout: ``uv run --frozen pytest -q experiments/R-PG-01b``.
"""

from __future__ import annotations

import json
import os
import platform
import random
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checks  # noqa: E402
import common as C  # noqa: E402
import ledger  # noqa: E402
import testsupport as T  # noqa: E402

# ---- the slots (§2.6) ----


def test_the_slot_draw_is_random_29_over_the_four_first_attempts() -> None:
    draw = checks.draw_slots()
    want = [1, 2, 3, 4]
    random.Random(29).shuffle(want)
    assert draw == dict(zip(("I1", "F1", "I2", "F2"), want, strict=True))
    assert sorted(draw.values()) == [1, 2, 3, 4]


def test_a_reattempt_takes_the_next_unused_slots_in_the_order_of_the_first() -> None:
    records: dict[str, Any] = {"draw": {"I1": 3, "F1": 1, "I2": 4, "F2": 2}, "attempts": []}
    assert checks.slots_for(records, 1) == {"I": 3, "F": 1}
    records["attempts"].append({"round": 1, "slots": {"I": 3, "F": 1}})
    # F's first slot is the lower, so F takes the lower new slot.
    assert checks.slots_for(records, 1) == {"F": 5, "I": 6}
    records["attempts"].append({"round": 1, "slots": {"F": 5, "I": 6}})
    assert checks.slots_for(records, 2) == {"I": 4, "F": 2}
    records["attempts"].append({"round": 2, "slots": {"I": 4, "F": 2}})
    assert checks.slots_for(records, 2) == {"F": 7, "I": 8}


def test_the_fallback_order_is_random_31() -> None:
    order = list(C.ARMS)
    random.Random(31).shuffle(order)
    assert checks.arm_order() == order


def test_two_usage_limit_voids_turn_on_the_fallback() -> None:
    records = {
        "attempts": [
            {"round": 1, "void_causes": ["usage limit", "a crashed or killed process"]},
            {"round": 1, "void_causes": ["usage limit"]},
            {"round": 2, "void_causes": ["usage limit"]},
        ]
    }
    assert checks.usage_limit_voids(records, 1) == 2
    assert checks.usage_limit_voids(records, 2) == 1


# ---- the token's shape, never shown ----


L = T.token_line
P = T.TOKEN_PREFIX


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        (L(P + "a" * 40) + "\n", True),
        (L(P + "b_-9" * 10) + "\n# a comment\nOTHER=1\n", True),
        (L("'" + P + "b_-9" * 10 + "'", before="export ") + "\n", False),
        (L(" " + P + "a" * 40) + "\n", False),
        (L("sk-ant-" + "api03-" + "a" * 40) + "\n", False),
        (L(P + "short") + "\n", False),
        (L(P + "a" * 40) + "\n" + L("x") + "\n", False),
        ("OTHER=1\n", False),
    ],
    ids=[
        "plain",
        "beside-other-lines",
        "exported-quoted",
        "a-space-after-the-equals",
        "an-api-key",
        "too-short",
        "two-lines",
        "none",
    ],
)
def test_the_token_line_is_held_to_its_shape_and_only_a_prefix_is_given(
    tmp_path: Path, text: str, ok: bool
) -> None:
    env = tmp_path / "run.env"
    env.write_text(text)
    if ok:
        prefix = checks.token_prefix(env)
        assert len(prefix) == 8 and all(c in "0123456789abcdef" for c in prefix)
        assert prefix not in text
    else:
        with pytest.raises(checks.Refused):
            checks.token_prefix(env)


# ---- the filled facts ----


#: The placeholders' own sentences, as the frozen CRITERIA.md writes them (§2.4, §2.5).
FROZEN = """
- **Instrument tree at the run commit:** `[FILL at "run commit filled"]`. **Run commit:** `[FILL at
  "run commit filled"]`. Both are filled by the dated "run commit filled" commit on `master`, after
- `MANIFEST.json` is new: format 1, author model `claude-opus-5-5`, label `[FILL at "sheet
  filled"]`.
- Its manifest digest is `[FILL at "sheet filled"]`.
"""


def test_the_placeholders_are_the_frozen_file_s_own_sentences() -> None:
    text = " ".join((HERE / "CRITERIA.md").read_text().split())
    for line in FROZEN.strip().splitlines():
        # the filled file keeps every word around its placeholders
        words = line.strip().split("`[FILL")[0].strip()
        assert words in text, words


def test_the_filled_facts_are_read_and_a_placeholder_is_not_a_fact() -> None:
    frozen = FROZEN
    assert C.filled(frozen) == {}
    tree, commit, digest = "a" * 40, "b" * 40, "c" * 64
    filled = (
        frozen.replace(
            '`[FILL at "run commit filled"]`. **Run commit:** `[FILL at\n  "run commit filled"]`',
            f"`{tree}`. **Run commit:** `{commit}`",
        )
        .replace('label `[FILL at "sheet\n  filled"]`', "label `an\n  arm F label`")
        .replace(
            'Its manifest digest is `[FILL at "sheet filled"]`',
            f"Its manifest digest is `{digest}`",
        )
    )
    assert C.filled(filled) == {
        "instrument_tree": tree,
        "run_commit": commit,
        "arm_f_manifest": digest,
        "arm_f_label": "an arm F label",
    }


# ---- L2's path rule ----


def _repo(tmp_path: Path) -> tuple[Path, Callable[..., str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@e.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@e.invalid",
    }

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    return repo, git


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body)


def test_l2_admits_only_the_backport_s_paths_and_master_s_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, git = _repo(tmp_path)
    _write(repo, {"src/physgate/evaluation/inject/corpus.py": "old\n", "README.md": "r\n"})
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    monkeypatch.setattr(C, "R_PG_01_COMMIT", base)
    # master: the freeze, the scripts, the sheet, the fill, then scripts again after the fill
    git("checkout", "-q", "-b", "master")
    _write(repo, {"experiments/R-PG-01b/CRITERIA.md": "c [FILL]\n"})
    git("add", "-A")
    git("commit", "-q", "-m", "freeze")
    monkeypatch.setattr(C, "FREEZE_COMMIT", git("rev-parse", "HEAD"))
    _write(repo, {"experiments/R-PG-01b/launch.sh": "l\n"})
    git("add", "-A")
    git("commit", "-q", "-m", "scripts")
    _write(
        repo, {f"{C.ARM_F_CORPUS}/sources.json": "s\n", "experiments/R-PG-01b/sheet/t.md": "t\n"}
    )
    git("add", "-A")
    git("commit", "-q", "-m", "sheet")
    _write(repo, {"experiments/R-PG-01b/CRITERIA.md": "c filled\n"})
    git("commit", "-qam", "filled")
    _write(repo, {"experiments/R-PG-01b/launch.sh": "l2\n"})
    git("commit", "-qam", "scripts again")
    # the run branch: base plus the backport and master's files, the frozen CRITERIA.md
    git("checkout", "-q", "-b", "run", base)
    _write(repo, {"src/physgate/evaluation/inject/corpus.py": "new\n"})
    git(
        "checkout",
        "master",
        "--",
        "experiments/R-PG-01b/launch.sh",
        f"{C.ARM_F_CORPUS}/sources.json",
    )
    git("checkout", C.FREEZE_COMMIT, "--", "experiments/R-PG-01b/CRITERIA.md")
    git("add", "-A")
    git("commit", "-q", "-m", "run")
    found = checks.l2(repo, "master")
    assert found["paths outside §2.4"] == [] and found["paths_changed"] == 4
    assert found["scripts_commit"] == git("rev-parse", "master")
    # a change outside §2.4 is refused
    _write(repo, {"README.md": "changed\n"})
    git("commit", "-qam", "outside")
    with pytest.raises(checks.Refused, match="outside"):
        checks.l2(repo, "master")
    git("reset", "-q", "--hard", "HEAD~1")
    # a script blob that is not master's last scripts commit's is refused
    _write(repo, {"experiments/R-PG-01b/launch.sh": "l\n"})
    git("commit", "-qam", "drift")
    with pytest.raises(checks.Refused, match="experiments/R-PG-01b blobs"):
        checks.l2(repo, "master")
    git("reset", "-q", "--hard", "HEAD~1")
    # a script the run branch lacks is refused
    git("rm", "-q", "experiments/R-PG-01b/launch.sh")
    git("commit", "-qm", "lacks")
    with pytest.raises(checks.Refused, match="experiments/R-PG-01b blobs"):
        checks.l2(repo, "master")
    git("reset", "-q", "--hard", "HEAD~1")
    # the filled CRITERIA.md on the run branch is refused: it carries the frozen one
    git("checkout", "master", "--", "experiments/R-PG-01b/CRITERIA.md")
    git("commit", "-qm", "filled on the run branch")
    with pytest.raises(checks.Refused, match="frozen CRITERIA.md"):
        checks.l2(repo, "master")
    git("reset", "-q", "--hard", "HEAD~1")
    # the sheet copy on the run branch is refused
    git("checkout", "master", "--", "experiments/R-PG-01b/sheet/t.md")
    git("commit", "-qm", "copy")
    with pytest.raises(checks.Refused):
        checks.l2(repo, "master")


# ---- the round's end, on invented logs ----


def _run(tmp: Path, name: str, rubric: str | None = None, unavailable: int = 0) -> Path:
    run = tmp / name
    digest = rubric or C.RUBRIC_SHA256["electrical"]
    inj = [T.planned("r1", "electrical"), T.ran("r1", "fail", [], rubric=digest)]
    for n in range(unavailable):
        inj += [
            T.planned(f"u{n}", "electrical"),
            T.unavailable(f"u{n}", "infrastructure", True),
            T.unavailable(f"u{n}", "infrastructure", False),
        ]
    inj.append(T.gate("r1", ("units", "fail")))
    T.write_jsonl(run / "events.jsonl", inj)
    T.write_jsonl(
        run / "controls" / "events.jsonl",
        [
            T.planned("t1", "electrical"),
            T.ran("t1", "pass", [], rubric=digest),
            T.gate("t1", ("units", "pass")),
        ],
    )
    return run


def test_the_round_s_end_counts_infrastructure_ends_after_their_retry(tmp_path: Path) -> None:
    assert checks.cascade(_run(tmp_path, "a", unavailable=2)) == 2
    assert checks.cascade(_run(tmp_path, "b")) == 0


def test_every_review_line_is_held_to_its_role_s_rubric_digest(tmp_path: Path) -> None:
    assert checks.rubric_mismatches(_run(tmp_path, "a")) == (0, 2)
    assert checks.rubric_mismatches(_run(tmp_path, "b", rubric="0" * 64)) == (2, 2)


def test_gate_records_are_compared_by_subtask_and_side(tmp_path: Path) -> None:
    a, b = checks.gate_records(_run(tmp_path, "a")), checks.gate_records(_run(tmp_path, "b"))
    assert a == b and set(a) == {"i:r1", "t:t1"}


# ---- the round's end, on invented attempts (§12) ----

#: The invented attempt's slots: arm I in 3, arm F in 1.
SLOTS_I_F = {"I": 3, "F": 1}
SID = "00000000-0000-4000-8000-{:012d}"


def _log(
    path: Path,
    prefix: str,
    *,
    infra: int = 0,
    final: bool = True,
    gates: bool = True,
    rubric: str | None = None,
    sessions: dict[int, str] | None = None,
    gate_extra: bool = False,
) -> None:
    """One invented log of 40 subtasks, each planned, reviewed and gated.

    As ``run_instrument`` writes them; ``infra`` reviews end unavailable for infrastructure
    after their retry; with ``final`` false the last review's retry never came; with ``gates``
    false no gate line.
    """
    ids = [f"{prefix}{k:03d}" for k in range(C.DENOMINATOR)]
    rows: list[dict[str, Any]] = [T.planned(i, "electrical") for i in ids]
    for k, i in enumerate(ids):
        sid = (sessions or {}).get(k)
        if k < infra:
            rows += [
                T.unavailable(i, "infrastructure", True),
                T.unavailable(i, "infrastructure", False, session=sid),
            ]
        elif not final and k == len(ids) - 1:
            rows.append(T.unavailable(i, "infrastructure", True, session=sid))
        else:
            digest = rubric or C.RUBRIC_SHA256["electrical"]
            rows.append(T.ran(i, "pass", [], session=sid, rubric=digest))
    if gates:
        rows += [T.gate(i, ("units", "pass")) for i in ids]
    if gate_extra:
        rows[-1] = T.gate(ids[-1], ("units", "pass"), ("thermal", "unchecked"))
    T.write_jsonl(path, rows)


def _arm(home: Path, runs: Path, slot: int, *, rows: int = C.DENOMINATOR, **kw: Any) -> Path:
    """One arm's run directory: both logs and its results file (``rows`` rows; none if -1)."""
    run = C.places(home, slot, runs)["run"]
    twin_kw = {k: v for k, v in kw.items() if k in ("rubric",)}
    _log(run / "events.jsonl", "r", **kw)
    _log(run / "controls" / "events.jsonl", "t", **twin_kw)
    if rows >= 0:
        T.write_jsonl(run / "results.jsonl", [{"artefact": f"a{k}"} for k in range(rows)])
    return run


def _stream_file(home: Path, slot: int, sid: str, text: str) -> None:
    d = C.places(home, slot)["scratch"] / sid / "session"
    d.mkdir(parents=True, exist_ok=True)
    (d / "stdout.jsonl").write_text(text)


def _records(
    tmp: Path, monkeypatch: pytest.MonkeyPatch, prior: list[dict[str, Any]] | None = None
) -> tuple[Path, Path, Path]:
    """HOME, the records and this attempt's launch directory, as ``checks`` reads them."""
    home, runs = tmp / "home", tmp / "home" / "runs"
    launch = runs / "launch-1-9"
    launch.mkdir(parents=True)
    monkeypatch.setattr(checks, "HOME", home)
    monkeypatch.setattr(checks, "RUNS", runs)
    monkeypatch.setattr(checks, "SLOTS", runs / "slots.json")
    attempts = list(prior or [])
    attempts.append(
        {
            "round": 1,
            "attempt": len(attempts) + 1,
            "slots": SLOTS_I_F,
            "launch": str(launch),
            "started_utc": "T",
        }
    )
    records = {"seed": C.SLOT_SEED, "draw": checks.draw_slots(), "attempts": attempts}
    (runs / "slots.json").write_text(json.dumps(records))
    return home, runs, launch


def _after(
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exits: dict[str, Any] | None = None,
    watcher: str = "WATCHER: every arm ended\n",
    arm: dict[str, dict[str, Any]] | None = None,
    regate: dict[int, int | None] | None = None,
    prior: list[dict[str, Any]] | None = None,
    streams: dict[int, dict[str, str]] | None = None,
    l1: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``checks.after`` on one invented attempt of round 1: a complete one unless told."""
    home, runs, launch = _records(tmp, monkeypatch, prior)
    if l1 is not None:
        (launch / "L1.json").write_text(json.dumps(l1) + "\n")
    for name, slot in SLOTS_I_F.items():
        _arm(home, runs, slot, **(arm or {}).get(name, {}))
        for sid, text in (streams or {}).get(slot, {}).items():
            _stream_file(home, slot, sid, text)
    shown = {str(s): 0 for s in SLOTS_I_F.values()} if exits is None else exits
    (launch / "exits.json").write_text(json.dumps(shown))
    (launch / "watcher.log").write_text(watcher)
    counts = regate or {}
    monkeypatch.setattr(
        checks,
        "regate_count",
        lambda _checkout, _arm, run, _into: counts.get(int(run.name.split("-")[1]), 0),
    )
    found = checks.after(1, launch, C.REPO)
    found["records"] = json.loads((runs / "slots.json").read_text())
    return found


def test_the_owner_s_waiver_is_a_disclosed_deviation_of_the_round_and_voids_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiver = OWNER_WAIVES["owner_waiver"]
    l1 = {
        "check": "L1",
        "owner_confirmed_no_other_session": False,
        "owner_statement": "waived",
        "owner_waiver": waiver,
    }
    found = _after(tmp_path, monkeypatch, l1=l1)
    assert found["valid"] is True and found["void_causes"] == []
    assert found["deviations"] == [f"§11's idle-account rule waived by the owner at L1: {waiver}"]
    assert found["records"]["attempts"][-1]["deviations"] == found["deviations"]
    assert found["records"]["attempts"][-1]["valid"] is True


@pytest.mark.parametrize(
    "l1",
    [
        {"check": "L1", "owner_confirmed_no_other_session": True, "owner_statement": "confirmed"},
        # round 1's record, written before the waiver existed
        {"check": "L1", "owner_confirmed_no_other_session": True},
    ],
    ids=["confirmed", "confirmed-before-the-waiver"],
)
def test_a_confirmed_round_has_no_waiver_deviation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, l1: dict[str, Any]
) -> None:
    found = _after(tmp_path, monkeypatch, l1=l1)
    assert found["valid"] is True and found["deviations"] == []


def test_a_complete_attempt_is_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    found = _after(tmp_path, monkeypatch)
    assert found["valid"] is True, found["void_causes"]
    assert found["void_causes"] == [] and found["deviations"] == []
    assert found["records"]["attempts"][-1]["valid"] is True


@pytest.mark.parametrize(
    ("exits", "arm"),
    [
        # Python's exit for an uncaught exception is 1, as inject's for a run with a review
        # that gave no verdict: the run is held to its files, not to its exit
        ({"3": 1, "1": 1}, {"I": {"rows": -1}}),
        ({"3": 0, "1": 0}, {"F": {"rows": 39}}),
        ({"3": 0, "1": 0}, {"I": {"final": False}}),
        ({"3": 0, "1": 0}, {"F": {"gates": False}}),
        ({"3": 2, "1": 0}, None),
        ({"3": 143, "1": 0}, None),
        ({"3": 0}, None),
    ],
    ids=[
        "exit-1-no-results",
        "39-rows",
        "a-retry-never-came",
        "no-gate-lines",
        "exit-2",
        "killed",
        "an-exit-missing",
    ],
)
def test_a_crashed_or_killed_process_voids_the_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exits: dict[str, int],
    arm: dict[str, dict[str, Any]] | None,
) -> None:
    found = _after(tmp_path, monkeypatch, exits=exits, arm=arm)
    assert "a crashed or killed process" in found["void_causes"]
    assert found["valid"] is False and found["records"]["attempts"][-1]["valid"] is False


def test_a_partial_last_line_of_a_killed_process_is_read_as_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, runs, launch = _records(tmp_path, monkeypatch)
    for slot in SLOTS_I_F.values():
        run = _arm(home, runs, slot, rows=-1)
        with (run / "events.jsonl").open("a") as f:
            f.write('{"kind": "review_ran", "subtask_id": "r0')
    (launch / "exits.json").write_text(json.dumps({"3": 1, "1": 1}))
    monkeypatch.setattr(checks, "regate_count", lambda *_: None)
    found = checks.after(1, launch, C.REPO)
    assert "a crashed or killed process" in found["void_causes"]


@pytest.mark.parametrize(
    ("infra_i", "infra_f", "void"), [(1, 1, False), (2, 1, True), (0, 3, True)]
)
def test_three_infrastructure_ends_in_a_round_void_it_and_two_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, infra_i: int, infra_f: int, void: bool
) -> None:
    arm = {"I": {"infra": infra_i}, "F": {"infra": infra_f}}
    found = _after(tmp_path, monkeypatch, arm=arm)
    assert ("an infrastructure cascade" in found["void_causes"]) is void
    assert found["valid"] is (not void)


def _sheet_stream(lines: int, returned: int) -> str:
    body = "\n".join(
        f"{n}\t" + (f'"{C.LAST_ROW_ID}": {{' if n == lines else "x") for n in range(1, returned + 1)
    )
    events = [
        {"type": "system", "subtype": "init", "cwd": "/r/read/worktree"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "/r/read/worktree/parts_sheet.json"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": body}]},
        },
    ]
    return "".join(json.dumps(e) + "\n" for e in events)


def test_a_cut_read_in_either_arm_voids_the_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = SID.format(7)
    lines = C.SHEET_LINES["F"]
    found = _after(
        tmp_path,
        monkeypatch,
        arm={"F": {"sessions": {0: sid}}},
        streams={SLOTS_I_F["F"]: {sid: _sheet_stream(lines, lines - 10)}},
    )
    assert found["void_causes"] == ["a cut read"]
    whole = _after(
        tmp_path / "w",
        monkeypatch,
        arm={"F": {"sessions": {0: sid}}},
        streams={SLOTS_I_F["F"]: {sid: _sheet_stream(lines, lines)}},
    )
    assert whole["valid"] is True


def test_a_second_cut_in_the_same_round_stops_the_experiment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = SID.format(7)
    lines = C.SHEET_LINES["I"]
    prior = [
        {
            "round": 1,
            "attempt": 1,
            "slots": {"I": 4, "F": 2},
            "launch": "elsewhere",
            "void_causes": ["a cut read"],
            "valid": False,
        }
    ]
    found = _after(
        tmp_path,
        monkeypatch,
        arm={"I": {"sessions": {3: sid}}},
        streams={SLOTS_I_F["I"]: {sid: _sheet_stream(lines, 5)}},
        prior=prior,
    )
    assert "a cut read" in found["void_causes"]
    assert "a second cut read in round 1" in found["records"]["stopped"]["reason"]
    with pytest.raises(checks.Refused, match="stopped"):
        checks.refuse_if_stopped(found["records"])
    # one cut alone does not stop it
    first = _after(
        tmp_path / "one",
        monkeypatch,
        arm={"I": {"sessions": {3: sid}}},
        streams={SLOTS_I_F["I"]: {sid: _sheet_stream(lines, 5)}},
    )
    assert "stopped" not in first["records"]
    checks.refuse_if_stopped(first["records"])


def test_a_stop_is_recorded_and_refuses_every_later_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _records(tmp_path, monkeypatch)
    found = checks.stop(1, "L10 found a cut read")
    assert found["stopped"]["reason"] == "L10 found a cut read"
    records = checks.read_slots()
    with pytest.raises(checks.Refused, match="L10 found a cut read"):
        checks.refuse_if_stopped(records)


def test_a_usage_limit_voids_the_attempt_by_the_watcher_s_line_or_by_its_own_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    by_watcher = _after(
        tmp_path / "a",
        monkeypatch,
        watcher="ABORT 2026-10-23T10:00:00Z: usage_limit_reached files 1\n",
        exits={"3": 143, "1": 143},
        arm={"I": {"rows": -1}, "F": {"rows": -1}},
    )
    assert "usage limit" in by_watcher["void_causes"]
    # the watcher saw nothing (it ended first): the round's end searches the roots itself
    sid = SID.format(9)
    found = _after(
        tmp_path / "b",
        monkeypatch,
        arm={"F": {"sessions": {0: sid}}},
        streams={SLOTS_I_F["F"]: {sid: '{"type":"result","error":"usage_limit_reached"}\n'}},
    )
    assert found["void_causes"] == ["usage limit"]
    assert found["usage_limit_files"] == 1
    assert checks.usage_limit_voids(found["records"], 1) == 1


def test_each_deviation_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rubric = _after(tmp_path / "a", monkeypatch, arm={"I": {"rubric": "0" * 64}})
    assert rubric["deviations"] == ["a review line's rubric_sha256 is not its role's pinned digest"]
    regate = _after(tmp_path / "b", monkeypatch, regate={3: 1})
    assert regate["deviations"] == ["the gate's records differ"]
    across = _after(tmp_path / "c", monkeypatch, arm={"F": {"gate_extra": True}})
    assert across["deviations"] == ["the gate's records differ"]
    assert across["gate_records_identical_across_arms"] is False
    unrun = _after(tmp_path / "d", monkeypatch, regate={1: None})
    assert unrun["deviations"] == ["regate_r6.py did not run on a complete run"]
    for found in (rubric, regate, across, unrun):
        assert found["valid"] is True  # a deviation is not a void cause


def test_an_arm_the_fallback_never_started_is_recorded_as_not_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, runs, launch = _records(tmp_path, monkeypatch)
    _arm(home, runs, SLOTS_I_F["I"], rows=-1)
    (launch / "exits.json").write_text(json.dumps({"3": 143, "1": None}))
    (launch / "watcher.log").write_text("ABORT x: usage_limit_reached files 1\n")
    monkeypatch.setattr(checks, "regate_count", lambda *_: None)
    found = checks.after(1, launch, C.REPO)
    assert "usage limit" in found["void_causes"]
    assert found["per_slot"]["slot 1"]["started"] is False
    assert found["per_slot"]["slot 3"]["started"] is True


# ---- §11's fallback: the second arm, in the next window ----


def test_the_second_arm_does_not_start_after_the_first_arm_s_watcher_stopped_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "watcher.log").write_text("ABORT x: usage_limit_reached files 1\n")
    assert checks.second_arm(tmp_path, since=0.0, now=100.0) is None


@pytest.mark.parametrize(
    ("now_h", "wait_h"),
    [(1.0, 4.0), (4.99, 0.01), (5.0, 0.0), (7.0, 3.0), (10.5, 4.5)],
)
def test_the_second_arm_starts_at_the_next_5_hour_boundary_after_the_first_arm_ends(
    tmp_path: Path, now_h: float, wait_h: float
) -> None:
    (tmp_path / "watcher.log").write_text("WATCHER x: every arm ended\n")
    wait = checks.second_arm(tmp_path, since=1000.0, now=1000.0 + now_h * 3600)
    assert wait == pytest.approx(wait_h * 3600)


def test_the_second_arm_s_command_reads_its_start_as_utc(tmp_path: Path) -> None:
    (tmp_path / "watcher.log").write_text("WATCHER x: every arm ended\n")
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    done = subprocess.run(
        [sys.executable, str(HERE / "checks.py"), "second-arm", "--launch", str(tmp_path),
         "--since", since],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    wait = json.loads(done.stdout)["wait_s"]
    assert 4 * 3600 - 5 <= wait <= 4 * 3600 + 5


# ---- L1 ----


_SID_L1 = "00000000-0000-4000-8000-000000000042"


def _proc(*argv: str) -> tuple[int, list[str]]:
    return (4242, list(argv))


@pytest.mark.parametrize(
    ("argv", "alive"),
    [
        (("/home/u/pinned/claude-2.1.301", "-p", "--session-id", "x"), True),
        (("claude",), True),
        (("/usr/bin/python3", "-c", "held", "/home/u/pinned/claude-2.1.301", "-p"), True),
        (("/r/.venv/bin/python", "/r/.venv/bin/physgate", "inject", "--corpus", "c"), True),
        (("uv", "run", "--frozen", "physgate", "inject", "--corpus", "c"), True),
        (("bash", "experiments/R-PG-01b/launch.sh", "--round", "1"), False),
        (("/r/.venv/bin/physgate", "gate", "x"), False),
        (("vim", "notes-on-claude.md"), False),
        (("sshd: ubuntu@pts/0",), False),
    ],
)
def test_l1_knows_a_claude_or_inject_process_by_its_arguments(
    argv: tuple[str, ...], alive: bool
) -> None:
    assert bool(checks.live_sessions([_proc(*argv)])) is alive


def _checkout(tmp: Path, home: Path, *, filled_commit: str | None = None) -> Path:
    """A checkout at a pushed tag, and an origin whose master holds the filled CRITERIA.md."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@e.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@e.invalid",
    }

    def git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
        ).stdout.strip()

    origin = tmp / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
    checkout = home / C.CHECKOUT_NAME
    checkout.mkdir(parents=True)
    git(checkout, "init", "-q", "-b", "run")
    git(checkout, "remote", "add", "origin", str(origin))
    (checkout / "x.txt").write_text("run\n")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", "run")
    head = git(checkout, "rev-parse", "HEAD")
    git(checkout, "tag", C.RUN_TAG)
    git(checkout, "push", "-q", "origin", f"refs/tags/{C.RUN_TAG}")
    # master: the filled CRITERIA.md, on a branch of its own
    master = tmp / "master"
    git(tmp, "clone", "-q", str(origin), str(master))
    git(master, "checkout", "-q", "--orphan", "master")
    (master / "experiments" / "R-PG-01b").mkdir(parents=True)
    commit = filled_commit or head
    (master / "experiments" / "R-PG-01b" / "CRITERIA.md").write_text(
        f"- **Instrument tree at the run commit:** `{'a' * 40}`. **Run commit:**\n  `{commit}`.\n"
    )
    git(master, "add", "-A")
    git(master, "commit", "-q", "-m", "filled")
    git(master, "push", "-q", "origin", "master")
    git(checkout, "fetch", "-q", "origin")
    return checkout


#: The owner's statements for a round (§11): the confirmation, and the recorded waiver.
OWNER_CONFIRMS = {"account_label": "a trial", "no_other_session_during_round": True}
OWNER_WAIVES = {
    "account_label": "a trial",
    "no_other_session_during_round": False,
    "owner_waiver": "other sessions of the owner run on the account; decided 30.10.2026",
}


def _l1(
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    filled_commit: str | None = None,
    procs: list[tuple[int, list[str]]] | None = None,
    stopped: bool = False,
    dry: bool = True,
    login: list[str] | None = None,
    owner: Any = None,
) -> dict[str, Any]:
    home = tmp / "home"
    checkout = _checkout(tmp, home, filled_commit=filled_commit)
    runs = tmp / "trial"
    runs.mkdir()
    said = OWNER_CONFIRMS if owner is None else owner
    (runs / "owner-1.json").write_text(json.dumps(said))
    if stopped:
        (runs / "slots.json").write_text(
            json.dumps({"draw": checks.draw_slots(), "attempts": [], "stopped": {"reason": "x"}})
        )
    monkeypatch.setattr(checks, "HOME", home)
    monkeypatch.setattr(checks, "RUNS", runs)
    monkeypatch.setattr(checks, "SLOTS", runs / "slots.json")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(checks, "own_processes", lambda: procs or [])
    for rel in login or []:
        (home / C.SCRATCH_NAME / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / C.SCRATCH_NAME / rel).write_text("{}\n")
    return checks.l1(1, checkout, "origin/master", dry)


def test_l1_holds_a_checkout_at_the_filled_run_commit_and_never_reads_the_token_in_a_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # no env file at all: a check-only trial never reads the token
    found = _l1(tmp_path, monkeypatch)
    assert found["the filled run commit"] == found["head"]
    assert found["token_sha256_prefix"] == "not read: checks only"
    assert not (tmp_path / "trial" / "slots.json").exists()


def test_l1_refuses_a_head_that_is_not_the_filled_run_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(checks.Refused, match="filled run commit"):
        _l1(tmp_path, monkeypatch, filled_commit="f" * 40)


def test_l1_refuses_while_a_claude_or_inject_process_of_the_account_is_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alive = [_proc("/home/u/pinned/claude-2.1.301", "-p")]
    with pytest.raises(checks.Refused, match="1 claude or inject process"):
        _l1(tmp_path, monkeypatch, procs=alive)


@pytest.mark.parametrize(
    "rel",
    [
        f"rpb-4/{_SID_L1}/session/config/.credentials.json",
        f"rpb-smoke-1-2/s1/{_SID_L1}/session/config/.credentials.json",
        f"rpb-7/{_SID_L1}/session/state/key",
    ],
)
def test_l1_refuses_while_a_login_file_of_the_run_s_sessions_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rel: str
) -> None:
    with pytest.raises(checks.Refused, match="login file"):
        _l1(tmp_path, monkeypatch, login=[rel])


def test_l1_reads_no_other_experiment_s_review_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _l1(
        tmp_path, monkeypatch, login=[f"rp2-1-1/{_SID_L1}/session/config/.credentials.json"]
    )
    assert found["login_files_left"] == 0


def test_l1_refuses_after_the_experiment_has_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(checks.Refused, match="stopped"):
        _l1(tmp_path, monkeypatch, stopped=True)


def test_l1_records_the_owner_s_confirmation_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _l1(tmp_path, monkeypatch)
    assert found["owner_confirmed_no_other_session"] is True
    assert found["owner_statement"] == "confirmed"
    assert "owner_waiver" not in found


def test_l1_takes_the_owner_s_recorded_waiver_of_the_idle_account_and_records_its_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _l1(tmp_path, monkeypatch, owner=OWNER_WAIVES)
    assert found["owner_confirmed_no_other_session"] is False
    assert found["owner_statement"] == "waived"
    assert found["owner_waiver"] == OWNER_WAIVES["owner_waiver"]
    assert found["account_label"] == "a trial"


@pytest.mark.parametrize(
    "owner",
    [
        {"account_label": "a trial"},
        {"account_label": "a trial", "no_other_session_during_round": None},
        {"account_label": "a trial", "no_other_session_during_round": "true"},
        {"account_label": "a trial", "no_other_session_during_round": 1},
        {"account_label": "a trial", "no_other_session_during_round": 0, "owner_waiver": "w"},
        {"account_label": "a trial", "no_other_session_during_round": False},
        {"account_label": "a trial", "no_other_session_during_round": False, "owner_waiver": ""},
        {
            "account_label": "a trial",
            "no_other_session_during_round": False,
            "owner_waiver": " \n\t",
        },
        {"account_label": "a trial", "no_other_session_during_round": False, "owner_waiver": 1},
        {
            "account_label": "a trial",
            "no_other_session_during_round": False,
            "owner_waiver": ["waived"],
        },
        {"account_label": "a trial", "no_other_session_during_round": False, "owner_waiver": None},
        {"account_label": "a trial", "no_other_session_during_round": True, "owner_waiver": "w"},
        {"account_label": "a trial", "no_other_session_during_round": True, "owner_waiver": ""},
    ],
    ids=[
        "missing",
        "null",
        "a-string",
        "one",
        "zero-with-a-waiver",
        "false-without-a-waiver",
        "an-empty-waiver",
        "a-blank-waiver",
        "a-number-for-a-waiver",
        "a-list-for-a-waiver",
        "a-null-waiver",
        "confirmed-and-waived",
        "confirmed-and-an-empty-waiver",
    ],
)
def test_l1_refuses_an_owner_statement_that_neither_confirms_nor_waives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: dict[str, Any]
) -> None:
    with pytest.raises(checks.Refused, match="owner"):
        _l1(tmp_path, monkeypatch, owner=owner)


@pytest.mark.parametrize(
    "owner", [[OWNER_WAIVES], "waived", None, 1], ids=["a-list", "a-string", "null", "a-number"]
)
def test_l1_refuses_an_owner_statement_that_is_no_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: Any
) -> None:
    home = tmp_path / "home"
    checkout = _checkout(tmp_path, home)
    runs = tmp_path / "trial"
    runs.mkdir()
    (runs / "owner-1.json").write_text(json.dumps(owner))
    monkeypatch.setattr(checks, "HOME", home)
    monkeypatch.setattr(checks, "RUNS", runs)
    monkeypatch.setattr(checks, "SLOTS", runs / "slots.json")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(checks, "own_processes", lambda: [])
    with pytest.raises(checks.Refused, match="owner statement"):
        checks.l1(1, checkout, "origin/master", True)


def test_l1_reads_the_token_in_a_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(checks.Refused, match="env file"):
        _l1(tmp_path, monkeypatch, dry=False)


# ---- the ledger line ----


def _session(root: Path, sid: str, tokens: int | None) -> None:
    d = root / sid / "session"
    d.mkdir(parents=True)
    lines = [{"type": "system"}]
    if tokens is not None:
        lines.append(
            {
                "type": "result",
                "usage": {
                    "input_tokens": tokens - 3,
                    "output_tokens": 1,
                    "cache_read_input_tokens": 1,
                    "cache_creation_input_tokens": 1,
                },
            }
        )
    (d / "stdout.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))


def test_the_ledger_line_sums_every_session_s_result_line_void_attempts_included(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "slots.json").write_text(
        json.dumps(
            {
                "draw": {"I1": 2, "F1": 1, "I2": 3, "F2": 4},
                "attempts": [
                    {
                        "round": 1,
                        "attempt": 1,
                        "slots": {"I": 2, "F": 1},
                        "started_utc": "T1",
                        "ended_utc": "T2",
                        "valid": False,
                    },
                    {
                        "round": 1,
                        "attempt": 2,
                        "slots": {"I": 6, "F": 5},
                        "started_utc": "T3",
                        "ended_utc": "T4",
                        "valid": True,
                    },
                ],
            }
        )
    )
    sid = "00000000-0000-4000-8000-0000000000{:02d}"
    for slot, n in ((2, 1), (1, 2), (6, 3), (5, 4)):
        _session(tmp_path / C.SCRATCH_NAME / f"rpb-{slot}", sid.format(n), 1000 * n)
    _session(tmp_path / C.SCRATCH_NAME / f"rpb-{5}", sid.format(9), None)
    launch = runs / "launch-1-2"
    launch.mkdir()
    (launch / "L1.json").write_text(
        json.dumps({"account_label": "the run account", "token_sha256_prefix": "abcd1234"})
    )
    (launch / "l11.json").write_text(
        json.dumps({"T": 400000, "projected_5h": 48000000, "carried_in_5h": 80000000})
    )
    _session(tmp_path / C.SCRATCH_NAME / "rpb-smoke-1-2" / "s1", sid.format(10), 500)
    found = ledger.round_line(1, runs, tmp_path)
    assert found["review_sessions"] == 5 and found["review_sessions_without_result"] == 1
    assert found["review_tokens"] == 10_000 and found["smoke_tokens"] == 500
    assert (found["started_utc"], found["ended_utc"], found["valid_attempt"]) == ("T1", "T4", 2)
    assert "the run account" in found["line"] and "48000000" in found["line"]


# ---- the watcher ----

#: Only the run machine is ever signalled: off Linux the watcher signals nothing, and these
#: tests, which stop processes they started themselves, run there alone.
ON_THE_RUN_MACHINE = sys.platform == "linux"
signals = pytest.mark.skipif(not ON_THE_RUN_MACHINE, reason="signals are sent on Linux alone")


def _group(seconds: int) -> subprocess.Popen[bytes]:
    return subprocess.Popen(["sleep", str(seconds)], start_new_session=True)


def _watch(log: Path, *triples: Any) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(HERE / "abort_on_limit.sh"), str(log), *(str(x) for x in triples)],
        env={**os.environ, "RPB_WATCH_SECONDS": "1"},
    )


def _started(pid: int) -> str:
    return " ".join(
        subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        ).stdout.split()
    )


def _stand_in(root: Path, seconds: int, *, record: bool = True) -> subprocess.Popen[bytes]:
    """A stand-in session, as the instrument spawns and records one.

    Its own group, its id on its command line, its process record and its credential directory
    under the review root.
    """
    sid = f"00000000-0000-4000-8000-{random.randrange(10**12):012d}"
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(int(__import__('sys').argv[3]))",
         "--session-id", sid, str(seconds)],
        start_new_session=True,
    )  # fmt: skip
    sdir = root / sid / "session"
    (sdir / "config").mkdir(parents=True)
    (sdir / "config" / "credential").write_text("x\n")
    if record:
        time.sleep(0.3)
        (sdir / "process.json").write_text(
            json.dumps({"pid": proc.pid, "started": _started(proc.pid), "session_id": sid})
        )
    return proc


@signals
def test_the_watcher_stops_every_arm_and_every_recorded_session_at_the_first_usage_limit(
    tmp_path: Path,
) -> None:
    a, b = _group(60), _group(60)
    dirs = [tmp_path / n for n in ("run-1", "rpb-1", "run-2", "rpb-2")]
    for d in dirs:
        d.mkdir()
    session = _stand_in(dirs[1], 60)
    unrecorded = _stand_in(dirs[3], 20, record=False)
    log = tmp_path / "watcher.log"
    watcher = _watch(log, a.pid, dirs[0], dirs[1], b.pid, dirs[2], dirs[3])
    time.sleep(1.5)
    assert a.poll() is None and b.poll() is None and session.poll() is None
    (dirs[3] / "stdout.jsonl").write_text('{"type":"result","error":"usage_limit_reached"}\n')
    assert watcher.wait(timeout=60) == 0
    assert a.wait(timeout=10) == -signal.SIGTERM and b.wait(timeout=10) == -signal.SIGTERM
    assert session.wait(timeout=10) == -signal.SIGTERM
    # a process no record of this run names is never signalled
    assert unrecorded.poll() is None
    assert not list(tmp_path.glob("*/*/session/config"))
    text = log.read_text()
    assert "ABORT" in text and "usage_limit_reached files 1" in text
    assert '"stopped": 1' in text and '"configs_removed": 2' in text
    unrecorded.wait(timeout=30)


@signals
def test_the_watcher_signals_no_session_whose_record_does_not_prove_it(tmp_path: Path) -> None:
    root = tmp_path / "rpb-1"
    root.mkdir()
    session = _stand_in(root, 20)
    record = next(root.glob("*/session/process.json"))
    forged = json.loads(record.read_text())
    record.write_text(json.dumps({**forged, "started": "Thu Jan  1 00:00:00 1970"}))
    found = checks.stop_sessions([root])
    assert found["stopped"] == 0 and found["not_proven"] == 1
    assert session.poll() is None
    session.wait(timeout=30)


def test_off_the_run_machine_nothing_is_signalled(tmp_path: Path) -> None:
    if ON_THE_RUN_MACHINE:
        pytest.skip("off the run machine only")
    with pytest.raises(checks.Refused, match="run machine"):
        checks.stop_sessions([tmp_path])
    a = _group(4)
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "x.jsonl").write_text('{"error":"usage_limit_reached"}\n')
    log = tmp_path / "watcher.log"
    watcher = _watch(log, a.pid, tmp_path / "r", tmp_path / "r")
    assert watcher.wait(timeout=30) == 1
    assert a.poll() is None  # not signalled: it ends by itself
    assert "ABORT" in log.read_text() and "nothing signalled" in log.read_text()
    a.wait(timeout=30)


# ---- nothing outside a root is touched, and no forged record is believed ----


def _sid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _kept(d: Path) -> Path:
    """A directory holding a file nothing may delete."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "keep.txt").write_text("keep\n")
    return d


def test_the_credential_cleanup_never_follows_a_symlink_out_of_the_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    root = tmp_path / "review-scratch" / "rpb-3"
    root.mkdir(parents=True)
    # a session directory that is a symlink out of the root
    _kept(outside / "a" / "session" / "config")
    (root / _sid(1)).symlink_to(outside / "a")
    # a session/ that is a symlink out of the root
    _kept(outside / "b" / "config")
    (root / _sid(2)).mkdir()
    (root / _sid(2) / "session").symlink_to(outside / "b")
    # a config that is a symlink out of the root
    (root / _sid(3) / "session").mkdir(parents=True)
    (root / _sid(3) / "session" / "config").symlink_to(_kept(outside / "c"))
    # a credential directory of the run's own: it goes
    _kept(root / _sid(4) / "session" / "config")
    # a directory not named as a session is not one
    _kept(root / "elsewhere" / "session" / "config")
    found = checks.remove_credentials([root])
    assert found["configs_removed"] == 1 and found["refused_symlinks"] == 3
    # a symlink standing where a session's directory, session/ or config/ belongs leaves the
    # removal of whatever lies behind it unconfirmed: the cleanup fails closed
    assert found["login_files_left"] == 0 and found["unconfirmed"] == 3
    for kept in (outside / "a" / "session" / "config", outside / "b" / "config", outside / "c"):
        assert (kept / "keep.txt").is_file()
    assert not (root / _sid(4) / "session" / "config").exists()
    assert (root / "elsewhere" / "session" / "config" / "keep.txt").is_file()


def _swap_on_open(
    monkeypatch: pytest.MonkeyPatch, root: Path, at: tuple[str, ...], target: Path, moved: Path
) -> list[tuple[str, ...]]:
    """Swap the directory at ``at`` for a symlink, between the walk's opening and its acting.

    The symlink points to ``target``; the directory itself is moved to ``moved``.
    """
    swapped: list[tuple[str, ...]] = []

    def hook(parts: tuple[str, ...]) -> None:
        if parts == at and not swapped:
            swapped.append(parts)
            os.rename(root.joinpath(*parts), moved)
            root.joinpath(*parts).symlink_to(target)

    monkeypatch.setattr(C, "_after_open", hook)
    return swapped


@pytest.mark.parametrize("at", [("session",), ("session", "config")])
def test_a_directory_swapped_for_a_symlink_after_it_is_opened_leads_nowhere_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, at: tuple[str, ...]
) -> None:
    outside = _kept(tmp_path / "outside")
    _kept(outside / "config")
    root = tmp_path / "review-scratch" / "rpb-3"
    sid = _sid(1)
    _kept(root / sid / "session" / "config")
    target = outside if at == ("session",) else outside / "config"
    swapped = _swap_on_open(monkeypatch, root, (sid, *at), target, tmp_path / "moved")
    checks.remove_credentials([root])
    assert swapped
    assert (outside / "keep.txt").is_file() and (outside / "config" / "keep.txt").is_file()


def test_a_read_after_its_directory_is_swapped_for_a_symlink_reads_nothing_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, sid = tmp_path / "rpb-3", _sid(1)
    (root / sid / "session").mkdir(parents=True)
    (root / sid / "session" / "stdout.jsonl").write_text("ours\n")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "stdout.jsonl").write_text("outside\n")
    swapped = _swap_on_open(
        monkeypatch, root, (sid, "session"), tmp_path / "outside", tmp_path / "moved"
    )
    data = C.read_inside(root, root / sid / "session" / "stdout.jsonl")
    assert swapped and data != b"outside\n"
    # afterwards the symlink stands in the root: it is refused, never followed
    monkeypatch.setattr(C, "_after_open", lambda parts: None)
    assert C.read_inside(root, root / sid / "session" / "stdout.jsonl") is None


def test_the_usage_limit_search_reads_nothing_through_a_directory_swapped_mid_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "rpb-3"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "x.jsonl").write_text("{}\n")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "x.jsonl").write_text('{"error": "usage_limit_reached"}\n')
    swapped = _swap_on_open(monkeypatch, root, ("sub",), tmp_path / "outside", tmp_path / "moved")
    # the file it listed now lies behind a symlink: it is not read there, and the search
    # cannot rule a limit out, so it fails closed
    with pytest.raises(C.FailClosed, match="could not be read"):
        checks.usage_limit_files([root])
    assert swapped


def test_a_run_log_or_launch_record_that_is_a_symlink_is_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, runs, launch = _records(tmp_path, monkeypatch)
    for slot in SLOTS_I_F.values():
        _arm(home, runs, slot)
    # one arm's log is a symlink to a complete log elsewhere: it is not that arm's, and not read
    run = C.places(home, SLOTS_I_F["F"], runs)["run"]
    _log(tmp_path / "elsewhere.jsonl", "r")
    (run / "events.jsonl").unlink()
    (run / "events.jsonl").symlink_to(tmp_path / "elsewhere.jsonl")
    assert C.read_log(run / "events.jsonl") == ([], 0)
    (tmp_path / "exits.json").write_text(json.dumps({"3": 0, "1": 0}))
    (launch / "exits.json").symlink_to(tmp_path / "exits.json")
    monkeypatch.setattr(checks, "regate_count", lambda *_: 0)
    found = checks.after(1, launch, C.REPO)
    assert "a crashed or killed process" in found["void_causes"]
    assert found["per_slot"]["slot 1"]["arm_exit"] is None


# ---- the credential cleanup fails closed; every walk and read is bounded ----


def test_a_login_file_that_cannot_be_removed_is_reported_and_stops_the_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, runs, launch = _records(tmp_path, monkeypatch)
    root = C.places(home, SLOTS_I_F["F"], runs)["scratch"]
    config = root / _sid(1) / "session" / "config"
    config.mkdir(parents=True)
    (config / ".credentials.json").write_text("{}\n")
    config.chmod(0o500)  # the file cannot be unlinked
    try:
        found = checks.remove_credentials([root])
        assert found["login_files_left"] == 1 and found["configs_removed"] == 0
        with pytest.raises(checks.Refused, match="1 login file"):
            checks.credentials(1, launch)
    finally:
        config.chmod(0o700)
    checks.remove_credentials([root])
    assert checks.credentials(1, launch)["login_files_left"] == 0


def test_the_round_s_credential_check_counts_every_login_file_of_its_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, runs, launch = _records(tmp_path, monkeypatch)
    root = C.places(home, SLOTS_I_F["I"], runs)["scratch"]
    (root / _sid(1) / "session" / "config").mkdir(parents=True)
    (root / _sid(1) / "session" / "config" / "settings.json").write_text("{}\n")
    assert checks.credentials(1, launch)["login_files_left"] == 0  # no login file: clean
    (root / _sid(1) / "session" / "state").mkdir()
    (root / _sid(1) / "session" / "state" / "key-helper.sh").write_text("x\n")
    (root / _sid(2) / "session").mkdir(parents=True)
    (root / _sid(2) / "session" / "config").symlink_to(tmp_path)
    with pytest.raises(checks.Refused, match="2 login file"):
        checks.credentials(1, launch)


def test_review_roots_that_cannot_be_opened_fail_the_login_check_closed(tmp_path: Path) -> None:
    scratch = tmp_path / C.SCRATCH_NAME
    (scratch / "rpb-1").mkdir(parents=True)
    for locked in (scratch / "rpb-1", scratch):
        locked.chmod(0)
        try:
            with pytest.raises(C.FailClosed, match="could not be opened"):
                checks.run_login_files(tmp_path)
        finally:
            locked.chmod(0o700)
    assert checks.run_login_files(tmp_path) == {"roots": 1, "left": 0, "unconfirmed": 0}
    assert checks.run_login_files(tmp_path / "nowhere") == {"roots": 0, "left": 0, "unconfirmed": 0}


def test_the_second_arm_does_not_start_without_the_watcher_s_last_line(tmp_path: Path) -> None:
    assert checks.second_arm(tmp_path, since=0.0, now=10.0) is None


def test_a_records_file_that_is_a_symlink_or_a_fifo_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "real.jsonl").write_text("{}\n")
    (tmp_path / "link.jsonl").symlink_to(tmp_path / "real.jsonl")
    with pytest.raises(C.FailClosed, match="not a regular file"):
        C.read_jsonl(tmp_path / "link.jsonl")
    assert C.read_jsonl(tmp_path / "real.jsonl") == [{}]


def test_an_unreadable_directory_under_a_root_fails_the_search_closed(tmp_path: Path) -> None:
    root = tmp_path / "rpb-3"
    (root / "locked").mkdir(parents=True)
    (root / "locked").chmod(0)
    try:
        with pytest.raises(C.FailClosed, match="could not be opened"):
            checks.usage_limit_files([root])
    finally:
        (root / "locked").chmod(0o700)


def _no_block(call: Any, fifo: Path) -> Any:
    """Run ``call`` in a thread; if it blocks on the FIFO, release it, and fail."""
    import threading

    out: list[Any] = []
    t = threading.Thread(target=lambda: out.append(call()), daemon=True)
    t.start()
    t.join(timeout=10)
    if t.is_alive():
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        t.join(timeout=10)
        pytest.fail("a FIFO under a root was opened for reading and blocked")
    return out[0]


def test_a_fifo_under_a_root_is_never_opened_for_reading(tmp_path: Path) -> None:
    root = tmp_path / "rpb-3"
    (root / _sid(1) / "session").mkdir(parents=True)
    fifo = root / _sid(1) / "session" / "stdout.jsonl"
    os.mkfifo(fifo)
    assert _no_block(lambda: C.read_inside(root, fifo), fifo) is None
    assert _no_block(lambda: C.read_own(fifo), fifo) is None
    assert _no_block(lambda: checks.usage_limit_files([root]), fifo) == (0, 0)


def test_a_read_past_its_size_bound_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "rpb-3"
    root.mkdir()
    (root / "x.jsonl").write_text("0123456789A")
    monkeypatch.setattr(C, "MAX_FILE_BYTES", 10)
    with pytest.raises(C.FailClosed, match="bound"):
        C.read_inside(root, root / "x.jsonl")
    with pytest.raises(C.FailClosed, match="bound"):
        C.read_own(root / "x.jsonl")
    with pytest.raises(C.FailClosed, match="bound"):
        checks.usage_limit_files([root])


def test_a_walk_past_its_depth_or_entry_bound_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "rpb-3"
    (root / "a" / "b" / "c" / "d" / "e").mkdir(parents=True)
    monkeypatch.setattr(C, "MAX_DEPTH", 3)
    with pytest.raises(C.FailClosed, match="depth"):
        list(C.walk_inside(root))
    monkeypatch.setattr(C, "MAX_DEPTH", 32)
    wide = tmp_path / "rpb-4"
    wide.mkdir()
    for n in range(10):
        (wide / f"f{n}.json").write_text("{}")
    monkeypatch.setattr(C, "MAX_ENTRIES", 5)
    with pytest.raises(C.FailClosed, match="entries"):
        list(C.walk_inside(wide))
    with pytest.raises(C.FailClosed, match="entries"):
        C.list_inside(wide)


@pytest.mark.parametrize("name", ["home", "rpb-x", "rpb-1000", "review-scratch"])
def test_the_credential_cleanup_acts_on_a_review_root_of_the_run_s_form_alone(
    tmp_path: Path, name: str
) -> None:
    _kept(tmp_path / name / _sid(1) / "session" / "config")
    with pytest.raises(checks.Refused, match="review root"):
        checks.remove_credentials([tmp_path / name])
    assert (tmp_path / name / _sid(1) / "session" / "config" / "keep.txt").is_file()


def _record(root: Path, sid: str, record: dict[str, Any]) -> Path:
    sdir = root / sid / "session"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "process.json").write_text(json.dumps(record))
    return sdir


def test_a_process_record_proves_only_a_session_this_run_started(tmp_path: Path) -> None:
    root = tmp_path / "rpb-3"
    me, started = os.getpid(), _started(os.getpid())
    # the test's own process, its true start time, but no such session id on its command line
    assert checks.proven_session(root, _record(root, _sid(1), {
        "pid": me, "started": started, "session_id": _sid(1)})) is None  # fmt: skip
    for n, forged in enumerate(
        [
            {"pid": 1, "started": started, "session_id": _sid(2)},
            {"pid": "1; rm -rf /", "started": started, "session_id": _sid(3)},
            {"pid": me, "started": started, "session_id": _sid(99)},  # not its directory's id
            {"pid": me, "started": started},
            [me],
        ],
        start=2,
    ):
        sdir = root / _sid(n) / "session"
        sdir.mkdir(parents=True)
        (sdir / "process.json").write_text(json.dumps(forged))
        assert checks.proven_session(root, sdir) is None, forged
    # a stand-in that carries its id but does not lead its own group is not proven
    sid = _sid(10)
    loose = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3)", "--session-id", sid]
    )
    time.sleep(0.3)
    sdir = _record(root, sid, {"pid": loose.pid, "started": _started(loose.pid), "session_id": sid})
    assert checks.proven_session(root, sdir) is None
    # one that leads its group, with its start time and id: proven (and never signalled here)
    sid = _sid(11)
    led = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3)", "--session-id", sid],
        start_new_session=True,
    )
    time.sleep(0.3)
    sdir = _record(root, sid, {"pid": led.pid, "started": _started(led.pid), "session_id": sid})
    assert checks.proven_session(root, sdir) == (led.pid, _started(led.pid), sid)
    # the same record read through a symlink is not believed
    sid = _sid(12)
    (root / sid / "session").mkdir(parents=True)
    (root / sid / "session" / "process.json").symlink_to(sdir / "process.json")
    assert checks.proven_session(root, root / sid / "session") is None
    loose.wait(timeout=30)
    led.wait(timeout=30)


def test_the_usage_limit_search_never_follows_a_symlink_out_of_a_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    text = '{"error": "usage_limit_reached", "api_error_status": 429}\n'
    (outside / "x.jsonl").write_text(text)
    root = tmp_path / "rpb-3"
    root.mkdir()
    (root / "linked").symlink_to(outside)
    (root / "linked.jsonl").symlink_to(outside / "x.jsonl")
    assert checks.usage_limit_files([root]) == (0, 0)
    (root / "own.jsonl").write_text(text)
    assert checks.usage_limit_files([root]) == (1, 1)


@pytest.mark.parametrize("slot", [0, -1, 1000, "3", "1/../../x", True, 2.0])
def test_a_slot_is_a_whole_number_from_1_to_999(slot: Any) -> None:
    with pytest.raises(ValueError, match="slot"):
        C.places(Path("/h"), slot)


@pytest.mark.parametrize(
    "value", ["relative/runs", "/h/runs/../../etc", "/h/runs/x\n", "/h/run s", "/h/runs/"]
)
def test_the_records_directory_is_an_absolute_plain_path(value: str) -> None:
    with pytest.raises(ValueError, match="records"):
        C.records_dir(value, Path("/h"))


def test_the_records_directory_is_the_run_s_unless_a_trial_names_one() -> None:
    assert C.records_dir("", Path("/h")) == Path("/h/runs/rpg01b")
    assert C.records_dir(None, Path("/h")) == Path("/h/runs/rpg01b")
    assert C.records_dir("/h/rpb-trial/dry2", Path("/h")) == Path("/h/rpb-trial/dry2")


def test_the_watcher_ends_when_every_arm_has_ended_and_stops_nothing(tmp_path: Path) -> None:
    a = _group(1)
    log = tmp_path / "watcher.log"
    (tmp_path / "r").mkdir()
    watcher = _watch(log, a.pid, tmp_path / "r", tmp_path / "r")
    a.wait(timeout=10)  # reaped, as launch.sh's wait reaps an arm that ends
    assert watcher.wait(timeout=30) == 0
    text = log.read_text()
    assert "ABORT" not in text and "LIMIT" not in text
    assert "usage_limit_reached files 0" in text


def test_the_watcher_never_follows_a_symlink_out_of_a_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.jsonl").write_text('{"error":"usage_limit_reached"}\n')
    run, root = tmp_path / "run-1", tmp_path / "rpb-1"
    run.mkdir()
    root.mkdir()
    (root / "linked").symlink_to(outside)
    (root / "linked.jsonl").symlink_to(outside / "x.jsonl")
    a = _group(2)
    log = tmp_path / "watcher.log"
    watcher = _watch(log, a.pid, run, root)
    a.wait(timeout=10)
    assert watcher.wait(timeout=30) == 0
    text = log.read_text()
    assert "ABORT" not in text and "LIMIT" not in text and "files 0" in text


def test_the_watcher_looks_once_more_after_every_arm_has_ended(tmp_path: Path) -> None:
    a = _group(0)
    a.wait(timeout=10)
    (tmp_path / "r").mkdir()
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "stdout.jsonl").write_text('{"error":"usage_limit_reached"}\n')
    log = tmp_path / "watcher.log"
    watcher = _watch(log, a.pid, tmp_path / "r", tmp_path / "s")
    assert watcher.wait(timeout=30) == 0
    text = log.read_text()
    assert "LIMIT" in text and "usage_limit_reached files 1" in text


# ---- launch.sh and the published diffs ----


def test_a_check_only_trial_names_its_own_records_and_writes_nothing_of_the_run_s(
    tmp_path: Path,
) -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("RPB_RUNS", "RPB_MASTER_REF")}
    env["HOME"] = str(tmp_path)
    for runs in (None, str(tmp_path / C.RUNS_NAME), str(tmp_path / C.RUNS_NAME / "trial")):
        if runs is not None:
            env["RPB_RUNS"] = runs
        done = subprocess.run(
            [str(HERE / "launch.sh"), "--round", "1", "--checks-only"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert done.returncode == 1 and "RPB_RUNS" in done.stderr, done.stderr
        assert not (tmp_path / "runs").exists()


def test_launch_sh_gives_the_arms_no_trial_variable() -> None:
    text = (HERE / "launch.sh").read_text()
    assert "export RPB_RUNS" not in text


def test_launch_sh_parses_and_refuses_a_trial_s_overrides_in_a_run(tmp_path: Path) -> None:
    assert subprocess.run(["bash", "-n", str(HERE / "launch.sh")], check=False).returncode == 0
    usage = subprocess.run([str(HERE / "launch.sh")], capture_output=True, text=True, check=False)
    assert usage.returncode == 2
    refused = subprocess.run(
        [str(HERE / "launch.sh"), "--round", "1"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "RPB_MASTER_REF": "elsewhere", "HOME": str(tmp_path)},
    )
    assert refused.returncode == 1 and "--checks-only alone" in refused.stderr


def _applies(old: str, diff: Path, new: Path, tmp: Path) -> bool:
    """Whether the published diff, applied to ``old``, gives ``new`` byte for byte."""
    (tmp / "old").write_text(old)
    done = subprocess.run(
        ["patch", "-s", "-o", str(tmp / "patched"), str(tmp / "old"), str(diff)],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode == 0 and (tmp / "patched").read_bytes() == new.read_bytes()


def test_r3_scan_f_is_r_pg_01_s_scan_with_arm_f_s_corpus_path_alone(tmp_path: Path) -> None:
    old = subprocess.run(
        ["git", "-C", str(HERE), "show", f"{C.R_PG_01_COMMIT}:experiments/R-PG-01/r3_scan.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    new = (HERE / "r3_scan_f.py").read_text()
    changed = [(a, b) for a, b in zip(old.splitlines(), new.splitlines(), strict=True) if a != b]
    assert changed == [
        (
            'corpus_dir = checkout / "corpora" / "injected-errors" / "v1"',
            'corpus_dir = checkout / "corpora" / "injected-errors" / "v1-fullsheet"',
        )
    ]
    published = HERE / "diffs" / "r3_scan_f.py.diff"
    assert published.read_text().splitlines()[0].startswith("--- experiments/R-PG-01/r3_scan.py")
    assert _applies(old, published, HERE / "r3_scan_f.py", tmp_path)


def test_launch_sh_s_published_diff_is_against_r_pg_01_s_frozen_launch_sh(tmp_path: Path) -> None:
    old = subprocess.run(
        ["git", "-C", str(HERE), "show", f"{C.R_PG_01_COMMIT}:experiments/R-PG-01/launch.sh"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    published = HERE / "diffs" / "launch.sh.diff"
    assert published.read_text().splitlines()[0].startswith("--- experiments/R-PG-01/launch.sh")
    assert _applies(old, published, HERE / "launch.sh", tmp_path)


def test_the_watcher_s_published_diff_is_its_own() -> None:
    published = (HERE / "diffs" / "abort_on_limit.sh.diff").read_text()
    assert published.splitlines()[1] == "+++ experiments/R-PG-01b/abort_on_limit.sh"
    added = [ln[1:] for ln in published.splitlines()[3:] if ln.startswith(("+", " "))]
    assert added == (HERE / "abort_on_limit.sh").read_text().splitlines()
