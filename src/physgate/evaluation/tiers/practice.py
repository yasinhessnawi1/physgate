"""A practice store: one version of control tasks written for practice, never for a measurement.

A shakedown runs both arms end to end on a version in a store of its own, so that every step a
counted trial takes (the refusals of a measured run, the placement beneath a run root, the
canary scans, the held-out exclusions, the baseline round, the report) runs once without
touching a real tier. :func:`build_practice_store` writes that store.

**Its tasks are practice tasks**, written here and labelled so in every brief: six control
tasks, one plant family (a second-order plant with one unstable pole, ``1 / (s^2 + a s - b)``,
each task its own ``a`` and ``b``), adapted in kind from a published benchmark's second-order
unstable category, with three specifications composing three requirements. Each is held to the
split's own entry checks before the split: it loads, it composes at least two requirements, its
scorer passes its good reference and fails its bad one on the spec it names, its brief gives no
number of the good reference away, and its directory is named by its id
(:func:`.per_role.validate.sound`). Their content is the builder's own, not an author session's,
and wants a person's look before a shakedown relies on it.

**The version** is written by the store's own writer (:func:`.store.write_version`) with two
tasks to a tier, split by the seed given: so its held-out tier holds two practice tasks, its
validation tier two and its visible tier two, each protected tier with its canary list, as the
version format requires.

**Its check record** is written in the imported form (``source: imported``, the form the real
version's record has), through the store's own writer (:func:`.checks.write_check`), flagging
no task. No blind check ran on practice tasks: the record's kept session is named
``practice-no-check-session`` and keeps no stream, its answer is the all-yes answer on the
held-out ids' digests, and its spend is unknown. It is a stand-in that lets the round's
check-record path run, and says so in its own fields.

The store is built only into a directory that does not exist, so nothing real is ever beside it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.manifest import TierSet
from physgate.evaluation.tiers.task import canonical_json

#: The plants of the six practice tasks: ``(a, b)`` of ``1 / (s^2 + a s - b)``.
PLANTS = ((0.5, 2.0), (1.0, 3.0), (0.25, 1.5), (0.75, 4.0), (0.4, 2.5), (1.25, 5.0))
#: The good reference of every practice task: a lead controller ``K (s + z) / (s + p)``.
GOOD = (96.0, 1.75, 12.5)
#: The bad reference: the same controller at a gain too low to hold the unstable pole.
BAD = (0.5, 1.75, 12.5)
#: Each tier's count in the practice version.
PER_TIER = 2
#: The seed the practice version is split by, unless another is given.
SEED = 20261124
#: The model the stand-in check record names, as the real check's model is named.
CHECK_MODEL = "claude-sonnet-5"
#: The kept session the stand-in check record names: there was none.
NO_SESSION = "practice-no-check-session"
#: What every practice brief begins with.
LABEL = "PRACTICE TASK, for a shakedown only; never a measured task."


class PracticeError(PerRoleError):
    """The practice store cannot be built, for a reason it names."""


def practice_task(number: int) -> dict[str, Any]:
    """Practice task ``number`` (from 0), as its ``task.json`` holds it."""
    a, b = PLANTS[number]
    brief = (
        f"{LABEL} The plant is G(s) = 1 / (s^2 + {a} s - {b}), with one unstable pole. Design "
        "a linear controller for unity negative feedback around it that makes the closed loop "
        "stable, settles a unit step in under 5 s and overshoots it by under 60 percent. Write "
        "the controller as a transfer function to answer.json in the directory you work in."
    )
    return {
        "id": f"control.practice_{number:02d}",
        "role": "control",
        "tier": "visible",
        "source": {"kind": "own"},
        "brief": brief,
        "inputs": [
            {"name": "plant_num_0", "value": 1.0, "unit": "1"},
            {"name": "plant_den_0", "value": 1.0, "unit": "s**2"},
            {"name": "plant_den_1", "value": a, "unit": "s"},
            {"name": "plant_den_2", "value": -b, "unit": "1"},
        ],
        "answer": {"path": "answer.json", "form": "lti_tf"},
        "specs": [
            {
                "name": "stable",
                "metric": "max_real_pole",
                "op": "<",
                "bound": {"value": 0, "unit": "1/s"},
                "composes": ["hold_the_unstable_pole", "reject_a_disturbance"],
            },
            {
                "name": "settles",
                "metric": "settling_time",
                "op": "<",
                "bound": {"value": 5.0, "unit": "s"},
                "composes": ["hold_the_unstable_pole", "settle_quickly"],
            },
            {
                "name": "overshoot",
                "metric": "overshoot",
                "op": "<",
                "bound": {"value": 60.0, "unit": "percent"},
                "composes": ["settle_quickly"],
            },
        ],
        "scorer": {"id": "control", "version": "1.1.0", "params": []},
    }


def _controller(gain: float, zero: float, pole: float) -> dict[str, Any]:
    return {
        "form": "lti_tf",
        "gain": {"value": gain, "unit": "1"},
        "num": [{"value": 1.0, "unit": "s"}, {"value": zero, "unit": "1"}],
        "den": [{"value": 1.0, "unit": "s"}, {"value": pole, "unit": "1"}],
    }


def write_practice_task(pool: Path, number: int) -> Path:
    """Write practice task ``number`` with its references into ``pool``; its directory."""
    task = practice_task(number)
    directory = pool / str(task["id"])
    good = directory / "references" / "good"
    bad = directory / "references" / "bad_unstable"
    good.mkdir(parents=True)
    bad.mkdir(parents=True)
    (directory / "task.json").write_bytes(canonical_json(task))
    (good / "answer.json").write_bytes(canonical_json(_controller(*GOOD)))
    (bad / "answer.json").write_bytes(canonical_json(_controller(*BAD)))
    (bad / "expect.json").write_bytes(canonical_json({"fails": "stable"}))
    return directory


def build_practice_store(
    store: Path,
    *,
    implementer_model: str,
    seed: int = SEED,
    runtime: str = "practice",
) -> TierSet:
    """Build a store at the new directory ``store`` with one practice version; its manifest.

    Runs in the evaluation environment: each task's scorer is run on its references.

    Raises:
        PracticeError: ``store`` exists (``store_exists``), or a practice task is not one the
            split takes (``practice_task_refused``, with its counted reasons).
        PerRoleError: the store's writers refuse, each with its own reason.
    """
    from physgate.evaluation.per_role.validate import refusal_reasons, sound
    from physgate.evaluation.tiers.checks import make_check, write_check
    from physgate.evaluation.tiers.store import pool_dir, write_version

    if store.exists() or store.is_symlink():
        msg = "a practice store is built only into a directory that does not exist"
        raise PracticeError(msg, refused_because="store_exists")
    pool = pool_dir(store, "control")
    pool.mkdir(parents=True)
    written = [write_practice_task(pool, n) for n in range(3 * PER_TIER)]
    taken = sound(pool)
    if sorted(taken) != sorted(d.name for d in written):
        reasons = refusal_reasons(pool)
        msg = f"a practice task is not one the split takes: {reasons}"
        raise PracticeError(msg, refused_because="practice_task_refused")
    provenance = canonical_json({"practice": True, "written_by": "physgate.tiers.practice"})
    manifest, _ = write_version(
        store / "control",
        written,
        role="control",
        seed=seed,
        model="practice",
        runtime=runtime,
        provenance=provenance,
        retire=pool,
        per_tier=PER_TIER,
    )
    held = _held_out_digests(store, manifest)
    answer = {
        digest: {"states_every_requirement": True, "unambiguous": True, "answerable_as_asked": True}
        for digest in held
    }
    record = make_check(
        role="control",
        version=manifest.version,
        tier="held_out",
        tier_sha256=manifest.held_out.sha256,
        source="imported",
        checked=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        pins={
            "model": CHECK_MODEL,
            "claude_version": runtime,
            "implementer_model": implementer_model,
        },
        kept={"session_id": NO_SESSION, "stream_sha256": None, "bound_by": "answer_keys"},
        session={},
        tasks=len(held),
        all_yes=len(held),
        flagged=[],
        answer_sha256=hashlib.sha256(canonical_json(answer)).hexdigest(),
    )
    write_check(store, "control", record)
    return manifest


def _held_out_digests(store: Path, manifest: TierSet) -> list[str]:
    """The digests of the practice version's held-out ids, as the check would key its answer."""
    from physgate.evaluation.tiers.checks import _held_out_digests as digests

    return sorted(digests(store, "control", manifest.version))


def describe(manifest: TierSet) -> str:
    """The line the command prints: the version and its tiers' counts and digests."""
    return json.dumps(
        {
            "version": manifest.version,
            "practice": True,
            **{
                tier: {
                    "count": getattr(manifest, tier).count,
                    "sha256": getattr(manifest, tier).sha256,
                }
                for tier in ("visible", "validation", "held_out")
            },
        },
        sort_keys=True,
    )
