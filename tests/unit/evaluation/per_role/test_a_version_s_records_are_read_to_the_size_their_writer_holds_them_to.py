"""A version's records are read to the size their writer holds them to, and to no other.

A version is never written again, so its reader must take every version its writer cut. The
provenance record names every session of the round with the digest of each file of its kept
stream, and grows with the sessions a round takes: a round of twelve wrote one over a megabyte,
which the reader then refused as no record of a version. The provenance record has a limit of
its own, sized to what a round can hold; the manifest keeps its small one, since it is a
kilobyte of counts and digests. The split refuses, before it writes anything and with the pool
left whole, a record its reader would refuse, and both hold the record to one constant.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.tiers.authoring import AuthoringError
from physgate.evaluation.tiers.task import canonical_json

#: A round as the first real one left it: twelve sessions, each noting a few hundred files.
SESSIONS = 12
FILES_PER_SESSION = 740


def _api(name: str) -> Any:
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


def _round_provenance(sessions: int = SESSIONS, files: int = FILES_PER_SESSION) -> bytes:
    """A provenance record as the author writes it: each session, every kept file's digest."""
    notes = []
    for s in range(sessions):
        session_id = f"{s:08d}-0000-4000-8000-000000000000"
        kept = {
            f"config/file-history/{session_id}/{n:016x}@v{n % 5 + 1}": hashlib.sha256(
                f"{s}/{n}".encode()
            ).hexdigest()
            for n in range(files)
        }
        notes.append(
            {
                "session_id": session_id,
                "end": "budget_exhausted",
                "tokens": 8_000_000,
                "cap": 8_000_000,
                "wall_clock_s": 1100.0,
                "held_out_seen": False,
                "files": kept,
                "turns": "not recorded by the session record",
                "secret_scan": "not recorded by the session record",
            }
        )
    return canonical_json({"sessions": notes})


def _sized(size: int) -> bytes:
    """A provenance record of exactly ``size`` bytes."""
    empty = canonical_json({"pad": "", "sessions": []})
    data = canonical_json({"pad": "x" * (size - len(empty)), "sessions": []})
    assert len(data) == size
    return data


