"""Tests of reality.py (§7): lines, packets and seeds, sessions, controls, confirmation, classes.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

Every session is a scripted stand-in executable (never the pinned binary), and every set is the
fixture's. The prompt, the schema and the four standards files are read at their pinned digests.
"""

from __future__ import annotations

import json
import os
import random
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import fixture as fx  # noqa: E402
import reality as rl  # noqa: E402
import tally3 as t3  # noqa: E402

AC, DS = fx.SECTION1, fx.SECTION2


def test_the_prompt_and_schema_are_r_law_01_s_byte_for_byte() -> None:
    prompt, schema = rl.prompt_and_schema()
    assert common.sha256_file(prompt) == common.REALITY_PROMPT_SHA256
    assert common.sha256_file(schema) == common.REALITY_SCHEMA_SHA256


@pytest.mark.parametrize("role", common.ROLES)
def test_each_domain_s_standards_are_the_pinned_tree_s_blob(role: str) -> None:
    assert common.sha256_bytes(rl.standards(common.REPO, role)) == common.STANDARDS_SHA256[role]


def test_the_probe_is_published_byte_for_byte_and_its_counts_are_one() -> None:
    assert common.sha256_file(HERE / "ff_key_probe.py") == common.FF_PROBE_SHA256
    out = json.loads((HERE / "ff_key_probe_output.json").read_text())
    assert [k["lines_matched"] for k in out["keys"]] == [1, 1, 1, 1, 1]
    assert out["law_extract_sha256"] == common.LAW_EXTRACT_SHA256
    assert out["law_inputs_digests_sha256"] == common.LAW_INPUTS_SHA256
    keys = [
        (k["case"], k["key"]["item"], k["key"]["side"], k["key"]["rubric_item_id"])
        for k in out["keys"]
    ]
    assert keys == [
        (c if c != "4" else ("4a" if lab == "repeat-K" else "4b"), i, s, r)
        for c, lab, i, s, r in rl.FF_KEYS
    ]


def test_the_false_finding_control_is_not_checked_on_records_not_at_their_digests(
    tmp_path: Path,
) -> None:
    for label in ("round-1", "repeat-K"):
        (tmp_path / label).mkdir()
    with pytest.raises(rl.RefusedError, match="cannot be read at its digest"):
        rl.ff_count({"round-1": tmp_path / "round-1", "repeat-K": tmp_path / "repeat-K"})


def test_ff_count_says_not_checked_apart_from_a_failed_precondition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for label in ("round-1", "repeat-K"):
        (tmp_path / label).mkdir()
    argv = ["ff-count", f"--practice=round-1={tmp_path / 'round-1'}"]
    argv += [f"--practice=repeat-K={tmp_path / 'repeat-K'}"]
    assert rl.main(argv) == 1 and "not_checked" in capsys.readouterr().out
    monkeypatch.setattr(common, "LAW_INPUTS_SHA256", "0" * 64)
    assert rl.main(argv) == 2 and "refused" in capsys.readouterr().out


# ---- the lines, from real runs ---------------------------------------------------------------


@pytest.fixture(scope="module")
def block(tmp_path_factory: pytest.TempPathFactory) -> t3.Block:
    base = tmp_path_factory.mktemp("reality")
    sets = fx.write_sets(base / "sets", ["fresh-v2-x1"])
    by_arm = {
        "A2": {
            "c1": (
                fx.fail(
                    ("D25", DS, "the D26 gain of control.balance_loop loop_gain"), ("A7", AC, "c")
                ),
                ("pass",),
            ),
            "e1": (("blocked",), ("pass",)),
        },
        "A1": {
            "c1": (fx.fail(("D26", DS, "loop_gain of balance_loop")), fx.fail(("D99", DS, "x")))
        },
        "B": {"c1": (fx.fail(("A7", AC, "the gain")), ("pass",))},
    }
    runs = {
        arm: fx.real_run(
            sets / "fresh-v2-x1", base / arm, common.BLOCK_SEED["x1"], arm, by_arm[arm]
        )
        for arm in common.ARMS
    }
    return t3.read_block("x1", fx.attempt("x1", runs), sets, {})


