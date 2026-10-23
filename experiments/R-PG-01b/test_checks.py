"""Tests of the launch's own parts on invented fixtures: checks.py, launch.sh, the watcher, the
ledger line, r3_scan_f.py's derivation and the filled facts (common.py).

Run explicitly, in the run checkout: ``uv run --frozen pytest -q experiments/R-PG-01b``.
"""

from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import time
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


def _repo(tmp_path: Path) -> Path:
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
    return repo, git  # type: ignore[return-value]


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body)


def test_l2_admits_only_the_backport_s_paths_and_master_s_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, git = _repo(tmp_path)  # type: ignore[misc]
    _write(repo, {"src/physgate/evaluation/inject/corpus.py": "old\n", "README.md": "r\n"})
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    monkeypatch.setattr(C, "R_PG_01_COMMIT", base)
    # master: the scripts, then the sheet
    git("checkout", "-q", "-b", "master")
    _write(
        repo, {"experiments/R-PG-01b/CRITERIA.md": "c\n", "experiments/R-PG-01b/launch.sh": "l\n"}
    )
    git("add", "-A")
    git("commit", "-q", "-m", "scripts")
    _write(
        repo, {f"{C.ARM_F_CORPUS}/sources.json": "s\n", "experiments/R-PG-01b/sheet/t.md": "t\n"}
    )
    git("add", "-A")
    git("commit", "-q", "-m", "sheet")
    # the run branch: base plus the backport and master's files, no sheet copy
    git("checkout", "-q", "-b", "run", base)
    _write(repo, {"src/physgate/evaluation/inject/corpus.py": "new\n"})
    git(
        "checkout",
        "master",
        "--",
        "experiments/R-PG-01b/CRITERIA.md",
        "experiments/R-PG-01b/launch.sh",
        f"{C.ARM_F_CORPUS}/sources.json",
    )
    git("add", "-A")
    git("commit", "-q", "-m", "run")
    found = checks.l2(repo, "master")
    assert found["paths outside §2.4"] == [] and found["paths_changed"] == 4
    # a change outside §2.4 is refused
    _write(repo, {"README.md": "changed\n"})
    git("commit", "-qam", "outside")
    with pytest.raises(checks.Refused, match="outside"):
        checks.l2(repo, "master")
    git("reset", "-q", "--hard", "HEAD~1")
    # a script blob that is not master's is refused
    _write(repo, {"experiments/R-PG-01b/launch.sh": "other\n"})
    git("commit", "-qam", "drift")
    with pytest.raises(checks.Refused, match="experiments/R-PG-01b tree"):
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


def _group(seconds: int) -> subprocess.Popen[bytes]:
    return subprocess.Popen(["sleep", str(seconds)], start_new_session=True)


def test_the_watcher_stops_every_arm_at_the_first_usage_limit(tmp_path: Path) -> None:
    a, b = _group(60), _group(60)
    dirs = [tmp_path / n for n in ("ra", "sa", "rb", "sb")]
    for d in dirs:
        d.mkdir()
    log = tmp_path / "watcher.log"
    watcher = subprocess.Popen(
        [
            str(HERE / "abort_on_limit.sh"),
            str(log),
            str(a.pid),
            str(dirs[0]),
            str(dirs[1]),
            str(b.pid),
            str(dirs[2]),
            str(dirs[3]),
        ],
        env={**os.environ, "RPB_WATCH_SECONDS": "1"},
    )
    time.sleep(1.5)
    assert a.poll() is None and b.poll() is None
    (dirs[3] / "stdout.jsonl").write_text('{"type":"result","error":"usage_limit_reached"}\n')
    assert watcher.wait(timeout=20) == 0
    assert a.wait(timeout=10) == -signal.SIGTERM and b.wait(timeout=10) == -signal.SIGTERM
    text = log.read_text()
    assert "ABORT" in text and "usage_limit_reached files 1" in text


def test_the_watcher_ends_when_every_arm_has_ended_and_stops_nothing(tmp_path: Path) -> None:
    a = _group(1)
    log = tmp_path / "watcher.log"
    (tmp_path / "r").mkdir()
    watcher = subprocess.Popen(
        [
            str(HERE / "abort_on_limit.sh"),
            str(log),
            str(a.pid),
            str(tmp_path / "r"),
            str(tmp_path / "r"),
        ],
        env={**os.environ, "RPB_WATCH_SECONDS": "1"},
    )
    a.wait(timeout=10)  # reaped, as launch.sh's wait reaps an arm that ends
    assert watcher.wait(timeout=30) == 0 and "ABORT" not in log.read_text()


# ---- launch.sh and the published diffs ----


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
