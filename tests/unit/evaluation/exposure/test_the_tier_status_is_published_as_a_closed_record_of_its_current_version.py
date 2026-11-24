"""Each role's current tier version, published for the Evidence page as a closed record.

The page's server reads none of the places a version's facts come from: the check record lies in
the role's root, the register beneath its withheld root. So a person publishes them at a terminal
(``physgate tiers status --store S --publish DIR``), from the command's own reader. The record a
role gets is closed: its current version's id (the one fresh version), the three tiers' task
counts, the blind check's counts and where its answer came from, an exposure word, the version's
state, whether a measured run names it, and when it was read; or, where the current version
cannot be told, a closed word saying why. Nothing else: no task id, brief, canary, path, digest
but the version id, sentence of an error or number from a run. Its parser refuses anything its
writer could not have written.

The fixture store is the baseline round's stand-in, every task's id and specification carrying a
marker of its own, and the store's own path a marker too, so what of them reached a file is
found by a plain search.
"""

from __future__ import annotations

import errno
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from exposure_fixtures import StandInStore, api, second_version, stand_in_store

from physgate.cli import main
from physgate.evaluation.gaps import published as gap_publication
from physgate.evaluation.tiers.manifest import read_version
from physgate.evaluation.tiers.task import id_digest

MODULE = "physgate.evaluation.tiers.published"
PUBLISH = f"{MODULE}.publish_status"
PARSE = f"{MODULE}.read_published_status"
NAME = f"{MODULE}.published_name"
EXPOSURE = "physgate.evaluation.tiers.exposure"
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
ROLES = ("control", "firmware")
#: A marker in the store's own path, so a path that reached a file is found by a plain search.
STORE_MARK = "zqstoremarkzq"
#: The words a publication may hold, written here apart from the module's own lists.
WORDS = frozenset(
    {
        *ROLES,
        "check",
        "imported",
        "none",
        "exposed",
        "exposed_unchecked",
        "fresh",
        "stale",
        "store_unreadable",
        "register_unreadable",
        "version_refused",
        "no_fresh_version",
        "fresh_versions_several",
        "publish_failed",
        "check_record_changed",
        "check_record_invalid",
        "check_record_not_the_version",
        "check_record_unreadable",
        "check_record_unsynced",
        "check_record_unwritten",
    }
)
#: The exact key set of each shape, at every depth.
READ_KEYS = {
    "role",
    "read_at",
    "version",
    "counts",
    "check",
    "exposure",
    "version_state",
    "measured",
}
REFUSED_KEYS = {"role", "read_at", "refused"}
COUNT_KEYS = {"visible", "validation", "held_out"}
CHECK_KEYS = {"tasks", "all_yes", "left_out", "source"}
HEX64 = re.compile(r"[0-9a-f]{64}")


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    """A marked store of one checked version whose check flagged one held-out task."""
    return stand_in_store(tmp_path / STORE_MARK, marked=True, flagged=(0,))