def test_lines_are_numbered_in_section_7_s_order_and_masked(block: t3.Block) -> None:
    keyed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    cells = t3.Cells.at(common.REPO)
    for arm in common.ARMS:
        scored = t3.score(block, arm, cells)
        for p in scored:
            p["common_cell"] = list(
                t3.common_cell(common.ARM_KIND[arm], p["role"], p["class"], cells)
            )
        k, _ = rl.lines_of(block, arm, scored, common.REPO)
        keyed += k
    keyed.sort(key=lambda x: x[0])
    order = [(r["item"], r["side"], r["arm"], r["position"]) for _, r in keyed]
    assert order == [
        ("c1", "injected", "A2", 0),
        ("c1", "injected", "A2", 1),
        ("c1", "injected", "A1", 0),
        ("c1", "injected", "B", 0),
        ("c1", "twin", "A1", 0),
    ]
    first = keyed[0][1]
    assert "[rule]" in first["text"] and "D26" not in first["text"]
    assert ["control.balance_loop", "loop_gain"] in first["locus"]


def test_a_blocked_review_gives_no_line_and_a_pass_none(block: t3.Block) -> None:
    scored = t3.score(block, "A2", t3.Cells.at(common.REPO))
    for p in scored:
        p["common_cell"] = []
    keyed, reviews = rl.lines_of(block, "A2", scored, common.REPO)
    assert not any(r["item"] == "e1" for _, r in keyed)
    assert {(r["item"], r["side"], r["outcome"]) for r in reviews if r["item"] == "e1"} == {
        ("e1", "injected", "blocked"),
        ("e1", "twin", "pass"),
    }


# ---- the packets ---------------------------------------------------------------------------


def make_work(
    tmp: Path,
    lines: list[dict[str, Any]],
    reviews: list[dict[str, Any]] | None = None,
    design: dict[str, Any] | None = None,
) -> Path:
    work = tmp / "work"
    work.mkdir()
    rl.write_jsonl(work / "lines.jsonl", lines)
    rl.write_jsonl(work / "reviews.jsonl", reviews or [])
    (work / "design.json").write_text(json.dumps(design or {}))
    return work


def line(
    n: int,
    corpus: str,
    item: str,
    side: str,
    arm: str,
    pos: int = 0,
    locus: list[list[str]] | None = None,
    rubric_item: str = "D25",
) -> dict[str, Any]:
    return {
        "line_id": f"L{n:05d}",
        "corpus": corpus,
        "item": item,
        "side": side,
        "arm": arm,
        "role": "control",
        "class": "unit",
        "section": DS,
        "rubric_item": rubric_item,
        "position": pos,
        "text": f"finding {n}",
        "locus": locus or [],
    }


@pytest.fixture
def sets(tmp_path: Path) -> Path:
    return fx.write_sets(tmp_path / "sets", ["fresh-v2-x1", "fresh-v2-s", "fresh-v1c-a01-a20"])


def test_a_version_s_lines_are_shuffled_by_seed_37_and_cut_at_twelve(
    tmp_path: Path, sets: Path
) -> None:
    lines = [line(n, "fresh-v2-x1", "c1", "injected", "A2", n) for n in range(1, 15)]
    lines += [line(n, "fresh-v2-x1", "c1", "twin", "B", n) for n in range(15, 17)]
    work = make_work(tmp_path, lines)
    rl.build_packets(work, sets, tmp_path / "p")
    key = json.loads((tmp_path / "p" / "key.json").read_text())
    rng = random.Random(37)
    ids = [f"L{n:05d}" for n in range(1, 15)]
    rng.shuffle(ids)
    twins = [f"L{n:05d}" for n in range(15, 17)]
    rng.shuffle(twins)

    def ordered(findings: dict[str, str]) -> list[str]:
        return [findings[f] for f in sorted(findings, key=lambda f: int(f[1:]))]

    assert [ordered(key[p]["findings"]) for p in sorted(key)] == [ids[:12], ids[12:], twins]
    assert (tmp_path / "p" / "injected.txt").read_text().split() == ["Q0001", "Q0002"]


def test_fresh_v2_s_packets_are_the_same_whether_or_not_blocks_p1_and_p2_ran(
    tmp_path: Path, sets: Path
) -> None:
    v2 = [line(n, "fresh-v2-x1", "c1", "injected", "A2", n) for n in range(1, 6)]
    p = [line(n, "fresh-v1c-a01-a20", "c1", "injected", "A2", n) for n in range(6, 9)]
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    rl.build_packets(make_work(tmp_path / "a", v2), sets, tmp_path / "a" / "p")
    rl.build_packets(make_work(tmp_path / "b", v2 + p), sets, tmp_path / "b" / "p")
    assert (tmp_path / "a" / "p" / "Q0001.md").read_bytes() == (
        tmp_path / "b" / "p" / "Q0001.md"
    ).read_bytes()
    key = json.loads((tmp_path / "b" / "p" / "key.json").read_text())
    assert key["Q0002"]["corpus"] == "fresh-v1c-a01-a20"


