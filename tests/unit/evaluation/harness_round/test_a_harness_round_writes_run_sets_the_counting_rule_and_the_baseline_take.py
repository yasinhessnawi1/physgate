"""A harness round writes the run sets and records its consumers read, and nothing more of a task.

The round runs every task of the three tiers of a stand-in version once, through the real loop,
each on a clone of the target inside its own run directory beneath the registered run root. Its
run sets are held, unchanged, to their consumers: the counting rule (``census``) takes each tier's
set and records, and the baseline's plan takes the combined set. Each tier's set names its own
tier's runs only; each run was given its task's brief byte for byte and started from the
target's commit; the register holds the lines it held before; and the exposure scan reads every
run root whole and finds nothing.

Of a protected task, nothing reaches the round's output directory or what it prints: no id, no
field, no brief and no brief's digest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig, protected_tiers_withheld

from physgate.evaluation.baseline.runner import RunSet, plan
from physgate.evaluation.harness_round import COMBINED, HARNESS_ROUNDS, ROUND_RECORD, run_round
from physgate.evaluation.tiers.checks import check_path
from physgate.evaluation.tiers.exposure import register_lines, run_roots, survey, version_refusal
from physgate.evaluation.tiers.measure import census
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import id_digest
from physgate.orchestrator.run_config import load_run_config

TIERS = ("visible", "validation", "held_out")


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


@pytest.fixture(scope="module")
def whole(tmp_path_factory: pytest.TempPathFactory) -> tuple[Rig, str, dict[str, Any], str]:
    """One round over every task of the three tiers, once each, of a marked store."""
    rig = make_rig(tmp_path_factory.mktemp("whole"), store={"marked": True})
    with protected_tiers_withheld():
        status, summary = run_round(
            rig.inputs(tiers=TIERS, trials=1, tasks=None),
            driver=rig.driver(),
            scorer=_score,
            sleep=lambda _: None,
        )
    printed = json.dumps(summary, sort_keys=True)
    return rig, status, summary, printed


def _place(rig: Rig, summary: dict[str, Any]) -> Path:
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _set(rig: Rig, summary: dict[str, Any], tier: str) -> tuple[Path, Path]:
    where = rig.root / "out" if tier == "visible" else _place(rig, summary)
    return where / f"{tier}.runs.json", where / f"{tier}.trials.jsonl"


def test_every_trial_of_the_round_is_run_and_assembled(
    whole: tuple[Rig, str, dict[str, Any], str],
) -> None:
    rig, status, summary, _ = whole
    assert status == "done" and summary["done"] is True
    assert {t: c["assembled"] for t, c in summary["tiers"].items()} == {t: 8 for t in TIERS}
    assert summary["tiers"]["visible"]["pass"] == 8


@pytest.mark.parametrize("tier", TIERS)
def test_the_counting_rule_takes_each_tier_s_run_set_and_records_unchanged(
    whole: tuple[Rig, str, dict[str, Any], str], tier: str
) -> None:
    rig, _, summary, _ = whole
    runs, trials = _set(rig, summary, tier)
    assert runs.is_file() and trials.is_file(), f"the {tier} tier's set is not where it belongs"
    counted = census(rig.made.store, "control", rig.made.version, tier, runs, trials)
    assert counted.trials == 1 and len(counted.outcomes) == 8
    assert all(o.passes == 1 for o in counted.outcomes.values())


@pytest.mark.parametrize("tier", TIERS)
def test_each_tier_s_run_set_names_its_own_tier_s_runs_alone(
    whole: tuple[Rig, str, dict[str, Any], str], tier: str
) -> None:
    rig, _, summary, _ = whole
    runs, _ = _set(rig, summary, tier)
    briefs = {hashlib.sha256(t.brief.encode()).hexdigest(): t.id for t in rig.made.tasks[tier]}
    named = RunSet.model_validate_json(runs.read_bytes())
    given = [load_run_config(Path(e.run_dir) / "run.json").brief_sha256 for e in named.trials]
    assert sorted(given) == sorted(briefs)


def test_the_baseline_plan_takes_the_combined_run_set_unchanged(
    whole: tuple[Rig, str, dict[str, Any], str],
) -> None:
    rig, _, summary, _ = whole
    combined = RunSet.model_validate_json((_place(rig, summary) / COMBINED).read_bytes())
    _, planned = plan(rig.made.store, "control", rig.made.version, combined, base_url=None)
    assert len(planned) == 24
    assert {p.tier for p in planned} == set(TIERS)
    assert all(p.cap > 0 for p in planned)


def test_each_run_was_given_its_task_s_brief_byte_for_byte_and_the_target_s_commit(
    whole: tuple[Rig, str, dict[str, Any], str],
) -> None:
    rig, _, summary, _ = whole
    record = json.loads((_place(rig, summary) / ROUND_RECORD).read_bytes())
    head = record["inputs"]["target_head"]
    briefs = {
        hashlib.sha256(t.brief.encode()).hexdigest() for tier in TIERS for t in rig.made.tasks[tier]
    }
    for trial in record["trials"]:
        config = load_run_config(Path(trial["run_dir"]) / "run.json")
        brief = _place(rig, summary) / "briefs" / f"{trial['index']:04d}.md"
        assert hashlib.sha256(brief.read_bytes()).hexdigest() == config.brief_sha256
        assert config.brief_sha256 == trial["brief_sha256"] and config.brief_sha256 in briefs
        assert config.target_head == head
        assert config.seed == 100 + trial["index"] and config.run_id == trial["run_id"]
        # The clone and the review root lie inside the run's own directory.
        assert (Path(trial["run_dir"]) / "target" / ".git").is_dir()
        assert (Path(trial["run_dir"]) / "review").is_dir()
        assert Path(trial["run_dir"]).parent.parent == rig.run_root.resolve()
    assert len({t["run_dir"] for t in record["trials"]}) == 24


def test_the_round_s_record_names_its_digests_pins_and_every_trial(
    whole: tuple[Rig, str, dict[str, Any], str],
) -> None:
    rig, _, summary, _ = whole
    record = json.loads((_place(rig, summary) / ROUND_RECORD).read_bytes())
    inputs = record["inputs"]
    assert inputs["version"] == rig.made.version
    assert inputs["params_sha256"] == hashlib.sha256(rig.params.read_bytes()).hexdigest()
    check = check_path(rig.made.store, "control", rig.made.version)
    assert inputs["check_sha256"] == summary["check_sha256"]
    assert hashlib.sha256(check.read_bytes()).hexdigest() == inputs["check_sha256"]
    assert set(record["protected_sha256"]) == {"validation", "held_out"}
    assert record["pins"]["claude_version"] == "2.1.301"
    assert record["pins"]["account"] == "run-seat-1"
    assert all(t["harness_total"] and t["harness_total"] > 0 for t in record["trials"])
    assert [t["index"] for t in record["trials"]] == list(range(24))
    # The order: the tiers as the version holds them, each tier's tasks by their brief's digest.
    tiers = [t["tier"] for t in record["trials"]]
    assert tiers == [tier for tier in TIERS for _ in range(8)]
    for tier in TIERS:
        briefs = [t["brief_sha256"] for t in record["trials"] if t["tier"] == tier]
        assert briefs == sorted(briefs)
    assert record["superseded"] == [] and record["left"] == []


def test_the_round_writes_no_line_of_the_register(
    whole: tuple[Rig, str, dict[str, Any], str],
) -> None:
    rig, _, summary, _ = whole
    assert summary["register_before"] == summary["register_after"]
    assert summary["register_after"]["lines"] == len(register_lines(rig.made.store, "control"))


def test_the_exposure_scan_reads_every_run_root_whole_and_each_run_passes_the_version_check(
    whole: tuple[Rig, str, dict[str, Any], str],
) -> None:
    rig, _, summary, _ = whole
    roots = run_roots(rig.made.store, "control")
    seen = survey(rig.made.store, "control", roots)
    assert seen.findings == () and seen.unread == () and seen.missing == ()
    record = json.loads((_place(rig, summary) / ROUND_RECORD).read_bytes())
    for trial in record["trials"]:
        run_dir = Path(trial["run_dir"])
        assert version_refusal(load_run_config(run_dir / "run.json"), run_dir) is None


def _protected_words(rig: Rig) -> set[str]:
    """Every string that names a protected task: its id and its digest, its brief and its digest."""
    found: set[str] = set()
    for tier in TIERS[1:]:
        for task in rig.made.tasks[tier]:
            found |= {task.id, id_digest(task.id), task.brief}
            found.add(hashlib.sha256(task.brief.encode()).hexdigest())
            found.add(task.id.split(".", 1)[1])  # the marker every field of it carries
    return found


def test_nothing_of_a_protected_task_reaches_the_output_directory_or_what_is_printed(
    whole: tuple[Rig, str, dict[str, Any], str],
) -> None:
    rig, _, _, printed = whole
    words = _protected_words(rig)
    assert all(w.startswith("zqmark") or len(w) > 8 for w in words)
    texts = {"printed": printed}
    for path in sorted((rig.root / "out").rglob("*")):
        if path.is_file():
            texts[path.name] = path.read_text()
    leaked = sorted(f"{name}: {w[:12]}" for name, text in texts.items() for w in words if w in text)
    assert leaked == []
    assert sorted(texts) == ["printed", "round.json", "visible.runs.json", "visible.trials.jsonl"]
