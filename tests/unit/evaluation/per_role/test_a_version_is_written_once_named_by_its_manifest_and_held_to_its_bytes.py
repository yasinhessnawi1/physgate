"""A version is written once, named by its manifest, and held to its bytes by every reader.

The split writes a round's three tiers into a temporary directory beside the versions, with
their provenance record and manifest, and renames it to the manifest's id last. The id is the
digest of the manifest without the id; the manifest names no task; a reader recomputes every
digest, count and list digest from disk and refuses a version that is not what its manifest
says. A version is never written again, and the pool it was drawn from is gone after it.
"""

from __future__ import annotations

import hashlib
import importlib
import itertools
import json
import os
import secrets
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.tiers import authoring
from physgate.evaluation.tiers.authoring import AuthoringError
from physgate.evaluation.tiers.task import canonical_json

PROVENANCE = canonical_json({"sessions": [{"session_id": "s-1", "end": "ended"}]})


def _api(name: str) -> Any:
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


def _pool(root: Path, count: int = 24) -> Path:
    pool = root / "control" / "withheld" / "pool"
    for i in range(count):
        write_task_dir(
            pool / f"control.t{i:02d}",
            own_task(id=f"control.t{i:02d}"),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    return pool


def _write(store: Path, pool: Path, **kw: Any) -> tuple[Any, dict[str, Any]]:
    write_version = _api("physgate.evaluation.tiers.store.write_version")
    chosen = sorted(p for p in pool.iterdir() if p.is_dir())[:24]
    args: dict[str, Any] = {
        "role": "control",
        "seed": 5,
        "model": "claude-sonnet-5",
        "runtime": "2.1.301",
        "provenance": PROVENANCE,
        "retire": pool,
        "generated": "2026-11-08",
    }
    args.update(kw)
    result: tuple[Any, dict[str, Any]] = write_version(store / "control", chosen, **args)
    return result


def _version(tmp_path: Path) -> tuple[Path, Any]:
    store = tmp_path.resolve() / "store"
    manifest, _ = _write(store, _pool(store))
    return store / "control" / manifest.version, manifest


def test_a_split_writes_one_version_whole_under_its_id_and_its_manifest_names_no_task(
    tmp_path: Path,
) -> None:
    store = tmp_path.resolve() / "store"
    pool = _pool(store)
    ids = sorted(p.name for p in pool.iterdir())
    manifest, placed = _write(store, pool)
    version = store / "control" / manifest.version
    assert sorted(p.name for p in version.iterdir()) == [
        "held_out",
        "provenance.json",
        "tierset.json",
        "validation",
        "visible",
    ]
    assert sorted(p.name for p in (store / "control").iterdir()) == sorted(
        [manifest.version, "withheld", "work"]
    )
    assert list((store / "control" / "withheld").iterdir()) == []
    assert [manifest.tier(t).count for t in ("visible", "validation", "held_out")] == [8, 8, 8]
    assert manifest.visible.canaries_sha256 is None
    assert (
        manifest.held_out.canaries_sha256
        == hashlib.sha256((version / "held_out" / "canaries.json").read_bytes()).hexdigest()
    )
    assert manifest.held_out.sha256 == placed["held_out_sha256"]
    assert (manifest.model, manifest.seed, manifest.runtime) == ("claude-sonnet-5", 5, "2.1.301")
    assert manifest.provenance_sha256 == hashlib.sha256(PROVENANCE).hexdigest()
    assert (version / "provenance.json").read_bytes() == PROVENANCE
    text = (version / "tierset.json").read_text()
    assert not [task_id for task_id in ids if task_id in text]
    read_version = _api("physgate.evaluation.tiers.manifest.read_version")
    assert read_version(version) == manifest


def test_the_version_id_is_the_digest_of_the_manifest_without_its_id(tmp_path: Path) -> None:
    version, manifest = _version(tmp_path)
    stated = json.loads((version / "tierset.json").read_text())
    without = {key: value for key, value in stated.items() if key != "version"}
    assert stated["version"] == manifest.version == version.name
    assert manifest.version == hashlib.sha256(canonical_json(without)).hexdigest()


def test_the_id_leaves_out_the_id_field_and_nothing_else() -> None:
    version_id = _api("physgate.evaluation.tiers.manifest.version_id")
    fields = {"role": "control", "seed": 5}
    assert version_id({**fields, "version": "0" * 64}) == version_id(fields)
    assert version_id({**fields, "seed": 6}) != version_id(fields)


@pytest.mark.parametrize(
    "change",
    [
        {"held_out_ids": ["control.t00"]},
        {"visible": {"sha256": "0" * 64, "count": 8, "ids": ["control.t00"]}},
        {"version": "0" * 64},
    ],
    ids=["a held-out id beside the tiers", "an id inside a tier's record", "an id not its digest"],
)
def test_a_manifest_naming_a_task_or_misnaming_itself_is_refused_by_its_schema(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    from pydantic import ValidationError

    version, _ = _version(tmp_path)
    stated = {**json.loads((version / "tierset.json").read_text()), **change}
    with pytest.raises(ValidationError):
        _api("physgate.evaluation.tiers.manifest.TierSet").model_validate_json(json.dumps(stated))


def test_a_manifest_made_with_a_task_id_is_refused_whatever_its_id_says(tmp_path: Path) -> None:
    version, manifest = _version(tmp_path)
    fields = {
        **manifest.model_dump(mode="json", exclude={"format", "version"}),
        "held_out_ids": ["control.t00"],
    }
    error = _api("physgate.evaluation.tiers.manifest.TierSetError")
    with pytest.raises(error) as refused:
        _api("physgate.evaluation.tiers.manifest.make_tierset")(**fields)
    assert refused.value.context.get("refused_because") == "manifest_invalid"


def _refused(version: Path) -> str:
    read_version = _api("physgate.evaluation.tiers.manifest.read_version")
    error = _api("physgate.evaluation.tiers.manifest.TierSetError")
    try:
        read_version(version)
    except error as exc:
        return str(exc.context.get("refused_because"))
    pytest.fail("the version was taken to be what its manifest says")


@pytest.mark.parametrize("tier", ["visible", "validation", "held_out"])
def test_a_changed_task_under_an_unchanged_manifest_refuses_the_version(
    tmp_path: Path, tier: str
) -> None:
    version, _ = _version(tmp_path)
    task = sorted(p for p in (version / tier).iterdir() if p.is_dir())[0]
    (task / "references" / "good" / "answer.json").write_text(json.dumps(controller(num=[])))
    if tier != "visible":
        # The tier made consistent with itself: only the manifest's digest still differs.
        (version / tier / "SHA256SUMS").write_text(authoring.sha256sums(version / tier))
    assert _refused(version) == "tier_changed"


def test_a_changed_canary_list_refuses_the_version(tmp_path: Path) -> None:
    version, _ = _version(tmp_path)
    listed = json.loads((version / "held_out" / "canaries.json").read_text())
    (version / "held_out" / "canaries.json").write_text(json.dumps(sorted(listed)[1:]) + "\n")
    assert _refused(version) == "canary_list_changed"


def test_a_task_gone_from_a_tier_and_its_digest_refuses_the_version(tmp_path: Path) -> None:
    import shutil

    version, _ = _version(tmp_path)
    shutil.rmtree(sorted(p for p in (version / "visible").iterdir())[0])
    assert _refused(version) in {"tier_changed", "tier_count_changed"}


def test_a_version_under_another_name_refuses(tmp_path: Path) -> None:
    version, _ = _version(tmp_path)
    renamed = version.with_name("f" * 64)
    version.rename(renamed)
    assert _refused(renamed) == "version_misnamed"


def test_a_changed_provenance_record_refuses_the_version(tmp_path: Path) -> None:
    version, _ = _version(tmp_path)
    (version / "provenance.json").write_bytes(canonical_json({"sessions": []}))
    assert _refused(version) == "provenance_changed"


def test_a_version_holding_anything_more_refuses(tmp_path: Path) -> None:
    version, _ = _version(tmp_path)
    (version / "notes.txt").write_text("a person's note")
    assert _refused(version) == "version_holds_other"


def _deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every secret drawn from a counter that starts again on each call of this."""
    counter = itertools.count()
    monkeypatch.setattr(
        secrets,
        "token_hex",
        lambda n: hashlib.sha256(str(next(counter)).encode()).hexdigest()[: 2 * n],
    )


def test_a_version_that_exists_is_never_written_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path.resolve() / "store"
    _deterministic(monkeypatch)
    first, _ = _write(store, _pool(store))
    version = store / "control" / first.version
    before = {p.relative_to(version): p.read_bytes() for p in version.rglob("*") if p.is_file()}
    # The same pool, seed and secrets, so the same tiers and the same manifest: the same id.
    _deterministic(monkeypatch)
    with pytest.raises(AuthoringError) as refused:
        _write(store, _pool(store))
    assert refused.value.context.get("refused_because") == "version_exists"
    after = {p.relative_to(version): p.read_bytes() for p in version.rglob("*") if p.is_file()}
    assert after == before
    assert not [p for p in (store / "control").iterdir() if p.name.startswith(".version-")]


def test_the_pool_is_marked_spent_before_the_rename_and_gone_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path.resolve() / "store"
    pool = _pool(store, count=26)
    renames: list[tuple[str, str]] = []
    real = os.rename

    def watched(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        if not kwargs:  # a file written whole is renamed under its directory's descriptor
            renames.append((Path(src).name, Path(dst).name))
        real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", watched)
    manifest, _ = _write(store, pool)
    assert ("pool", "pool.spent") in renames
    moved = [n for n, (src, _) in enumerate(renames) if src.startswith(".version-")]
    assert len(moved) == 1 and renames[moved[0]][1] == manifest.version
    assert renames.index(("pool", "pool.spent")) < moved[0]
    # The pool is gone with the two tasks the draw did not take.
    assert sorted(p.name for p in (store / "control").iterdir()) == sorted(
        [manifest.version, "withheld", "work"]
    )
    assert list((store / "control" / "withheld").iterdir()) == []


def test_a_split_that_fails_leaves_no_version_and_the_pool_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path.resolve() / "store"
    pool = _pool(store)
    store_module = _api("physgate.evaluation.tiers.store")

    def half_a_split(
        staging: Path, visible: Path, held_out: Path, *, validation: Path, seed: int
    ) -> Any:
        visible.mkdir(parents=True)
        held_out.mkdir(parents=True)
        raise OSError("the disk filled part-way")

    monkeypatch.setattr(store_module, "split", half_a_split)
    with pytest.raises(OSError, match="part-way"):
        _write(store, pool)
    assert sorted(p.name for p in (store / "control").iterdir()) == ["withheld", "work"]
    assert len([p for p in pool.iterdir() if p.is_dir()]) == 24