def test_a_packet_holds_the_table_verbatim_and_the_class_s_holds_its_role_s_standards(
    tmp_path: Path, sets: Path
) -> None:
    lines = [
        line(1, "fresh-v2-x1", "c1", "injected", "A2"),
        line(2, "fresh-v2-s", "c1", "twin", "A1"),
    ]
    rl.build_packets(make_work(tmp_path, lines), sets, tmp_path / "p")
    plain = (tmp_path / "p" / "Q0001.md").read_text()
    cls = (tmp_path / "p" / "Q0002.md").read_text()
    assert (
        fx.edited_table().decode() in plain
        and "standards" not in plain.lower().split("## the parts sheet")[0]
    )
    assert (
        rl.STANDARDS_HEADING.format(role="control") + rl.standards(common.REPO, "control").decode()
        in cls
    )
    assert cls.index("## The parts sheet") < cls.index("## The control domain's standards")
    for word in ("A2", "A1", "injected", "twin"):
        assert word not in plain.split("## Findings")[0]


def test_the_blindness_check_rebuilds_every_packet_and_finds_a_tampered_one(
    tmp_path: Path, sets: Path
) -> None:
    work = make_work(tmp_path, [line(1, "fresh-v2-x1", "c1", "injected", "A2")])
    rl.build_packets(work, sets, tmp_path / "p")
    assert rl.blind(work, sets, tmp_path / "p")["blind"]
    q = tmp_path / "p" / "Q0001.md"
    q.write_text(q.read_text() + "\nthe injected item\n")
    assert rl.blind(work, sets, tmp_path / "p")["not_their_template"] == 1


def test_a_corpus_whose_table_is_not_the_edited_one_is_refused(tmp_path: Path) -> None:
    d = fx.write_set(tmp_path / "c")
    (d / common.TABLE_NAME).write_text("another table\n")
    with pytest.raises(rl.RefusedError, match="edited"):
        rl.Corpus(d, "c")


# ---- the sessions ----------------------------------------------------------------------------

STANDIN = """#!{python}
import json, os, re, sys
packet = sys.stdin.read()
ids = re.findall(r"^### (F[0-9]+)$", packet, re.M)
mode = os.environ.get("STANDIN_MODE", "valid")
count = os.path.join(os.environ["STANDIN_DIR"], "calls")
with open(count, "a") as f:
    f.write("x")
if mode == "usage":
    print("API Error: usage_limit_reached")
    sys.exit(1)
if mode == "noresult":
    sys.exit(1)
found = [{{"id": i, "verdict": "true_flaw", "origin": "introduced", "reason": "r"}} for i in ids]
if mode == "partial":
    found = found[:1]
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False,
                  "usage": {{"input_tokens": 5}},
                  "structured_output": {{"findings": found}}}}))
"""


def standin(tmp: Path) -> Path:
    path = tmp / "standin"
    path.write_text(STANDIN.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def run_cli(
    tmp: Path, packets: Path, out: Path, mode: str, resume: bool = False
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "RP3_STANDIN": str(standin(tmp)),
        "STANDIN_MODE": mode,
        "STANDIN_DIR": str(tmp),
    }
    if resume:
        env["RP3_RESUME"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "reality.py"),
            "run",
            "--packets",
            str(packets),
            "--ids",
            str(packets / "injected.txt"),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=common.REPO,
    )


def test_a_session_per_packet_and_its_first_valid_forms(tmp_path: Path, sets: Path) -> None:
    lines = [line(n, "fresh-v2-x1", "c1", "injected", "A2", n) for n in range(1, 4)]
    rl.build_packets(make_work(tmp_path, lines), sets, tmp_path / "p")
    done = run_cli(tmp_path, tmp_path / "p", tmp_path / "s", "valid")
    assert done.returncode == 0, done.stdout
    got = rl.verdicts(tmp_path / "p", tmp_path / "s")
    assert {v["verdict"] for v in got.values()} == {"true_flaw"} and len(got) == 3
    assert (tmp_path / "calls").read_text() == "x"


