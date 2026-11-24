"""A control module's law file is exported as the controller only if it reproduces its vectors.

The graph is built here through the store's own writer, as the export's other rows build one,
and the law file is committed in a throwaway repository whose last commit the run's event log
names as its last merge. The law is a recorded design's: its coefficients on one node, a leaky
tilt estimate, the previous encoder angle and the previous command as memory, the test vectors
its design note states (the rows where the speed command is zero: the others exercise the
feed-forward and the reference's ramp, which the loop's analysis holds outside the law).

Each refusal is a status of its own and writes nothing: no file, units that do not balance, a
coefficient the graph does not hold (a leak named differently among them), a vector the law does
not reproduce, a law that is not linear or reads a signal outside the list. A law file is held to
the rules of reading an answer is held to: a key written twice, a sign written ``true`` and two
states marked applied refuse the file before anything is exported.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.whole.answer import parse_answer
from physgate.evaluation.whole.export import ExportError, export_whole_run, record_path
from physgate.state.store import Store

_HERE = Path(__file__).resolve().parent
_LAW = _HERE / "recorded_law" / "law.json"
_RECORDED = _HERE / "recorded_runs" / "records_a_sign_off_owed.jsonl"
_LAST_MERGE = "d4f71d6277580641385da872befcfa3ffac222bc"
_MODULE = "modules/c1"

Values = dict[str, tuple[float | int, str]]

COEFFICIENTS: Values = {
    "k_phi": (-0.0054505, "1/rad"),
    "k_theta": (-1.03529, "1/rad"),
    "k_w": (-0.038326, "s/rad"),
    "k_rate": (-0.0625146, "s/rad"),
    "k_u": (-0.346975, "1"),
    "leak": (0.999, "1"),
    "update_rate": (100, "Hz"),
    "duty_cycle": (0.9425, "1"),
    "computation_delay_bound": (0.003, "s"),
    "update_lateness_bound": (0.001, "s"),
    "output_data_rate": (208, "Hz"),
}
SETTINGS: Values = {
    "update_rate": (100, "Hz"),
    "gyro_full_scale": (1000, "deg/s"),
    "pwm_frequency": (20000, "Hz"),
    "pwm_full_scale": (400, "count"),
    "encoder_counts_per_wheel_revolution": (1322.9, "count"),
}
ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **ENV},
    )
    return done.stdout.strip()


def _repo(tmp_path: Path, *versions: bytes | None) -> tuple[Path, list[str]]:
    """A repository with a commit per version of the law file (``None``: no file), oldest first."""
    repo = Path(os.path.realpath(tmp_path)) / "target"
    repo.mkdir()
    _git(repo, "init", "-q")
    commits = []
    for n, body in enumerate(versions):
        (repo / "README").write_text(f"{n}")
        target = repo / _MODULE / "law.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if body is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(body)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"v{n}")
        commits.append(_git(repo, "rev-parse", "HEAD"))
    return repo, commits


def _node(
    node_id: str, values: Values, owner: str, domain: str, kind: str = "module"
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "domain": domain,
        "owner_role": owner,
        "quantities": {
            name: {"value": value, "unit": unit, "source": "fixture", "written_by": owner}
            for name, (value, unit) in values.items()
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "none",
        "updated": "2026-11-20",
    }


def _run(
    tmp_path: Path,
    merge: str,
    *,
    coefficients: Values | None = None,
    settings: Values | None = None,
    interface: dict[str, Values] | None = None,
) -> Path:
    run = Path(os.path.realpath(tmp_path)) / "run"
    (run / "store").mkdir(parents=True)
    log = _RECORDED.read_text()
    assert log.count(_LAST_MERGE) == 1
    (run / "events.jsonl").write_text(log.replace(_LAST_MERGE, merge))
    store = Store(run / "store")
    try:
        for node in (
            _node(
                "control.balance_controller",
                COEFFICIENTS if coefficients is None else coefficients,
                "control",
                "control",
            ),
            _node(
                "firmware.loop_timing",
                SETTINGS if settings is None else settings,
                "firmware",
                "firmware",
            ),
            *(
                _node(node_id, values, _OWNERS.get(node_id, "firmware"), "cross", "interface")
                for node_id, values in (interface or {}).items()
            ),
        ):
            assert store.write_node(node, node["owner_role"]).accepted
    finally:
        store.close()
    return run


def _out(tmp_path: Path, name: str = "answer.json") -> Path:
    return Path(os.path.realpath(tmp_path)) / "answers" / name


def _file() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(_LAW.read_text())
    return document


def _bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(document).encode()


def _export(tmp_path: Path, law: bytes | None = None, **kwargs: Any) -> tuple[Any, Path, Path, str]:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes() if law is None else law)
    run = _run(
        tmp_path,
        commit,
        **{k: v for k, v in kwargs.items() if k in ("coefficients", "settings", "interface")},
    )
    out = _out(tmp_path)
    record = export_whole_run(run, out, repository=repo, supplied=kwargs.get("supplied"))
    return record, out, run, commit


def test_the_recorded_law_is_exported_as_a_version_3_answer_with_the_graph_s_numbers(
    tmp_path: Path,
) -> None:
    record, out, _, commit = _export(tmp_path)
    assert record.status == "exported", (record.law_reason, record.law_detail)
    assert record.structure == "sampled_law"
    answer = json.loads(out.read_bytes())
    assert answer["version"] == 3
    controller = answer["controller"]
    assert controller["structure"] == "sampled_law"
    assert {n: (c["value"], c["unit"]) for n, c in controller["coefficients"].items()} == {
        n: COEFFICIENTS[n] for n in ("k_phi", "k_theta", "k_w", "k_rate", "k_u", "leak")
    }
    assert controller["period"] == {"value": 0.01, "unit": "s"}
    assert controller["command_limit"] == {"value": 0.9425, "unit": "1"}
    assert controller["sensor_delay"] == {"value": 1 / 208, "unit": "s"}
    assert controller["compute_delay"] == {"value": 0.003 + 0.001, "unit": "s"}
    assert answer["parameters"]["output_data_rate"] == {"value": 208, "unit": "Hz"}
    assert "gyro_output_data_rate" not in answer["parameters"]
    parse_answer(out.read_bytes())  # the scorer's own reading takes it whole
    assert record.sha256 == hashlib.sha256(out.read_bytes()).hexdigest()


def test_the_record_names_the_file_s_digest_the_commit_it_was_read_at_and_the_rows_it_reproduced(
    tmp_path: Path,
) -> None:
    record, out, _, commit = _export(tmp_path)
    assert record.law_sha256 == hashlib.sha256(_LAW.read_bytes()).hexdigest()
    assert record.law_commit == commit
    assert record.law_path == f"{_MODULE}/law.json"
    assert record.vector_rows == 30
    written = json.loads(record_path(out).read_text())
    assert written["law_sha256"] == record.law_sha256
    assert written["law_commit"] == commit
    assert written["vector_rows"] == 30
    assert written["answer_sha256"] == record.sha256


def test_the_same_run_is_exported_to_the_same_bytes(tmp_path: Path) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    run = _run(tmp_path, commit)
    first, second = _out(tmp_path, "one.json"), _out(tmp_path, "two.json")
    export_whole_run(run, first, repository=repo)
    export_whole_run(run, second, repository=repo)
    assert first.read_bytes() == second.read_bytes()


def _tree(root: Path) -> list[tuple[str, int, bytes, int]]:
    rows = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        body = b"" if path.is_dir() or path.is_symlink() else path.read_bytes()
        rows.append((str(path.relative_to(root)), info.st_size, body, info.st_mtime_ns))
    return rows


def test_neither_the_run_nor_the_repository_is_written(tmp_path: Path) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    run = _run(tmp_path, commit)
    before_run, before_repo = _tree(run), _tree(repo)
    record = export_whole_run(run, _out(tmp_path), repository=repo)
    assert record.status == "exported"
    assert _tree(run) == before_run
    assert _tree(repo) == before_repo


def test_the_file_is_read_at_the_last_merged_commit_not_from_the_working_copy(
    tmp_path: Path,
) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    (repo / _MODULE / "law.json").write_text("{ not the merged file")
    run = _run(tmp_path, commit)
    record = export_whole_run(run, _out(tmp_path), repository=repo)
    assert record.status == "exported"
    assert record.law_sha256 == hashlib.sha256(_LAW.read_bytes()).hexdigest()


def test_a_commit_after_the_last_merge_is_never_read(tmp_path: Path) -> None:
    broken = _bytes({**_file(), "form": "other"})
    repo, (merged, _later) = _repo(tmp_path, _LAW.read_bytes(), broken)
    run = _run(tmp_path, merged)
    record = export_whole_run(run, _out(tmp_path), repository=repo)
    assert record.status == "exported"
    assert record.law_commit == merged


def test_an_earlier_commit_than_the_last_merge_is_not_the_one_read(tmp_path: Path) -> None:
    broken = _bytes({**_file(), "form": "other"})
    repo, (_earlier, merged) = _repo(tmp_path, broken, _LAW.read_bytes())
    run = _run(tmp_path, merged)
    assert export_whole_run(run, _out(tmp_path), repository=repo).status == "exported"


def _nothing_written(out: Path) -> None:
    assert not out.exists()
    assert not record_path(out).exists()


def test_a_module_with_no_law_file_and_no_named_structure_is_law_missing(tmp_path: Path) -> None:
    repo, (commit,) = _repo(tmp_path, None)
    run = _run(tmp_path, commit)
    out = _out(tmp_path)
    record = export_whole_run(run, out, repository=repo)
    assert record.status == "law_missing"
    _nothing_written(out)


def test_no_repository_given_is_today_s_contract_lost_and_nothing_else(tmp_path: Path) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    run = _run(tmp_path, commit)
    out = _out(tmp_path)
    record = export_whole_run(run, out)
    assert record.status == "contract_lost"
    assert record.law_path is None
    _nothing_written(out)


FEEDBACK: Values = {
    "period": (0.01, "s"),
    "command_limit": (0.75, "1"),
    "sensor_delay": (0.0048, "s"),
    "compute_delay": (0.002, "s"),
    "angle_gain": (1.6643, "1/rad"),
    "rate_gain": (0.191, "s/rad"),
    "distance_gain": (0.2853, "1/m"),
    "speed_gain": (1.3421, "s/m"),
}
SETTINGS_V2: Values = {
    **SETTINGS,
    "gyro_output_data_rate": (208, "Hz"),
}


def test_a_named_structure_and_no_law_file_export_the_same_bytes_with_or_without_a_repository(
    tmp_path: Path,
) -> None:
    repo, (commit,) = _repo(tmp_path, None)
    run = _run(tmp_path, commit, coefficients=FEEDBACK, settings=SETTINGS_V2)
    plain, looked = _out(tmp_path, "plain.json"), _out(tmp_path, "looked.json")
    first = export_whole_run(run, plain)
    second = export_whole_run(run, looked, repository=repo)
    assert first.status == second.status == "exported"
    assert json.loads(plain.read_bytes())["version"] == 2
    assert plain.read_bytes() == looked.read_bytes()
    assert record_path(plain).read_bytes() == record_path(looked).read_bytes().replace(
        b"looked.json", b"plain.json"
    )
    assert "law_" not in record_path(looked).read_text()


def test_a_law_file_beside_a_named_structure_whole_is_ambiguous(tmp_path: Path) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    run = _run(tmp_path, commit, coefficients={**COEFFICIENTS, **FEEDBACK}, settings=SETTINGS_V2)
    out = _out(tmp_path)
    record = export_whole_run(run, out, repository=repo)
    assert record.status == "ambiguous"
    assert "sampled_law" in record.complete
    assert "state_feedback" in record.complete
    _nothing_written(out)


def _refused(tmp_path: Path, code: str, *, law: bytes | None = None, **kwargs: Any) -> Any:
    record, out, _, _ = _export(tmp_path, law, **kwargs)
    assert record.status == "law_unverified", (record.status, record.law_reason)
    assert record.law_reason == code, record.law_detail
    assert record.law_detail
    _nothing_written(out)
    return record


# ── the vectors must demand something of the law ────────────────────────────────────────────

ABSURD: Values = {
    **COEFFICIENTS,
    "k_phi": (9, "1/rad"),
    "k_theta": (50, "1/rad"),
    "k_w": (-5, "s/rad"),
    "k_rate": (7, "s/rad"),
    "k_u": (3, "1"),
    "leak": (1.7, "1"),
}


def test_one_all_zero_row_does_not_export_a_law_with_absurd_coefficients(tmp_path: Path) -> None:
    document = _file()
    document["vectors"] = [{"name": "nothing", "rows": [{"duty": 0.0, "counts": 0}]}]
    record = _refused(tmp_path, "vectors_too_few", law=_bytes(document), coefficients=ABSURD)
    assert "1 row" in record.law_detail
    assert "10" in record.law_detail


def _first_rows(duty_of: Any, count: int) -> list[dict[str, Any]]:
    """``count`` one-row vectors from a zero state, the signal and the honest duty of each."""
    vectors = []
    for n in range(count):
        rate = 0.1 + 0.05 * n
        duty = duty_of(rate)
        vectors.append(
            {
                "name": f"first update {n}",
                "rows": [{"tilt_rate": rate, "duty": duty, "counts": round(duty * 400)}],
            }
        )
    return vectors


def test_vectors_that_are_only_first_rows_do_not_pin_the_memory_the_law_keeps(
    tmp_path: Path,
) -> None:
    k_theta, k_w, k_rate = -0.0054505 - 1.03529, -0.038326, -0.0625146
    honest = lambda rate: -(k_theta * 0.01 * rate + k_w * rate + k_rate * rate)  # noqa: E731
    document = _file()
    document["vectors"] = _first_rows(honest, 12)
    coefficients = {**COEFFICIENTS, "k_u": (-9, "1"), "leak": (5, "1")}
    record = _refused(
        tmp_path, "vectors_do_not_exercise", law=_bytes(document), coefficients=coefficients
    )
    assert "u_prev" in record.law_detail
    assert "theta_hat" in record.law_detail


def _with_a_hidden_tilt_term() -> dict[str, Any]:
    document = _file()
    command = next(x for x in document["lines"] if x["name"] == "command")
    command["terms"].append({"sign": -1, "coefficients": ["k_true"], "of": "tilt"})
    document["coefficients"]["k_true"] = "k_true"
    return document


def test_a_term_on_a_signal_no_vector_row_sets_is_refused_and_the_signal_is_named(
    tmp_path: Path,
) -> None:
    record = _refused(
        tmp_path,
        "vectors_do_not_exercise",
        law=_bytes(_with_a_hidden_tilt_term()),
        coefficients={**COEFFICIENTS, "k_true": (1.0, "1/rad")},
    )
    assert "tilt" in record.law_detail
    assert "k_true" not in record.law_detail or "command" in record.law_detail


def test_a_term_so_small_that_no_vector_output_moves_when_it_changes_is_refused_and_named(
    tmp_path: Path,
) -> None:
    document = _file()
    command = next(x for x in document["lines"] if x["name"] == "command")
    command["terms"].append({"sign": 1, "coefficients": ["k_extra"], "of": "line.theta_now"})
    document["coefficients"]["k_extra"] = "k_extra"
    record = _refused(
        tmp_path,
        "vectors_do_not_pin",
        law=_bytes(document),
        coefficients={**COEFFICIENTS, "k_extra": (1e-9, "1/rad")},
    )
    assert "k_extra" in record.law_detail


def test_fewer_than_the_minimum_rows_is_refused_with_the_count_said(tmp_path: Path) -> None:
    document = _file()
    kept, rows = [], 0
    for vector in document["vectors"]:
        if rows + len(vector["rows"]) > 9:
            break
        kept.append(vector)
        rows += len(vector["rows"])
    assert rows == 9
    document["vectors"] = kept
    record = _refused(tmp_path, "vectors_too_few", law=_bytes(document))
    assert "9 rows" in record.law_detail


def test_the_record_names_the_signals_the_law_reads(tmp_path: Path) -> None:
    record, out, _, _ = _export(tmp_path)
    assert record.law_signals == ("tilt_rate", "wheel_angle", "wheel_reference")
    assert json.loads(record_path(out).read_text())["law_signals"] == [
        "tilt_rate",
        "wheel_angle",
        "wheel_reference",
    ]


def test_a_file_whose_units_do_not_balance_is_refused_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    record = _refused(
        tmp_path,
        "units_do_not_balance",
        coefficients={**COEFFICIENTS, "k_phi": (-0.0054505, "1/m")},
    )
    assert "command" in record.law_detail


def test_a_sum_of_delays_in_two_units_is_refused(tmp_path: Path) -> None:
    _refused(
        tmp_path,
        "units_do_not_balance",
        coefficients={**COEFFICIENTS, "update_lateness_bound": (1, "ms")},
    )


def test_a_rate_that_is_not_in_hz_has_no_reciprocal_period(tmp_path: Path) -> None:
    _refused(
        tmp_path,
        "units_do_not_balance",
        coefficients={**COEFFICIENTS, "update_rate": (100, "1/s")},
        settings={**SETTINGS, "update_rate": (100, "1/s")},
    )


def test_a_coefficient_the_graph_does_not_hold_is_refused_and_named(tmp_path: Path) -> None:
    held = {k: v for k, v in COEFFICIENTS.items() if k != "k_u"}
    record = _refused(tmp_path, "coefficient_not_held", coefficients=held)
    assert "k_u" in record.law_detail


def test_a_leak_the_graph_names_differently_is_not_silently_exported_without_it(
    tmp_path: Path,
) -> None:
    renamed = {("angle_decay_per_update" if k == "leak" else k): v for k, v in COEFFICIENTS.items()}
    record = _refused(tmp_path, "coefficient_not_held", coefficients=renamed)
    assert "leak" in record.law_detail


def test_a_law_that_does_not_reproduce_a_vector_is_refused_and_the_first_miss_is_said(
    tmp_path: Path,
) -> None:
    record = _refused(
        tmp_path,
        "vector_not_reproduced",
        coefficients={**COEFFICIENTS, "k_theta": (-1.0, "1/rad")},
    )
    assert "vector" in record.law_detail
    assert "update" in record.law_detail


def test_a_flipped_sign_in_the_law_is_caught_by_the_vectors_though_units_balance(
    tmp_path: Path,
) -> None:
    document = _file()
    command = next(x for x in document["lines"] if x["name"] == "command")
    command["terms"][4]["sign"] = 1  # k_rate
    _refused(tmp_path, "vector_not_reproduced", law=_bytes(document))


def test_a_missing_memory_term_is_caught_by_the_vectors(tmp_path: Path) -> None:
    document = _file()
    command = next(x for x in document["lines"] if x["name"] == "command")
    command["terms"] = command["terms"][:-1]  # the previous command's term
    _refused(tmp_path, "vector_not_reproduced", law=_bytes(document))


def test_a_duty_off_by_more_than_its_tolerance_is_a_miss_and_by_less_is_not(tmp_path: Path) -> None:
    document = _file()
    document["vectors"][1]["rows"][0]["duty"] += 5e-6
    record, _, _, _ = _export(tmp_path, _bytes(document))
    assert record.status == "exported"
    document["vectors"][1]["rows"][0]["duty"] += 2e-5
    other = tmp_path / "again"
    other.mkdir()
    _refused(other, "vector_not_reproduced", law=_bytes(document))


def test_a_command_off_by_one_count_is_taken_and_by_two_is_a_miss(tmp_path: Path) -> None:
    document = _file()
    document["vectors"][1]["rows"][0]["counts"] += 1
    record, _, _, _ = _export(tmp_path, _bytes(document))
    assert record.status == "exported"
    document["vectors"][1]["rows"][0]["counts"] += 1
    other = tmp_path / "again"
    other.mkdir()
    _refused(other, "vector_not_reproduced", law=_bytes(document))


def test_a_memory_state_after_an_update_is_checked_too(tmp_path: Path) -> None:
    document = _file()
    document["vectors"][1]["rows"][0]["memory"]["theta_hat"] += 1e-3
    _refused(tmp_path, "vector_not_reproduced", law=_bytes(document))


def test_a_vector_that_names_no_memory_state_is_a_miss(tmp_path: Path) -> None:
    document = _file()
    document["vectors"][1]["rows"][0]["memory"]["nothing"] = 0.0
    _refused(tmp_path, "vector_not_reproduced", law=_bytes(document))


@pytest.mark.parametrize(
    ("of", "code"),
    [
        ("abs(line.phi_hat)", "nonlinear"),
        ("tilt_rate*wheel_angle", "nonlinear"),
        ("accelerometer_tilt", "out_of_scope"),
    ],
)
def test_a_law_that_is_not_linear_or_reads_a_signal_outside_the_list_is_refused_by_name(
    tmp_path: Path, of: str, code: str
) -> None:
    document = _file()
    next(x for x in document["lines"] if x["name"] == "command")["terms"][0]["of"] = of
    _refused(tmp_path, code, law=_bytes(document))


def test_a_file_that_is_not_a_law_is_refused_as_malformed(tmp_path: Path) -> None:
    _refused(tmp_path, "malformed", law=b"[1, 2")


def test_a_file_with_no_vectors_is_refused_since_nothing_checks_it(tmp_path: Path) -> None:
    _refused(tmp_path, "malformed", law=_bytes({**_file(), "vectors": []}))


def test_a_file_past_its_size_is_refused_unread(tmp_path: Path) -> None:
    document = _file()
    document["vectors"][0]["name"] = "x" * 300_000
    _refused(tmp_path, "malformed", law=_bytes(document))


# ── the law file is read as an answer is read ───────────────────────────────────────────────

_COMMAND = b'"command": "command"'
_COMMAND_TWICE = b'"command": "no_such_line", "command": "command"'


def test_a_law_file_with_a_key_written_twice_is_refused_before_export_in_an_answer_s_words(
    tmp_path: Path,
) -> None:
    # The harness's file: refused by name, nothing exported, the last copy never read.
    text = _LAW.read_bytes()
    assert text.count(_COMMAND) == 1
    harness = tmp_path / "harness"
    harness.mkdir()
    record = _refused(harness, "key_written_twice", law=text.replace(_COMMAND, _COMMAND_TWICE))
    said = "the key 'command' is written twice in one object; each key is written once"
    assert record.law_detail == said
    # The same slip in the answer the same law exports to: refused in the same words.
    clean = tmp_path / "clean"
    clean.mkdir()
    exported, out, _, _ = _export(clean)
    assert exported.status == "exported"
    answer = out.read_bytes()
    assert answer.count(_COMMAND) == 1
    with pytest.raises(TaskFormatError) as caught:
        parse_answer(answer.replace(_COMMAND, _COMMAND_TWICE))
    assert f"key_written_twice: {said}" in str(caught.value)


def test_a_law_file_with_a_sign_written_true_is_refused_before_export(tmp_path: Path) -> None:
    text = _LAW.read_text()
    assert '"sign": 1,' in text
    record = _refused(
        tmp_path, "malformed", law=text.replace('"sign": 1,', '"sign": true,', 1).encode()
    )
    assert "not a truth value" in record.law_detail


def test_a_law_file_with_two_states_marked_applied_is_refused_before_export(
    tmp_path: Path,
) -> None:
    document = _file()
    document["memory"].append({"name": "u_again", "unit": "1", "next": "command", "applied": True})
    record = _refused(tmp_path, "malformed", law=_bytes(document))
    assert "2 memory states, 'u_prev' and 'u_again', are marked applied" in record.law_detail


def test_a_setting_the_graph_lacks_is_contract_lost_and_named(tmp_path: Path) -> None:
    held = {k: v for k, v in SETTINGS.items() if k != "gyro_full_scale"}
    record, out, _, _ = _export(tmp_path, settings=held)
    assert record.status == "contract_lost"
    assert record.missing == {"parameters": ("gyro_full_scale",)}
    _nothing_written(out)


def test_a_setting_the_caller_supplies_is_exported_as_given_and_the_record_says_so(
    tmp_path: Path,
) -> None:
    held = {k: v for k, v in SETTINGS.items() if k != "gyro_full_scale"}
    record, out, _, _ = _export(
        tmp_path, settings=held, supplied={"gyro_full_scale": (1000, "deg/s")}
    )
    assert record.status == "exported"
    assert record.supplied == {"gyro_full_scale": {"value": 1000, "unit": "deg/s"}}
    assert json.loads(out.read_bytes())["parameters"]["gyro_full_scale"] == {
        "value": 1000,
        "unit": "deg/s",
    }
    assert json.loads(record_path(out).read_text())["supplied"] == {
        "gyro_full_scale": {"value": 1000, "unit": "deg/s"}
    }


def test_a_supplied_setting_the_graph_already_holds_or_that_is_no_setting_is_an_error(
    tmp_path: Path,
) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    run = _run(tmp_path, commit)
    for name in ("gyro_full_scale", "not_a_setting"):
        with pytest.raises(ExportError):
            export_whole_run(run, _out(tmp_path), repository=repo, supplied={name: (1000, "deg/s")})


@pytest.mark.parametrize(
    "supplied",
    [
        (-3, "deg/s"),
        (0, "deg/s"),
        (20000, "deg/s"),
        (1000, "bananas"),
        (1000, "deg / s"),
        (True, "deg/s"),
        (float("nan"), "deg/s"),
        (float("inf"), "deg/s"),
        ("1000", "deg/s"),
    ],
)
def test_a_supplied_value_that_is_no_value_of_its_setting_is_an_error_and_nothing_is_written(
    tmp_path: Path, supplied: Any
) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    held = {k: v for k, v in SETTINGS.items() if k != "gyro_full_scale"}
    run = _run(tmp_path, commit, settings=held)
    out = _out(tmp_path)
    with pytest.raises(ExportError, match="gyro_full_scale"):
        export_whole_run(run, out, repository=repo, supplied={"gyro_full_scale": supplied})
    _nothing_written(out)


def test_a_supplied_pwm_full_scale_is_a_whole_number_of_counts(tmp_path: Path) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    held = {k: v for k, v in SETTINGS.items() if k != "pwm_full_scale"}
    run = _run(tmp_path, commit, settings=held)
    with pytest.raises(ExportError, match="whole number"):
        export_whole_run(
            run, _out(tmp_path), repository=repo, supplied={"pwm_full_scale": (400.5, "count")}
        )


def test_a_supplied_pwm_full_scale_is_the_one_the_vectors_are_counted_in(tmp_path: Path) -> None:
    held = {k: v for k, v in SETTINGS.items() if k != "pwm_full_scale"}
    record, out, _, _ = _export(
        tmp_path, settings=held, supplied={"pwm_full_scale": (400, "count")}
    )
    assert record.status == "exported"
    assert json.loads(out.read_bytes())["parameters"]["pwm_full_scale"]["value"] == 400
    assert record.supplied == {"pwm_full_scale": {"value": 400, "unit": "count"}}


def test_a_law_whose_answer_the_scorer_could_not_read_is_a_refusal_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    # The delay sum is not in the vectors, so they pass; the answer's own bound on it does not.
    record = _refused(
        tmp_path,
        "answer_not_valid",
        coefficients={**COEFFICIENTS, "computation_delay_bound": (0.9, "s")},
    )
    assert "delay" in record.law_detail


def _repo_with_the_law_path_as(tmp_path: Path, make: Any) -> tuple[Path, str]:
    repo = Path(os.path.realpath(tmp_path)) / "target"
    repo.mkdir()
    _git(repo, "init", "-q")
    target = repo / _MODULE / "law.json"
    target.parent.mkdir(parents=True)
    make(target)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the law's path is not a file")
    return repo, _git(repo, "rev-parse", "HEAD")


def _a_directory(target: Path) -> None:
    target.mkdir()
    (target / "inside.json").write_bytes(_LAW.read_bytes())


def _a_link_out(target: Path) -> None:
    (target.parent.parent.parent / "outside.json").write_bytes(_LAW.read_bytes())
    target.symlink_to("../../outside.json")


@pytest.mark.parametrize("make", [_a_directory, _a_link_out])
def test_a_directory_or_a_link_at_the_law_s_path_is_a_status_and_is_never_followed(
    tmp_path: Path, make: Any
) -> None:
    repo, commit = _repo_with_the_law_path_as(tmp_path, make)
    run = _run(tmp_path, commit)
    out = _out(tmp_path)
    try:
        record = export_whole_run(run, out, repository=repo)
    except ExportError as exc:
        pytest.fail(f"a status was owed, not an error: {exc}")
    assert record.status == "law_unverified"
    assert record.law_reason == "malformed"
    assert record.law_detail
    _nothing_written(out)


def test_a_loop_quantity_held_in_another_unit_than_the_loop_takes_is_refused(
    tmp_path: Path,
) -> None:
    record = _refused(
        tmp_path,
        "units_do_not_balance",
        coefficients={**COEFFICIENTS, "duty_cycle": (0.9425, "count")},
    )
    assert "duty_cycle" in record.law_detail or "command limit" in record.law_detail


# ── the loop's delays and limit may not be kinder than the run's interface states ───────────

_OWNERS = {"firmware.timing": "firmware", "drive.train": "mechanical"}
INTERFACE: dict[str, Values] = {
    "firmware.timing": {
        "update_rate": (100, "Hz"),
        "output_data_rate": (208, "Hz"),
        "update_lateness_bound": (0.001, "s"),
        "computation_delay_bound": (0.003, "s"),
    },
    "drive.train": {"duty_cycle": (0.9425, "1")},
}


def _timing_from(document: dict[str, Any], name: str, source: dict[str, Any]) -> bytes:
    document[name] = source
    return _bytes(document)


def test_a_sensor_delay_of_a_1_ms_quantity_is_refused_against_the_interface_s_208_hz(
    tmp_path: Path,
) -> None:
    document = _file()
    document["coefficients"]["fast_delay"] = "fast_delay"
    document["sensor_delay"] = {"quantity": "fast_delay"}
    record = _refused(
        tmp_path,
        "delay_or_limit_not_stated_by_the_interface",
        law=_bytes(document),
        coefficients={**COEFFICIENTS, "fast_delay": (0.001, "s")},
        interface=INTERFACE,
    )
    assert "sensor delay" in record.law_detail
    assert "output_data_rate" in record.law_detail


def test_a_compute_delay_pointing_at_a_quantity_only_control_holds_is_flagged_not_refused(
    tmp_path: Path,
) -> None:
    # No catalogue name gives the compute delay's floor, so only where the quantity comes from is
    # checked: a quantity no interface holds is exported with the no-statement flag.
    document = _file()
    document["coefficients"]["short_delay"] = "short_delay"
    document["compute_delay"] = {"quantity": "short_delay"}
    record, _, _, _ = _export(
        tmp_path,
        _bytes(document),
        coefficients={**COEFFICIENTS, "short_delay": (0.001, "s")},
        interface=INTERFACE,
    )
    assert record.status == "exported"
    assert record.law_timing["compute_delay"]["no_interface_statement"] is True
    assert record.law_timing["compute_delay"]["writers"] == ["control"]


def test_a_command_limit_above_the_interface_s_is_refused(tmp_path: Path) -> None:
    document = _file()
    document["coefficients"]["my_limit"] = "my_limit"
    document["command_limit"] = {"quantity": "my_limit"}
    record = _refused(
        tmp_path,
        "delay_or_limit_not_stated_by_the_interface",
        law=_bytes(document),
        coefficients={**COEFFICIENTS, "my_limit": (0.9425, "1")},
        interface={**INTERFACE, "drive.train": {"duty_cycle": (0.9, "1")}},
    )
    assert "command limit" in record.law_detail


def test_a_larger_delay_and_a_smaller_limit_are_accepted_as_pessimistic(tmp_path: Path) -> None:
    document = _file()
    document["coefficients"]["slow_delay"] = "slow_delay"
    document["sensor_delay"] = {"quantity": "slow_delay"}
    record, out, _, _ = _export(
        tmp_path,
        _bytes(document),
        coefficients={**COEFFICIENTS, "slow_delay": (0.02, "s")},
        interface=INTERFACE,
    )
    assert record.status == "exported", (record.law_reason, record.law_detail)
    assert record.law_timing["sensor_delay"]["value"] == 0.02


def test_a_copy_equal_to_the_interface_is_the_floor_applied_and_the_flag_is_absent(
    tmp_path: Path,
) -> None:
    record, out, _, _ = _export(tmp_path, interface=INTERFACE)
    assert record.status == "exported"
    assert record.law_timing["sensor_delay"] == {
        "names": ["output_data_rate"],
        "nodes": ["control.balance_controller", "firmware.timing"],
        "writers": ["control", "firmware"],
        "value": 1 / 208,
        "unit": "s",
        "held_against": {"name": "output_data_rate", "node": "firmware.timing", "value": 1 / 208},
        "no_interface_statement": False,
    }
    for key in ("period", "sensor_delay", "compute_delay", "command_limit"):
        assert record.law_timing[key]["no_interface_statement"] is False, key
    answer = json.loads(out.read_bytes())
    assert answer["controller"]["no_interface_statement"] == []
    assert json.loads(record_path(out).read_text())["law_timing"]["command_limit"][
        "held_against"
    ] == {"name": "duty_cycle", "node": "drive.train", "value": 0.9425}


def test_a_run_whose_interface_states_nothing_is_exported_with_the_flag_on_each_setting(
    tmp_path: Path,
) -> None:
    record, out, _, _ = _export(tmp_path)
    assert record.status == "exported"
    flagged = ["command_limit", "compute_delay", "period", "sensor_delay"]
    assert sorted(k for k, v in record.law_timing.items() if v["no_interface_statement"]) == flagged
    assert json.loads(out.read_bytes())["controller"]["no_interface_statement"] == flagged
    written = json.loads(record_path(out).read_text())
    assert all(written["law_timing"][k]["held_against"] is None for k in flagged)
    assert written["law_timing"]["sensor_delay"]["writers"] == ["control"]


def test_a_delay_quantity_held_only_by_control_is_no_statement_and_is_flagged(
    tmp_path: Path,
) -> None:
    # The interface holds the rate but not the two bounds the file names for the compute delay.
    light = {"firmware.timing": {"output_data_rate": (208, "Hz"), "update_rate": (100, "Hz")}}
    record, _, _, _ = _export(tmp_path, interface=light)
    assert record.status == "exported"
    assert record.law_timing["compute_delay"]["no_interface_statement"] is True
    assert record.law_timing["sensor_delay"]["no_interface_statement"] is False


def test_two_nodes_that_disagree_on_a_coefficient_the_law_reads_are_ambiguous(
    tmp_path: Path,
) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    run = _run(tmp_path, commit, settings={**SETTINGS, "k_u": (-0.3, "1")})
    out = _out(tmp_path)
    record = export_whole_run(run, out, repository=repo)
    assert record.status == "ambiguous"
    assert "k_u" in record.conflicts
    _nothing_written(out)


def test_a_commit_the_repository_does_not_hold_is_an_export_error(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path, _LAW.read_bytes())
    run = _run(tmp_path, "0" * 40)
    with pytest.raises(ExportError):
        export_whole_run(run, _out(tmp_path), repository=repo)


def test_a_run_that_did_not_finish_is_unfinished_before_any_file_is_read(tmp_path: Path) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    run = _run(tmp_path, commit)
    lines = (run / "events.jsonl").read_bytes().splitlines(keepends=True)
    (run / "events.jsonl").write_bytes(b"".join(lines[:10]))
    assert export_whole_run(run, _out(tmp_path), repository=repo).status == "unfinished"


def test_a_vector_start_is_the_memory_each_vector_names_and_zero_for_any_it_leaves_out(
    tmp_path: Path,
) -> None:
    document = copy.deepcopy(_file())
    document["vectors"][1]["start"].pop("u_prev")
    record, _, _, _ = _export(tmp_path, _bytes(document))
    assert record.status == "exported"


def test_the_commit_read_is_the_last_of_the_merges_the_log_records(tmp_path: Path) -> None:
    import re

    broken = _bytes({**_file(), "form": "other"})
    repo, commits = _repo(tmp_path, broken, broken, broken, _LAW.read_bytes())
    run = _run(tmp_path, commits[3])
    log = (run / "events.jsonl").read_text()
    merges = re.findall(r'"merge_commit":"([0-9a-f]{40})"', log)
    assert len(merges) == 4 and merges[3] == commits[3]
    for fake, real in zip(merges[:3], commits[:3], strict=True):
        log = log.replace(fake, real)
    (run / "events.jsonl").write_text(log)
    record = export_whole_run(run, _out(tmp_path), repository=repo)
    assert record.status == "exported"
    assert record.law_commit == commits[3]


def test_the_law_file_is_the_control_module_s_and_no_other_module_s(tmp_path: Path) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    (repo / "modules" / "z0").mkdir(parents=True)
    (repo / "modules" / "z0" / "law.json").write_bytes(b"{")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "other module")
    commit = _git(repo, "rev-parse", "HEAD")
    run = _run(tmp_path, commit)
    record = export_whole_run(run, _out(tmp_path), repository=repo)
    assert record.status == "exported"
    assert record.law_path == f"{_MODULE}/law.json"
