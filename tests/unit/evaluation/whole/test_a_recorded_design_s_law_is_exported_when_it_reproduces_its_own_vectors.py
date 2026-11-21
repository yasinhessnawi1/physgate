"""A control module's law file is exported as the controller only if it reproduces its vectors.

The graph is built here through the store's own writer, as the export's other rows build one,
and the law file is committed in a throwaway repository whose last commit the run's event log
names as its last merge. The law is a recorded design's: its coefficients on one node, a leaky
tilt estimate, the previous encoder angle and the previous command as memory, the test vectors
its design note states (the rows where the speed command is zero: the others exercise the
feed-forward and the reference's ramp, which the loop's analysis holds outside the law).

Each refusal is a status of its own and writes nothing: no file, units that do not balance, a
coefficient the graph does not hold (a leak named differently among them), a vector the law does
not reproduce, a law that is not linear or reads a signal outside the list.
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


def _node(node_id: str, values: Values, owner: str, domain: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "module",
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
        tmp_path, commit, **{k: v for k, v in kwargs.items() if k in ("coefficients", "settings")}
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
    assert record.supplied == ("gyro_full_scale",)
    assert json.loads(out.read_bytes())["parameters"]["gyro_full_scale"] == {
        "value": 1000,
        "unit": "deg/s",
    }
    assert json.loads(record_path(out).read_text())["supplied"] == ["gyro_full_scale"]


def test_a_supplied_setting_the_graph_already_holds_or_that_is_no_setting_is_an_error(
    tmp_path: Path,
) -> None:
    repo, (commit,) = _repo(tmp_path, _LAW.read_bytes())
    run = _run(tmp_path, commit)
    for name in ("gyro_full_scale", "not_a_setting"):
        with pytest.raises(ExportError):
            export_whole_run(run, _out(tmp_path), repository=repo, supplied={name: (1000, "deg/s")})


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