def test_a_packet_missing_a_form_is_tried_again_at_most_three_times(
    tmp_path: Path, sets: Path
) -> None:
    lines = [line(n, "fresh-v2-x1", "c1", "injected", "A2", n) for n in range(1, 4)]
    rl.build_packets(make_work(tmp_path, lines), sets, tmp_path / "p")
    run_cli(tmp_path, tmp_path / "p", tmp_path / "s", "partial")
    assert (tmp_path / "calls").read_text() == "xxx"
    got = rl.verdicts(tmp_path / "p", tmp_path / "s")
    assert sum(v["adjudicated"] for v in got.values()) == 1
    assert {v["verdict"] for v in got.values() if not v["adjudicated"]} == {"undecidable"}
    assert rl.done(tmp_path / "p", tmp_path / "s")["open"] == 0


def test_a_usage_limit_stops_everything_and_the_call_runs_again_whole_on_resume(
    tmp_path: Path, sets: Path
) -> None:
    lines = [line(n, "fresh-v2-x1", "c1", "injected", "A2", n) for n in range(1, 3)]
    rl.build_packets(make_work(tmp_path, lines), sets, tmp_path / "p")
    first = run_cli(tmp_path, tmp_path / "p", tmp_path / "s", "usage")
    assert first.returncode == 4 and (tmp_path / "s" / "STOPPED").is_file()
    assert not rl.attempts(tmp_path / "s", "Q0001")  # a failed call is not an attempt
    again = run_cli(tmp_path, tmp_path / "p", tmp_path / "s", "valid")
    assert again.returncode == 1 and "RP3_RESUME" in again.stdout
    resumed = run_cli(tmp_path, tmp_path / "p", tmp_path / "s", "valid", resume=True)
    assert resumed.returncode == 0 and len(rl.attempts(tmp_path / "s", "Q0001")) == 1


def test_a_call_with_no_result_is_not_an_attempt(tmp_path: Path, sets: Path) -> None:
    rl.build_packets(
        make_work(tmp_path, [line(1, "fresh-v2-x1", "c1", "injected", "A2")]), sets, tmp_path / "p"
    )
    assert run_cli(tmp_path, tmp_path / "p", tmp_path / "s", "noresult").returncode == 4
    assert not rl.attempts(tmp_path / "s", "Q0001")


# ---- the controls and the confirmation pass ------------------------------------------------------


def write_attempt(sessions: Path, pid: str, forms: dict[str, tuple[str, str]]) -> None:
    sessions.mkdir(parents=True, exist_ok=True)
    found = [{"id": f, "verdict": v, "origin": o, "reason": "r"} for f, (v, o) in forms.items()]
    (sessions / f"{pid}.attempt1.json").write_text(
        json.dumps({"type": "result", "structured_output": {"findings": found}})
    )


def judge(packets: Path, sessions: Path, by_line: dict[str, tuple[str, str]]) -> None:
    key = json.loads((packets / "key.json").read_text())
    for pid, k in key.items():
        write_attempt(
            sessions,
            pid,
            {f: by_line.get(lid, ("not_a_flaw", "n/a")) for f, lid in k["findings"].items()},
        )


def test_a_line_is_eligible_only_where_every_pair_of_its_locus_is_changed() -> None:
    changed = {("control.balance_loop", "loop_gain"), ("control.balance_loop", "tick")}
    true = {"verdict": "true_flaw", "origin": "introduced"}
    both = line(1, "fresh-v2-x1", "c1", "injected", "A2", 0, [list(p) for p in sorted(changed)])
    part = line(2, "fresh-v2-x1", "c1", "injected", "A2", 0, [["control.balance_loop", "tick"]])
    outside = [["control.balance_loop", "tick"], ["x.y", "z"]]
    wider = line(3, "fresh-v2-x1", "c1", "injected", "A2", 0, outside)
    assert rl.eligible(both, true, changed) and rl.eligible(part, true, changed)
    assert not rl.eligible(wider, true, changed)
    assert not rl.eligible(both, {"verdict": "true_flaw", "origin": "base"}, changed)
    assert not rl.eligible(both, {"verdict": "not_a_flaw", "origin": "n/a"}, changed)
    assert not rl.eligible({**both, "side": "twin"}, true, changed)
    assert not rl.eligible(both, None, changed)