def _pool(store: Path) -> Path:
    pool = store / "control" / "withheld" / "pool"
    for i in range(24):
        write_task_dir(
            pool / f"control.t{i:02d}",
            own_task(id=f"control.t{i:02d}"),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    return pool


def _write(store: Path, provenance: bytes, *, accepted: bool = True) -> tuple[Any, Path]:
    """Split a pool of 24 into a version with ``provenance``; its manifest and directory.

    With ``accepted``, a refusal fails the row: the split takes every record its reader reads.
    """
    write_version = _api("physgate.evaluation.tiers.store.write_version")
    pool = _pool(store)
    try:
        manifest, _ = write_version(
            store / "control",
            sorted(p for p in pool.iterdir() if p.is_dir()),
            role="control",
            seed=5,
            model="claude-sonnet-5",
            runtime="2.1.301",
            provenance=provenance,
            retire=pool,
            generated="2026-11-19",
        )
    except AuthoringError as exc:
        if not accepted:
            raise
        pytest.fail(f"the split refuses a {len(provenance)}-byte provenance record: {exc}")
    return manifest, store / "control" / manifest.version


def _refusal(version: Path) -> str | None:
    """Why the reader refuses ``version``; ``None`` when it reads it."""
    read_version = _api("physgate.evaluation.tiers.manifest.read_version")
    error = _api("physgate.evaluation.tiers.manifest.TierSetError")
    try:
        read_version(version)
    except error as exc:
        return str(exc.context.get("refused_because"))
    return None


def _everything(top: Path) -> dict[str, bytes | None]:
    """Every path under ``top``, with a file's bytes and ``None`` for a directory."""
    return {
        p.relative_to(top).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(top.rglob("*"))
    }


def test_a_version_whose_provenance_is_over_a_megabyte_is_read_as_its_manifest_says(
    tmp_path: Path,
) -> None:
    provenance = _round_provenance()
    assert 1_200_000 < len(provenance) < 1_400_000, len(provenance)
    store = tmp_path.resolve() / "store"
    manifest, version = _write(store, provenance)
    before = _everything(version)
    assert _refusal(version) is None, (
        f"a version whose provenance record is {len(provenance)} bytes is refused by the reader "
        "of the writer that cut it"
    )
    assert _api("physgate.evaluation.tiers.manifest.read_version")(version) == manifest
    # Read, never rewritten: its id, its records and its tiers are the bytes the split wrote.
    assert _everything(version) == before
    assert (version / "provenance.json").read_bytes() == provenance
    assert manifest.provenance_sha256 == hashlib.sha256(provenance).hexdigest()
    # And so it is no work left, and the store's status shows it as a version.
    leftovers = _api("physgate.evaluation.tiers.store.leftovers")
    assert leftovers(store)["work_left"] == 0, "a version its reader takes is counted as work"
    status = _api("physgate.evaluation.tierset_cli.status")(store)
    (row,) = status["versions"]
    assert row["state"] != "refused", f"the store's status refuses the version: {row}"


def test_a_provenance_record_at_its_limit_is_read_and_one_byte_over_it_is_refused(
    tmp_path: Path,
) -> None:
    most = _api("physgate.evaluation.tiers.manifest.MOST_PROVENANCE_BYTES")
    store = tmp_path.resolve() / "store"
    _, version = _write(store, _sized(most))
    assert _refusal(version) is None, "a provenance record at its limit is refused"
    with (version / "provenance.json").open("ab") as handle:
        handle.write(b" ")
    assert _refusal(version) == "manifest_unreadable", (
        "a provenance record over its limit is not refused as larger than any record of a version"
    )


def test_the_manifest_keeps_its_own_small_limit(tmp_path: Path) -> None:
    manifest_most = _api("physgate.evaluation.tiers.manifest.MOST_MANIFEST_BYTES")
    provenance_most = _api("physgate.evaluation.tiers.manifest.MOST_PROVENANCE_BYTES")
    assert manifest_most < provenance_most
    store = tmp_path.resolve() / "store"
    _, version = _write(store, _round_provenance(sessions=1, files=4))
    stated = json.loads((version / "tierset.json").read_text())
    stated["model"] = stated["model"] + " " * (manifest_most + 1)
    (version / "tierset.json").write_text(json.dumps(stated))
    assert _refusal(version) == "manifest_unreadable", (
        "a manifest over its own limit is read as far as the provenance record's"
    )


def test_the_split_refuses_a_provenance_its_reader_would_refuse_before_writing_anything(
    tmp_path: Path,
) -> None:
    most = _api("physgate.evaluation.tiers.manifest.MOST_PROVENANCE_BYTES")
    store = tmp_path.resolve() / "store"
    pool = _pool(store)
    before = _everything(store)
    write_version = _api("physgate.evaluation.tiers.store.write_version")
    with pytest.raises(AuthoringError) as refused:
        write_version(
            store / "control",
            sorted(p for p in pool.iterdir() if p.is_dir()),
            role="control",
            seed=5,
            model="claude-sonnet-5",
            runtime="2.1.301",
            provenance=_sized(most + 1),
            retire=pool,
            generated="2026-11-19",
        )
    assert refused.value.context.get("refused_because") == "record_too_large", (
        "the split did not refuse a provenance record its reader would refuse"
    )
    # Nothing written: no version, no temporary one, no log, and the pool whole.
    assert _everything(store) == before, "the split wrote before it refused"
    assert len([p for p in pool.iterdir() if p.is_dir()]) == 24


def test_the_reader_and_the_split_hold_the_provenance_to_one_constant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_module = importlib.import_module("physgate.evaluation.tiers.manifest")
    _api("physgate.evaluation.tiers.manifest.MOST_PROVENANCE_BYTES")
    store = tmp_path.resolve() / "store"
    _, written = _write(store, _sized(100_000))
    # One constant moved, and the reader and the split both follow it.
    monkeypatch.setattr(manifest_module, "MOST_PROVENANCE_BYTES", 64 * 1024)
    assert _refusal(written) == "manifest_unreadable", "the reader keeps a limit of its own"
    other = tmp_path.resolve() / "other"
    with pytest.raises(AuthoringError) as refused:
        _write(other, _sized(100_000), accepted=False)
    assert refused.value.context.get("refused_because") == "record_too_large", (
        "the split keeps a limit of its own"
    )
    _, under = _write(tmp_path.resolve() / "third", _sized(60_000))
    assert _refusal(under) is None


def test_the_split_holds_the_manifest_to_the_reader_s_limit_and_leaves_the_pool_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manifest's schema keeps it near a kilobyte; the split holds it to the limit all the same.

    Moved below a manifest's size, the one constant refuses the split after the tiers are
    written into the temporary version, which goes, and the pool stays whole.
    """
    manifest_module = importlib.import_module("physgate.evaluation.tiers.manifest")
    _api("physgate.evaluation.tiers.manifest.MOST_MANIFEST_BYTES")
    monkeypatch.setattr(manifest_module, "MOST_MANIFEST_BYTES", 256)
    store = tmp_path.resolve() / "store"
    with pytest.raises(AuthoringError) as refused:
        _write(store, _round_provenance(sessions=1, files=4), accepted=False)
    assert refused.value.context.get("refused_because") == "record_too_large", (
        "the split wrote a manifest its reader would refuse"
    )
    assert refused.value.context.get("record") == "tierset.json"
    root = store / "control"
    assert not [p for p in root.iterdir() if p.name not in ("withheld", "work")], (
        "a version, or one half written, is left"
    )
    pool = root / "withheld" / "pool"
    assert len([p for p in pool.iterdir() if p.is_dir()]) == 24