@pytest.fixture(autouse=True)
def places(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The places the harness knows of, as folders of the row's own.

    The rows' folders lie in the machine's shared temporary directory, where a publication is
    refused.
    """
    known = SimpleNamespace(
        harness=tmp_path / "code" / "harness",
        review_root=tmp_path / "home" / "review-scratch",
        shared_temps=(tmp_path / "shared-tmp",),
    )
    monkeypatch.setattr(gap_publication, "known_places", lambda: known)
    return known


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "context", {}).get("refused_because", type(exc).__name__))


def _out(tmp_path: Path, name: str = "tier-status") -> Path:
    out = tmp_path / name
    out.mkdir()
    return out


def _publish(made: StandInStore, out: Path) -> dict[str, dict[str, Any]]:
    """Publish into ``out``; each role's file as written, by role."""
    api(PUBLISH)(made.store, out=out, now=NOW)
    return {role: json.loads((out / api(NAME)(role)).read_bytes()) for role in ROLES}


def _leaves(value: Any, at: str = "") -> list[tuple[str, Any]]:  # noqa: ANN401
    """Every leaf of a JSON value, with where it lies."""
    if isinstance(value, dict):
        return [leaf for key, item in value.items() for leaf in _leaves(item, f"{at}.{key}")]
    if isinstance(value, list):
        return [leaf for i, item in enumerate(value) for leaf in _leaves(item, f"{at}[{i}]")]
    return [(at, value)]


def _digests(made: StandInStore) -> dict[str, str]:
    """Every digest the fixture's version and its check carry, but the version id."""
    manifest = read_version(made.store / "control" / made.version)
    found = {f"{tier}.sha256": manifest.tier(tier).sha256 for tier in ("visible", "validation")}
    found["held_out.sha256"] = manifest.held_out.sha256
    found["validation.canaries"] = str(manifest.validation.canaries_sha256)
    found["held_out.canaries"] = str(manifest.held_out.canaries_sha256)
    found["brief"] = manifest.brief_sha256
    found["requirements"] = manifest.requirements_sha256
    found["provenance"] = manifest.provenance_sha256
    check = json.loads((made.store / "control" / f"{made.version}.check.json").read_bytes())
    found["check"] = check["sha256"]
    found["answer"] = check["answer_sha256"]
    found["flagged"] = id_digest(made.tasks["held_out"][0].id)
    return found


def test_a_role_s_one_fresh_version_is_published_with_its_counts_check_and_state(
    tmp_path: Path, made: StandInStore
) -> None:
    out = _out(tmp_path)
    published = _publish(made, out)
    assert published["control"] == {
        "role": "control",
        "read_at": NOW.isoformat().replace("+00:00", "Z"),
        "version": made.version,
        "counts": {"visible": 8, "validation": 8, "held_out": 8},
        "check": {"tasks": 8, "all_yes": 7, "left_out": 1, "source": "check"},
        "exposure": "none",
        "version_state": "fresh",
        "measured": False,
    }
    # The firmware role holds no version: none is fresh, said by its word alone.
    assert published["firmware"] == {
        "role": "firmware",
        "read_at": published["control"]["read_at"],
        "refused": "no_fresh_version",
    }
    assert sorted(os.listdir(out)) == [api(NAME)(role) for role in ROLES]


def test_every_leaf_of_a_publication_is_a_closed_word_a_count_a_flag_the_version_or_its_time(
    tmp_path: Path, made: StandInStore
) -> None:
    published = _publish(made, _out(tmp_path))
    read_at = published["control"]["read_at"]
    for role, record in published.items():
        leaves = _leaves(record)
        assert leaves, role
        for at, value in leaves:
            if value is None or isinstance(value, bool | int):
                continue
            assert isinstance(value, str), (role, at, value)
            allowed = value in WORDS or (at == ".version" and value == made.version)
            allowed = allowed or (at == ".read_at" and value == read_at)
            assert allowed, f"the {role} publication holds a free string at {at}: {value!r}"


def test_no_task_id_brief_canary_or_path_reaches_a_publication_or_the_command_s_line(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _out(tmp_path)
    assert main(["tiers", "status", "--store", str(made.store), "--publish", str(out)]) == 1
    said = capsys.readouterr().out
    written = b"".join((out / name).read_bytes() for name in sorted(os.listdir(out))).decode()
    ids = [task.id for tier in made.tasks.values() for task in tier]
    assert ids and all("zqmark" in i for i in ids), "the row needs tasks that carry a marker"
    assert made.canaries, "the row needs a version with canaries"
    for text, where in ((written, "a publication"), (said, "the command's line")):
        assert "zqmark" not in text, f"{where} holds a task's id or specification"
        assert "Stabilise plant" not in text, f"{where} holds a task's brief"
        for canary in made.canaries:
            assert canary not in text, f"{where} holds a canary"
        for place in (STORE_MARK, str(made.store), str(tmp_path), "withheld", "/"):
            assert place not in text.replace("\\/", ""), f"{where} holds a path: {place}"


def test_no_digest_reaches_a_publication_but_the_version_id(
    tmp_path: Path, made: StandInStore
) -> None:
    out = _out(tmp_path)
    _publish(made, out)
    written = b"".join((out / name).read_bytes() for name in sorted(os.listdir(out))).decode()
    assert set(HEX64.findall(written)) == {made.version}
    for what, digest in _digests(made).items():
        assert digest not in written, f"the publication holds the {what} digest"


def test_each_shape_holds_its_exact_keys_at_every_depth(tmp_path: Path, made: StandInStore) -> None:
    published = _publish(made, _out(tmp_path))
    read, refused = published["control"], published["firmware"]
    assert set(read) == READ_KEYS
    assert set(read["counts"]) == COUNT_KEYS
    assert set(read["check"]) == CHECK_KEYS
    assert set(refused) == REFUSED_KEYS


def test_a_version_with_no_check_is_published_as_unchecked_and_a_refused_record_by_its_word(
    tmp_path: Path,
) -> None:
    unchecked = stand_in_store(tmp_path / "u", checked=False)
    assert _publish(unchecked, _out(tmp_path, "u-out"))["control"]["check"] is None
    made = stand_in_store(tmp_path / "c")
    record = made.store / "control" / f"{made.version}.check.json"
    body = json.loads(record.read_bytes())
    body["all_yes"] = body["all_yes"] - 1
    record.write_text(json.dumps(body))
    check = _publish(made, _out(tmp_path, "c-out"))["control"]["check"]
    assert check == {"refused": "check_record_changed"}, check


def test_a_measured_run_on_the_version_is_said_as_one_bit_and_a_probe_is_not_one(
    tmp_path: Path, made: StandInStore
) -> None:
    record = api(f"{EXPOSURE}.record_measurement")
    record(made.store, "control", made.version, measured="probe", key="e" * 64)
    assert _publish(made, _out(tmp_path, "probed"))["control"]["measured"] is False
    record(made.store, "control", made.version, measured="gaps", key="f" * 64)
    published = _publish(made, _out(tmp_path, "measured"))["control"]
    assert published["measured"] is True
    assert "e" * 64 not in json.dumps(published) and "f" * 64 not in json.dumps(published)


def _refused_as(made: StandInStore, tmp_path: Path, name: str) -> dict[str, Any]:
    control = _publish(made, _out(tmp_path, name))["control"]
    assert set(control) == REFUSED_KEYS, control
    return control


def test_two_fresh_versions_are_refused_and_neither_is_chosen(
    tmp_path: Path, made: StandInStore
) -> None:
    second = second_version(made)
    control = _refused_as(made, tmp_path, "two")
    assert control["refused"] == "fresh_versions_several"
    assert made.version not in json.dumps(control) and second.version not in json.dumps(control)


def test_no_fresh_version_is_refused_when_the_one_version_is_exposed(
    tmp_path: Path, made: StandInStore
) -> None:
    api(f"{EXPOSURE}.mark_exposed")(
        made.store, "control", made.version, by="a person", reason="read the held-out by hand"
    )
    control = _refused_as(made, tmp_path, "exposed")
    assert control["refused"] == "no_fresh_version"


def test_no_fresh_version_is_refused_when_the_question_has_changed(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.tiers import authoring

    monkeypatch.setattr(authoring, "AUTHOR_BRIEF", authoring.AUTHOR_BRIEF + "\nOne more rule.\n")
    assert _refused_as(made, tmp_path, "changed")["refused"] == "no_fresh_version"


def test_a_version_its_manifest_does_not_hold_to_refuses_the_role(
    tmp_path: Path, made: StandInStore
) -> None:
    task = sorted((made.store / "control" / made.version / "visible").iterdir())[0]
    (task / "task.json").write_bytes((task / "task.json").read_bytes() + b" ")
    assert _refused_as(made, tmp_path, "changed")["refused"] == "version_refused"


def test_a_register_that_cannot_be_read_refuses_the_role_by_its_word(
    tmp_path: Path, made: StandInStore
) -> None:
    register = made.store / "control" / "withheld" / "register.jsonl"
    register.write_bytes(register.read_bytes() + b'{"cut')
    assert _refused_as(made, tmp_path, "register")["refused"] == "register_unreadable"


def test_a_store_that_cannot_be_read_refuses_every_role_by_its_word(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation import tierset_cli

    def unreadable(store: Path) -> object:
        raise OSError(errno.EACCES, f"cannot list {store}")

    monkeypatch.setattr(tierset_cli, "status", unreadable)
    published = _publish(made, _out(tmp_path))
    assert {role: record["refused"] for role, record in published.items()} == {
        role: "store_unreadable" for role in ROLES
    }
    assert STORE_MARK not in json.dumps(published)


def test_a_failure_after_the_folder_is_judged_replaces_the_copy_with_its_word(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _out(tmp_path)
    assert _publish(made, out)["control"].get("version") == made.version
    from physgate.evaluation.tiers import exposure

    def broken(store: Path, role: str) -> object:
        raise RuntimeError(f"broke reading {store}")

    monkeypatch.setattr(exposure, "measurements", broken)
    control = _publish(made, out)["control"]
    assert control == {
        "role": "control",
        "read_at": control["read_at"],
        "refused": "publish_failed",
    }
    assert sorted(os.listdir(out)) == [api(NAME)(role) for role in ROLES]


def test_the_status_is_published_by_a_person_never_inside_a_session(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _out(tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path / "session-tmp"))
    with pytest.raises(Exception) as caught:
        api(PUBLISH)(made.store, out=out, now=NOW)
    assert _reason(caught.value) == "inside_a_session", caught.value
    assert os.listdir(out) == []


@pytest.mark.parametrize("where", ["in-the-store", "holding-the-store", "a-link", "a-run"])
def test_the_status_is_written_only_to_a_folder_the_gap_trend_s_judgement_allows(
    tmp_path: Path, made: StandInStore, where: str
) -> None:
    folder = _out(tmp_path)
    out = {
        "in-the-store": made.store / "control",
        "holding-the-store": made.store.parent,
        "a-link": tmp_path / "link",
        "a-run": tmp_path / "runs" / "run-1",
    }[where]
    if where == "a-link":
        out.symlink_to(folder, target_is_directory=True)
    if where == "a-run":
        out.mkdir(parents=True)
        (out / "run.json").write_text("{}")
    with pytest.raises(Exception) as caught:
        api(PUBLISH)(made.store, out=out, now=NOW)
    assert _reason(caught.value) == "publish_refused", caught.value
    assert "given no run" in str(caught.value)
    assert [p for p in tmp_path.rglob("tier-status-*")] == []


def test_the_status_is_not_published_into_the_gap_trend_s_folder(
    tmp_path: Path, made: StandInStore
) -> None:
    out = _out(tmp_path)
    (out / gap_publication.published_name("control")).write_text("{}")
    with pytest.raises(Exception) as caught:
        api(PUBLISH)(made.store, out=out, now=NOW)
    assert _reason(caught.value) == "publish_refused", caught.value
    assert "gap trend" in str(caught.value)
    assert [p.name for p in out.iterdir()] == [gap_publication.published_name("control")]


def test_a_publication_that_cannot_be_written_removes_the_copy_before_it(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _out(tmp_path)
    _publish(made, out)

    def replace(*_: object, **__: object) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(Exception) as caught:
        api(PUBLISH)(made.store, out=out, now=NOW)
    monkeypatch.undo()
    assert _reason(caught.value) == "publish_failed", caught.value
    assert not (out / api(NAME)("control")).exists(), "an older copy is left to read as current"
    assert str(tmp_path) not in str(caught.value)


def test_its_parser_takes_what_its_writer_wrote(tmp_path: Path, made: StandInStore) -> None:
    out = _out(tmp_path)
    published = _publish(made, out)
    for role in ROLES:
        parsed = api(PARSE)((out / api(NAME)(role)).read_bytes(), role)
        assert parsed.model_dump(mode="json") == published[role]


#: A place on disk, planted as a value a writer could not have written.
PLANTED = "/srv/zqplantedzq/held_out/task.json"


def _edited(read: dict[str, Any], refused: dict[str, Any], how: str) -> bytes:
    """A publication edited ``how``: a file its writer could not have written."""
    body = json.loads(json.dumps(read))
    if how == "cut":
        return json.dumps(body).encode()[:-9]
    if how == "not-json":
        return b"\x00not json at all"
    if how == "too-large":
        return json.dumps(body).encode() + b" " * (8 * 1024)
    if how == "an-extra-key":
        body["store"] = PLANTED
    elif how == "an-extra-key-inside":
        body["counts"]["path"] = PLANTED
    elif how == "a-string-for-a-count":
        body["counts"]["held_out"] = "8"
    elif how == "a-count-for-a-flag":
        body["measured"] = 1
    elif how == "a-flag-for-a-count":
        body["counts"]["visible"] = True
    elif how == "a-free-word":
        body["exposure"] = PLANTED
    elif how == "a-version-that-is-no-id":
        body["version"] = PLANTED
    elif how == "a-broken-count":
        body["check"]["left_out"] = 2
    elif how == "exposed-yet-fresh":
        body["exposure"] = "exposed"
    elif how == "both-shapes":
        body["refused"] = "no_fresh_version"
    elif how == "a-refusal-with-a-sentence":
        return json.dumps({**refused, "error": PLANTED}).encode()
    elif how == "a-refusal-of-a-free-word":
        return json.dumps({**refused, "refused": PLANTED}).encode()
    return json.dumps(body).encode()


EDITS = [
    "cut",
    "not-json",
    "too-large",
    "an-extra-key",
    "an-extra-key-inside",
    "a-string-for-a-count",
    "a-count-for-a-flag",
    "a-flag-for-a-count",
    "a-free-word",
    "a-version-that-is-no-id",
    "a-broken-count",
    "exposed-yet-fresh",
    "both-shapes",
    "a-refusal-with-a-sentence",
    "a-refusal-of-a-free-word",
]


@pytest.mark.parametrize("how", EDITS)
def test_its_parser_refuses_what_its_writer_could_not_have_written_and_repeats_none_of_it(
    tmp_path: Path, made: StandInStore, how: str
) -> None:
    published = _publish(made, _out(tmp_path))
    data = _edited(published["control"], published["firmware"], how)
    role = "firmware" if how.startswith("a-refusal") else "control"
    with pytest.raises(Exception) as caught:
        api(PARSE)(data, role)
    assert _reason(caught.value) == "publication_unreadable", caught.value
    assert "zqplanted" not in str(caught.value) and "/" not in str(caught.value), caught.value


def test_its_parser_refuses_another_role_s_publication(tmp_path: Path, made: StandInStore) -> None:
    out = _out(tmp_path)
    _publish(made, out)
    with pytest.raises(Exception) as caught:
        api(PARSE)((out / api(NAME)("control")).read_bytes(), "firmware")
    assert _reason(caught.value) == "publication_unreadable", caught.value
    assert "another role's" in str(caught.value)


def test_the_command_writes_only_when_asked_and_prints_what_it_published(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _out(tmp_path)
    argv = ["tiers", "status", "--store", str(made.store)]
    main(argv)
    capsys.readouterr()
    assert os.listdir(out) == [], "the command wrote without --publish"
    main([*argv, "--publish", str(out)])
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {"published"}
    written = {role: json.loads((out / api(NAME)(role)).read_bytes()) for role in ROLES}
    assert printed["published"] == [written[role] for role in ROLES]


def test_the_command_s_help_says_which_folder_to_publish_into_and_what_it_cannot_know(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["tiers", "status", "--help"])
    said = " ".join(capsys.readouterr().out.split())
    assert "given no run" in said, said
    assert "not the gap trend's" in said, said
    assert "physgate ui --root" in said, said