def test_the_rejection_control_draws_one_eligible_line_per_injected_version_by_seed_43(
    tmp_path: Path, sets: Path
) -> None:
    changed = [["control.balance_loop", "loop_gain"]]
    lines = [
        line(1, "fresh-v2-x1", "c1", "injected", "A2", 0, changed),
        line(2, "fresh-v2-x1", "c1", "injected", "A1", 0, changed),
        line(3, "fresh-v2-x1", "c1", "injected", "B", 0, [["x.y", "z"]]),  # a locus not all changed
        line(4, "fresh-v2-x1", "e1", "injected", "A2", 0, []),  # an empty locus is not eligible
        line(5, "fresh-v1c-a01-a20", "c1", "injected", "A2", 0, changed),
    ]
    design = {
        c: {
            "c1": {"role": "control", "changed": changed},
            "e1": {"role": "electrical", "changed": []},
        }
        for c in ("fresh-v2-x1", "fresh-v1c-a01-a20")
    }
    work = make_work(tmp_path, lines, design=design)
    rl.build_packets(work, sets, tmp_path / "p")
    judge(
        tmp_path / "p",
        tmp_path / "s",
        {f"L{n:05d}": ("true_flaw", "introduced") for n in range(1, 6)},
    )
    rl.build_controls(work, sets, tmp_path / "p", tmp_path / "s", tmp_path / "c")
    key = json.loads((tmp_path / "c" / "key.json").read_text())
    rng = random.Random(43)
    want = rng.choice(["L00001", "L00002"])
    assert [k["findings"]["F1"] for _, k in sorted(key.items())] == [want, "L00005"]
    assert [k["group"] for _, k in sorted(key.items())] == ["fresh-v2", "fresh-v1c"]
    assert all(k["side"] == "twin" for k in key.values())
    assert int(min(key)[1:]) > int(max(json.loads((tmp_path / "p" / "key.json").read_text()))[1:])


def test_the_confirmation_pass_takes_flaw_making_lines_on_fresh_v2_twins_and_the_class_s_twice(
    tmp_path: Path, sets: Path
) -> None:
    lines = [
        line(1, "fresh-v2-x1", "c1", "twin", "A2"),
        line(2, "fresh-v2-x1", "c1", "twin", "B"),
        line(3, "fresh-v2-s", "c1", "twin", "A2"),
        line(4, "fresh-v1c-a01-a20", "c1", "twin", "A2"),
        line(5, "fresh-v2-x1", "c1", "injected", "A2"),
    ]
    work = make_work(tmp_path, lines)
    rl.build_packets(work, sets, tmp_path / "p")
    judge(
        tmp_path / "p",
        tmp_path / "s",
        {
            "L00001": ("true_flaw", "both"),
            "L00002": ("true_flaw", "already_in_base"),
            "L00003": ("true_flaw", "introduced"),
            "L00004": ("true_flaw", "introduced"),
            "L00005": ("true_flaw", "introduced"),
        },
    )
    rl.build_confirm(work, sets, tmp_path / "p", tmp_path / "s", [tmp_path / "p"], tmp_path / "c")
    key = json.loads((tmp_path / "c" / "key.json").read_text())
    assert sorted(k["findings"]["F1"] for k in key.values()) == ["L00001", "L00003"]
    judge(
        tmp_path / "c",
        tmp_path / "cs",
        {"L00001": ("true_flaw", "introduced"), "L00003": ("true_flaw", "both")},
    )
    rl.build_third(tmp_path / "c", tmp_path / "cs", tmp_path / "t")
    third = json.loads((tmp_path / "t" / "key.json").read_text())
    assert [k["findings"]["F1"] for k in third.values()] == ["L00003"]
    pid = next(iter(third))
    assert (tmp_path / "t" / f"{pid}.md").read_bytes() == (
        tmp_path / "c" / f"{pid}.md"
    ).read_bytes()


# ---- the classes, the controls' bars, the statuses ----------------------------------------------


def review(
    corpus: str,
    item: str,
    side: str,
    arm: str,
    outcome: str,
    credited: bool | None = None,
    cell: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "corpus": corpus,
        "item": item,
        "side": side,
        "arm": arm,
        "role": "control",
        "class": "unit",
        "outcome": outcome,
        "cause": None,
        "credited": credited,
        "common_cell": cell or ["D25", "A7"],
    }


CHANGED = {(n, q) for n, q in [("control.balance_loop", "loop_gain")]}


