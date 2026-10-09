"""The paired run issues the control fixture verbatim, under the bounds it was sized for.

The control subtask's specification is the frozen fixture beside the driver, held to its
sha256; the decomposition brief carries it between its markers byte for byte, with the first
run's firmware stand-in and interface node unchanged; the run's parameters set 40 turns and
4500 s. Its acceptance criteria are numbered, so a review of it is held to exactly that many
criterion lines. The node its section 10 asks for, filled with placeholders, is a valid node.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import real_domain_roles as base
import real_paired_reviewers as paired

from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.contract import issued_criteria
from physgate.state.schema import validate_node

FROZEN = "f2a7080355c587a6925c992fdcb377ae20ba3458f6dc41f4d07143c3be16bf88"
#: What ``use_fixture`` points the first run's driver at, restored after each test that calls it.
POINTED = ("CONTROL_SPEC", "BRIEF", "params", "FIRMWARE_PROPOSAL", "FIRMWARE_SPEC", "INTERFACE")


def test_the_fixture_is_the_frozen_one() -> None:
    data = paired.CONTROL_FIXTURE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == FROZEN == paired.CONTROL_FIXTURE_SHA256
    assert len(data) == 22_285
    assert paired.control_fixture_spec().encode() == data


def test_a_changed_fixture_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    changed = tmp_path / "control_fixture_spec.md"
    changed.write_bytes(paired.CONTROL_FIXTURE.read_bytes() + b"\n")
    monkeypatch.setattr(paired, "CONTROL_FIXTURE", changed)
    with pytest.raises(SystemExit, match="not the frozen one"):
        paired.control_fixture_spec()


def test_the_brief_embeds_it_verbatim_beside_the_unchanged_stand_ins() -> None:
    spec = paired.control_fixture_spec()
    brief = paired.brief(spec)
    control = brief.split("<<<\n", 1)[1].split(">>>\n", 1)[0]
    assert control == spec
    firmware = brief.split("<<<\n", 2)[2].split(">>>\n", 1)[0]
    assert firmware == paired.FIRMWARE_SPEC
    assert brief.endswith(json.dumps(paired.INTERFACE) + "\n")
    assert "control.loop_gain" in spec and "control first" in brief


def test_the_run_sets_the_bounds_the_fixture_was_sized_for() -> None:
    bounds = RunBounds.model_validate_json(json.dumps(paired.params()["bounds"]))
    assert (bounds.session_max_turns, bounds.session_wall_clock_s) == (80, 4500.0)
    first = RunBounds.model_validate_json(json.dumps(base.params()["bounds"]))
    changed = {"session_max_turns", "session_wall_clock_s", "infra_retry_delays_s"}
    assert bounds.model_dump(exclude=changed) == first.model_dump(exclude=changed)
    assert bounds.binary_max_retries == 0


def test_a_real_role_session_is_retried_for_infrastructure_as_designed() -> None:
    """One transient API error is retried after 60 s, a second after 300 s, then the run halts."""
    bounds = RunBounds.model_validate_json(json.dumps(paired.params()["bounds"]))
    assert bounds.infra_retry_delays_s == (60.0, 300.0)
    assert bounds.binary_max_retries == 0
    unchanged = {k: v for k, v in paired.params().items() if k != "bounds"}
    assert unchanged == {k: v for k, v in base.params().items() if k != "bounds"}


def test_pointing_the_first_run_s_driver_at_the_fixture_does_not_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in POINTED:
        monkeypatch.setattr(base, name, getattr(base, name))
    spec = paired.use_fixture()
    assert spec == base.CONTROL_SPEC and paired.brief(spec) == base.BRIEF
    assert base.params()["bounds"]["session_max_turns"] == 80
    assert base.FIRMWARE_SPEC == paired.FIRMWARE_SPEC and base.INTERFACE == paired.INTERFACE


def test_its_eleven_criteria_are_counted_for_the_review() -> None:
    assert issued_criteria(paired.control_fixture_spec()) == tuple(str(n) for n in range(1, 12))
    assert issued_criteria(base.FIRMWARE_SPEC) is None


def test_the_node_template_filled_with_placeholders_is_a_valid_node() -> None:
    node = paired.dry_node()
    validate_node(node)
    assert node["id"] == "control.loop_gain" and node["constrains"] == ["firmware.main_loop"]
    spec = paired.control_fixture_spec()
    for name, (_, unit) in paired.DRY_NODE_UNITS.items():
        assert f'"{name}": {{"unit": "{unit}", ...}}' in spec, name
    assert spec.count('{"unit": ') == len(paired.DRY_NODE_UNITS)


def test_an_inexact_copy_is_reported_with_its_diff(tmp_path: Path) -> None:
    repo = tmp_path / "target"
    branch = f"physgate/{base.RUN_ID}/run"
    spec = paired.control_fixture_spec()
    for text, exact in ((spec, True), (spec.replace("Balboa 32U4", "Balboa  32U4", 1), False)):
        if repo.exists():
            shutil.rmtree(repo)
        path = repo / ".physgate" / "specs" / f"{base.CONTROL_ID}.md"
        path.parent.mkdir(parents=True)
        path.write_text(text)
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "init", "-q", "-b", branch], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "issued"], check=True)
        found = paired.issued_control_spec(repo)
        assert found["is_the_fixture"] is exact
        assert (found["diff"] is None) is exact
        if not exact:
            assert (
                "-# Control module specification: balance loop for the Pololu Balboa 32U4"
                in (found["diff"])
            )


def test_the_pre_flight_offers_control_the_schema_of_its_eleven_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in POINTED:
        monkeypatch.setattr(base, name, getattr(base, name))
    paired.use_fixture()
    criteria, schema = paired.preflight_schema("control")
    lines = schema["properties"]["review"]["properties"]["acceptance_criteria"]
    assert criteria == tuple(str(n) for n in range(1, 12))
    assert lines["minItems"] == lines["maxItems"] == 11
    assert paired.preflight_schema("firmware")[0] is None


def test_the_stand_in_s_geometry_hash_has_its_64_digits_here_and_only_here() -> None:
    digits = paired.GEOMETRY_HASH.removeprefix("sha256:")
    assert len(digits) == 64 and set(digits) == {"0"}
    for node in (paired.FIRMWARE_PROPOSAL, paired.INTERFACE):
        assert node["geometry_hash"] == paired.GEOMETRY_HASH
    assert json.dumps(paired.FIRMWARE_PROPOSAL) in paired.FIRMWARE_SPEC
    # The first run's own driver is untouched: its stand-in keeps the defect it ran with.
    assert len(base.FIRMWARE_PROPOSAL["geometry_hash"].removeprefix("sha256:")) == 61
    assert len(base.INTERFACE["geometry_hash"].removeprefix("sha256:")) == 61
    assert paired.FIRMWARE_SPEC.replace(json.dumps(paired.FIRMWARE_PROPOSAL), "") == (
        base.FIRMWARE_SPEC.replace(json.dumps(base.FIRMWARE_PROPOSAL), "")
    )