@pytest.mark.parametrize(
    ("side", "outcome", "credited", "verdicts", "want"),
    [
        ("injected", "blocked", False, [], "B"),
        ("injected", "fail", True, [("true_flaw", "introduced", [])], "P"),
        (
            "injected",
            "fail",
            False,
            [("true_flaw", "introduced", [["control.balance_loop", "loop_gain"]])],
            "P′",
        ),
        ("injected", "fail", False, [("true_flaw", "both", [["a.b", "c"]])], "O-introduced"),
        ("injected", "fail", False, [("true_flaw", "already_in_base", [["a.b", "c"]])], "O-base"),
        ("injected", "fail", False, [("true_flaw", "introduced", [])], "U"),
        ("injected", "fail", False, [("not_a_flaw", "n/a", [])], "N"),
        ("twin", "fail", None, [("true_flaw", "introduced", [])], "O-introduced"),
        ("twin", "fail", None, [("undecidable", "n/a", []), ("not_a_flaw", "n/a", [])], "U"),
        ("twin", "pass", None, [], None),
    ],
)
def test_one_class_per_rejection_the_first_that_holds(
    side: str,
    outcome: str,
    credited: bool | None,
    verdicts: list[tuple[str, str, list[list[str]]]],
    want: str | None,
) -> None:
    lines = [
        line(n, "fresh-v2-x1", "c1", side, "A2", n, locus)
        for n, (_, _, locus) in enumerate(verdicts, 1)
    ]
    got = {
        x["line_id"]: {"verdict": v, "origin": o}
        for x, (v, o, _) in zip(lines, verdicts, strict=True)
    }
    assert (
        rl.classify(review("fresh-v2-x1", "c1", side, "A2", outcome, credited), lines, got, CHANGED)
        == want
    )


def test_a_bar_needs_ten_cases_and_seventy_percent() -> None:
    assert rl.bar(7, 9)["status"] == "not checked"
    assert rl.bar(7, 10)["status"] == "met" and rl.bar(6, 10)["status"] == "missed"
    assert rl.reliability(["met", "met", "met"]) == "reliable"
    assert rl.reliability(["met", "not checked", "met"]) == "unchecked"
    assert rl.reliability(["missed", "not checked", "met"]) == "unreliable"


def _scored(
    tmp: Path,
    sets: Path,
    twin_lines: list[tuple[str, str, str]],
    second: dict[str, tuple[str, str]],
    third: dict[str, tuple[str, str]],
    ff: list[tuple[str, str]] | None,
) -> dict[str, Any]:
    """A reading: twin lines (corpus, arm, verdict:origin) on item c1, judged; then scored."""
    tmp.mkdir(parents=True, exist_ok=True)
    lines, by_line = [], {}
    for n, (corpus, arm, vo) in enumerate(twin_lines, 1):
        lines.append(line(n, corpus, "c1", "twin", arm, n))
        by_line[f"L{n:05d}"] = tuple(vo.split(":"))
    reviews = [
        review(c, "c1", "twin", a, "fail")
        for c in ("fresh-v2-x1", "fresh-v2-s")
        for a in common.ARMS
    ]
    reviews += [
        review(c, "c1", "injected", a, "pass")
        for c in ("fresh-v2-x1", "fresh-v2-s")
        for a in common.ARMS
    ]
    design = {
        c: {"c1": {"role": "control", "changed": [["control.balance_loop", "loop_gain"]]}}
        for c in ("fresh-v2-x1", "fresh-v2-s")
    }
    work = make_work(tmp, lines, reviews, design)
    rl.build_packets(work, sets, tmp / "p")
    judge(tmp / "p", tmp / "s", by_line)  # type: ignore[arg-type]
    for name in ("c", "cs", "f", "fs", "t", "ts"):
        (tmp / name).mkdir()
    (tmp / "c" / "key.json").write_text("{}")
    rl.build_confirm(work, sets, tmp / "p", tmp / "s", [tmp / "p"], tmp / "k")
    judge(tmp / "k", tmp / "ks", second)
    rl.build_third(tmp / "k", tmp / "ks", tmp / "th")
    judge(tmp / "th", tmp / "ths", third)
    if ff is not None:
        key = {
            f"Q09{n:02d}": {"case": c, "findings": {"F1": f"ff-{n}"}} for n, (c, _) in enumerate(ff)
        }
        (tmp / "f" / "key.json").write_text(json.dumps(key))
        for n, (_, vo) in enumerate(ff):
            write_attempt(tmp / "fs", f"Q09{n:02d}", {"F1": tuple(vo.split(":"))})  # type: ignore[dict-item]
    dirs = {
        "reading": (tmp / "p", tmp / "s"),
        "controls": (tmp / "c", tmp / "cs"),
        "ff": (tmp / "f", tmp / "fs"),
        "confirm": (tmp / "k", tmp / "ks"),
        "third": (tmp / "th", tmp / "ths"),
    }
    return rl.score(work, dirs)


def test_twin_statuses_flawed_by_a_confirmed_line_undecided_by_an_unconfirmed_one(
    tmp_path: Path, sets: Path
) -> None:
    got = _scored(
        tmp_path,
        sets,
        [("fresh-v2-x1", "A2", "true_flaw:introduced")],
        {"L00001": ("true_flaw", "both")},
        {},
        None,
    )
    assert got["twins"][0]["status"] == "flawed" and got["twins"][0]["confirmed_by_arm"]["A2"]
    assert got["corrected_A"]["A2"] == {
        "way 1": 1,
        "way 2": 1,
    }  # refused with its own confirmed line
    assert got["corrected_A"]["B"] == {
        "way 1": 0,
        "way 2": 0,
    }  # refused, no confirmed line of its own


def test_an_unconfirmed_flaw_making_line_leaves_the_twin_undecided(
    tmp_path: Path, sets: Path
) -> None:
    got = _scored(
        tmp_path,
        sets,
        [("fresh-v2-x1", "A1", "true_flaw:introduced")],
        {"L00001": ("not_a_flaw", "n/a")},
        {},
        None,
    )
    assert got["twins"][0]["status"] == "undecided"
    assert got["corrected_A"]["A1"] == {"way 1": 0, "way 2": 1}


def test_on_the_class_a_line_must_be_confirmed_twice(tmp_path: Path, sets: Path) -> None:
    got = _scored(
        tmp_path,
        sets,
        [("fresh-v2-s", "A2", "true_flaw:introduced")],
        {"L00001": ("true_flaw", "introduced")},
        {"L00001": ("not_a_flaw", "n/a")},
        None,
    )
    assert got["standard_twins"][0]["status"] == "undecided"
    assert got["confirmation"]["A2"]["confirmed_once_only"] == 1


def test_the_false_finding_control_passes_only_four_of_four_with_a22_s_two_lines_one_case(
    tmp_path: Path, sets: Path
) -> None:
    ok = [
        ("1", "not_a_flaw:n/a"),
        ("2", "not_a_flaw:n/a"),
        ("3", "true_flaw:already_in_base"),
        ("4", "not_a_flaw:n/a"),
        ("4", "not_a_flaw:n/a"),
    ]
    got = _scored(tmp_path / "a", sets, [], {}, {}, ok)
    assert got["controls"]["fresh-v2"]["false_finding"]["status"] == "met"
    assert got["controls"]["fresh-v2"]["false_finding"]["hit"] == 4
    bad = [*ok[:4], ("4", "true_flaw:both")]
    got = _scored(tmp_path / "b", sets, [], {}, {}, bad)
    assert got["controls"]["fresh-v2"]["false_finding"]["status"] == "missed"
    # a22's case holds two lines, and one flaw-making line misses the case.
    assert got["controls"]["fresh-v2"]["false_finding"]["hit"] == 3
    assert got["reliability"] == "unreliable"
    got = _scored(tmp_path / "c", sets, [], {}, {}, None)
    assert got["controls"]["fresh-v2"]["false_finding"]["status"] == "not checked"


def test_the_score_waits_for_every_packet(tmp_path: Path, sets: Path) -> None:
    work = make_work(tmp_path, [line(1, "fresh-v2-x1", "c1", "injected", "A2")])
    rl.build_packets(work, sets, tmp_path / "p")
    with pytest.raises(rl.RefusedError, match="not done"):
        rl.score(
            work,
            {
                "reading": (tmp_path / "p", tmp_path / "s"),
                "controls": (tmp_path / "x", tmp_path / "x"),
                "ff": (tmp_path / "x", tmp_path / "x"),
                "confirm": (tmp_path / "x", tmp_path / "x"),
                "third": (tmp_path / "x", tmp_path / "x"),
            },
        )
