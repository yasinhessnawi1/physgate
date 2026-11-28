"""Nothing but the named openers reads a tier, and every one of them is on the evaluation side.

Every function under ``src/`` that reads a tier's bytes, a task's file or a protected tier's
canary list, or joins a path onto a protected tier's name, is named below with what it reads it
for. The list is exact both ways: a new reader fails until a reviewed change names it here, and a
reader that is gone fails until its line is taken out, so the list stays what the code does. The
readers are found from the source alone, every import followed to where it points, so a reader
taken under another name, through a module, by a relative import or by a string is found too.

Every reader lies in the evaluation, never in the product: the harness's core reads no tier,
and the protection that stands in front of the held-out tier (the hooks, the OS layer, the
tripwire's walk of names and identities) reads no task's bytes. No test names a protected place
that exists on the machine it runs on: what a test reads of a tier, it built in its own temporary
directory.
"""

from __future__ import annotations

import ast
import json
import os
import re
import textwrap
from pathlib import Path

import pytest
from openers import readers_in, readers_of, readers_under, reexports_of, sources_under

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
TESTS = ROOT / "tests"

#: Each reader of a tier, by ``module:function``, and why it reads one.
NAMED: dict[str, str] = {
    # The tier's own bytes, read once through descriptors, and the digests made of them.
    "physgate.evaluation.tiers.heldout:tier_digest": "a tier's digest, from its bytes",
    "physgate.evaluation.tiers.heldout:digest": "the digest of a tier's digest file",
    "physgate.evaluation.tiers.heldout:_tier_problems": "the pre-run scan of a protected tier",
    "physgate.evaluation.tiers.heldout:_visible_problems": "the pre-run scan of the visible tier",
    "physgate.evaluation.tiers.manifest:tier_record": "a tier as its version's manifest records it",
    "physgate.evaluation.tiers.manifest:read_version": "a version held to its manifest",
    "physgate.evaluation.tiers.task:load_task": "a task with its references, from its directory",
    "physgate.evaluation.tiers.task:task_from_files": "a task from bytes already read",
    "physgate.evaluation.tiers.canaries:root_canaries": "the canary lists beneath a root",
    "physgate.evaluation.tiers.canaries:store_canaries": "the canary lists of every role's root",
    # The split writer.
    "physgate.evaluation.tiers.authoring:split": "the split writer: the staged tasks",
    "physgate.evaluation.tiers.authoring:_place": "the split writer: each task as placed",
    "physgate.evaluation.tiers.authoring:_check_placed": "the split writer: each task read back",
    "physgate.evaluation.tiers.store:write_version": "the split writer: a version's tiers",
    "physgate.evaluation.tiers.store:_out_of_place": "whether a version in the store is whole",
    # The exposure register and the reportable-run rule.
    "physgate.evaluation.tiers.exposure:versions": "every version of a role, held to its manifest",
    "physgate.evaluation.tiers.exposure:_versions_with_brief": "the version a run's brief is in",
    "physgate.evaluation.tiers.exposure:_protected_briefs": "the protected tiers' briefs, digested",
    "physgate.evaluation.tiers.exposure:_version_refusal": "a measured run's tiers, by digest",
    "physgate.evaluation.tiers.exposure:_scan_refusal": "the pre-run scan of a run's version",
    "physgate.evaluation.tierset_cli:status": "each version's state, counts and digests",
    # The scorer at measurement: the counting rule and the vector writer.
    "physgate.evaluation.tiers.measure:_tier_tasks": "each run's task, found by what it was given",
    # The values check: each tier's tasks counted by what they leave a session without.
    "physgate.evaluation.tiers.issued_check:value_counts": "the values check: counts only",
    # The isolation probe.
    "physgate.evaluation.tiers.probe:probe_version": "the probe: the held-out tier, read once",
    "physgate.evaluation.tiers.probe:_tasks": "the probe: the held-out tasks it scores",
    # The blind check's record, derived once from an earlier check's kept session.
    "physgate.evaluation.tiers.checks:import_check": "the version an imported answer is held to",
    "physgate.evaluation.tiers.checks:_held_out_digests": "each held-out id's digest, counted",
    "physgate.evaluation.tiers.checks:_given_to_the_check": "the tasks a check of it is given",
    # The tasks the blind check is given, by digest, without references or canary.
    "physgate.evaluation.tiers.check_tasks:bundle": "the tasks given to the blind check",
    # The author session and the blind check.
    "physgate.evaluation.per_role.author_session:author": "the author's protected tiers' places",
    "physgate.evaluation.per_role.author_session:blind_check": "the blind check of a version",
    "physgate.evaluation.per_role.author_session:_require_none_came": "canaries after a session",
    "physgate.evaluation.per_role.cli:_author": "the canaries an author session is held to",
    "physgate.evaluation.per_role.cli:_blind_check": "the canaries a blind check is held to",
    "physgate.evaluation.per_role.cli:_report": "the version a held-out suite's check is bound to",
    # The validator, and the references held to the scorer before any arm runs.
    "physgate.evaluation.per_role.validate:_examine": "the validator: counts and digests only",
    "physgate.evaluation.per_role.validate:refusal_reasons": "the validator's refusals, counted",
    "physgate.evaluation.per_role.synthesise:prepare": "each task held to its references",
    "physgate.evaluation.per_role.controleval:task_for": "a published benchmark's task, as built",
    # The baseline round: the raw arm on every harness trial of a version.
    "physgate.evaluation.baseline.runner:plan": "the version a baseline round runs on",
    "physgate.evaluation.baseline.runner:_tasks": "each harness run's task, by what it was given",
    "physgate.evaluation.baseline.runner:_external_tasks": "an external set's tasks and digest",
    "physgate.evaluation.baseline.runner:_listed": "the canaries a raw session is held to",
    # The harness round: each task's brief written for its trial, found again by its digest.
    "physgate.evaluation.harness_round:_version_tasks": "the tasks a harness round runs",
}


def test_the_functions_that_read_a_tier_are_the_named_ones() -> None:
    found = readers_under(SRC)
    unnamed = sorted(
        f"{where}: {sorted(how)}" for where, how in found.items() if where not in NAMED
    )
    gone = sorted(where for where in NAMED if where not in found)
    assert unnamed == [], "a reader of a tier that is not named"
    assert gone == [], "a named reader that reads no tier now"


def test_every_reader_of_a_tier_lies_in_the_evaluation() -> None:
    outside = sorted(w for w in readers_under(SRC) if not w.startswith("physgate.evaluation."))
    assert outside == []


def _found(source: str, module: str = "physgate.planted") -> dict[str, set[str]]:
    return readers_in(ast.parse(textwrap.dedent(source)), module)


@pytest.mark.parametrize(
    ("source", "where"),
    [
        (
            "from physgate.evaluation.tiers.heldout import snapshot as look\n"
            "def f(p):\n    return look(p)\n",
            "f",
        ),
        (
            "import physgate.evaluation.tiers.task as t\n"
            "def f(raw):\n    return t.parse_task(raw)\n",
            "f",
        ),
        (
            "from physgate.evaluation.tiers import manifest\n"
            "class C:\n    def m(self, d):\n        return manifest.read_version(d)\n",
            "C.m",
        ),
        (
            "import physgate.evaluation.tiers.heldout\n"
            "def f(p):\n    return physgate.evaluation.tiers.heldout.tier_digest(p)\n",
            "f",
        ),
        (
            "def f(raws):\n"
            "    from physgate.evaluation.tiers.task import parse_task\n"
            "    return list(map(parse_task, raws))\n",
            "f",
        ),
        ("from physgate.evaluation.tiers.task import load_task\nFOUND = load_task\n", "<module>"),
        ("def f(version):\n    return (version / 'held_out').read_bytes()\n", "f"),
        (
            "from physgate.evaluation.tiers.authoring import SUMS_NAME\n"
            "def f(tier):\n    return (tier / SUMS_NAME).read_bytes()\n",
            "f",
        ),
        (
            "import importlib\n"
            "def f():\n    return importlib.import_module('physgate.evaluation.tiers.heldout')\n",
            "f",
        ),
        ("def f():\n    return __import__('physgate.evaluation.tiers.task')\n", "f"),
    ],
    ids=[
        "a reader under another name",
        "a reader through a module alias",
        "a reader through its package, in a method",
        "a reader by its whole dotted name",
        "a reader imported inside a function and passed on",
        "a reader at module level",
        "a path joined onto a protected tier's name",
        "a path joined onto a protected tier's own file",
        "a tier module imported by a string",
        "a tier module imported by the builtin",
    ],
)
def test_a_reader_is_found_however_it_is_reached(source: str, where: str) -> None:
    assert where in _found(source)


def test_a_relative_import_inside_the_tiers_is_followed() -> None:
    source = "from .heldout import snapshot\ndef f(p):\n    return snapshot(p)\n"
    assert "f" in _found(source, module="physgate.evaluation.tiers.planted")


@pytest.mark.parametrize(
    ("source", "where"),
    [
        ("import os\ndef f(version):\n    return os.path.join(version, 'held_out')\n", "f"),
        ("from os.path import join\ndef f(v):\n    return open(join(v, 'validation'))\n", "f"),
        ("def f(version):\n    return version.joinpath('held_out').read_bytes()\n", "f"),
        ("from pathlib import Path\ndef f(version):\n    return Path(version, 'held_out')\n", "f"),
        ("def f(version):\n    return '/'.join([version, 'held_out'])\n", "f"),
        ("def f(version, task):\n    return open(f'{version}/held_out/{task}')\n", "f"),
        (
            "import os\nfrom physgate.evaluation.tiers.probe import PROBED_TIER\n"
            "def f(v):\n    return os.path.join(v, PROBED_TIER)\n",
            "f",
        ),
        (
            "from physgate.evaluation.tiers.probe import PROBED_TIER\n"
            "def f(v):\n    return f'{v}/{PROBED_TIER}'\n",
            "f",
        ),
    ],
    ids=[
        "by os.path.join",
        "by join under another name",
        "by joinpath",
        "by a path's constructor",
        "by a string's join",
        "in a format",
        "by os.path.join onto a name of the tiers",
        "in a format, onto a name of the tiers",
    ],
)
def test_a_path_joined_onto_a_protected_tier_s_name_is_found_however_it_is_joined(
    source: str, where: str
) -> None:
    assert where in _found(source)


@pytest.mark.parametrize(
    "source",
    [
        "import os\ndef f(v):\n    return os.path.join(v, 'visible')\n",
        "def f(v):\n    return f'the held_out tier of {v} is not read here'\n",
        "def f(parts):\n    return '/'.join(parts)\n",
    ],
    ids=["onto the visible tier", "a tier's name in words", "a join of names it is given"],
)
def test_a_join_that_names_no_protected_tier_is_not_one(source: str) -> None:
    assert _found(source) == {}


#: The tiers package and a caller that takes a reader from it, as a re-export would have it.
REEXPORTED = {
    "physgate.evaluation.tiers": "from .heldout import snapshot\n",
    "physgate.evaluation.tiers.heldout": "def snapshot(root):\n    return {}\n",
}


@pytest.mark.parametrize(
    "extra",
    [
        {
            "physgate.planted": (
                "from physgate.evaluation.tiers import snapshot\n"
                "def f(p):\n    return snapshot(p)\n"
            )
        },
        {
            "physgate.planted": (
                "import physgate.evaluation.tiers as tiers\ndef f(p):\n"
                "    return tiers.snapshot(p)\n"
            )
        },
        {
            "physgate.evaluation.tiers.helpers": (
                "from physgate.evaluation.tiers import heldout\nlook = heldout.snapshot\n"
            ),
            "physgate.evaluation.again": "from physgate.evaluation.tiers.helpers import look\n",
            "physgate.planted": (
                "from physgate.evaluation.again import look as glance\ndef f(p):\n"
                "    return glance(p)\n"
            ),
        },
    ],
    ids=["from the package", "through the package's name", "through two re-exports, one an alias"],
)
def test_a_reader_taken_through_a_re_export_is_found(extra: dict[str, str]) -> None:
    found = readers_of({**REEXPORTED, **extra})
    assert "physgate.planted:f" in found


def test_a_re_export_of_a_reader_is_found() -> None:
    sources = {
        **REEXPORTED,
        "physgate.evaluation.tiers.helpers": (
            "from physgate.evaluation.tiers import heldout\nlook = heldout.snapshot\n"
        ),
    }
    assert reexports_of(sources) == {
        "physgate.evaluation.tiers": frozenset({"snapshot"}),
        "physgate.evaluation.tiers.helpers": frozenset({"look"}),
    }


#: The packages of the evaluation whose names a caller would take a reader from.
PACKAGES = ("physgate.evaluation", "physgate.evaluation.tiers", "physgate.evaluation.gaps")
#: Each reader a package of the evaluation re-exports, by ``package:name``; none today.
PACKAGE_REEXPORTS: dict[str, str] = {}


def test_no_package_re_exports_a_reader_that_is_not_named() -> None:
    found = reexports_of(sources_under(SRC))
    listed = {f"{module}:{name}" for module in PACKAGES for name in found.get(module, ())}
    assert sorted(listed - set(PACKAGE_REEXPORTS)) == [], "a package re-exports a reader"
    assert sorted(set(PACKAGE_REEXPORTS) - listed) == [], "a named re-export is gone"


def test_a_name_that_only_shares_a_reader_s_name_is_not_one() -> None:
    source = (
        "from physgate.hooks.snapshot import signature as snapshot\n"
        "from physgate.orchestrator import placeholders\n"
        "def f(p):\n    return snapshot(p), placeholders.snapshot(p)\n"
        "def g(d):\n    return d / 'visible'\n"
    )
    assert _found(source) == {}


# ------------------------------------------------------------------ what the tests name

#: A protected place's name, as a path a test writes out may hold it.
PROTECTED_WORDS = re.compile(r"held[-_]?out|withheld|validation|corpora|tierset", re.IGNORECASE)


def _path_strings(path: Path) -> list[str]:
    """Every string in ``path`` that is an absolute or home path naming a protected place."""
    if path.suffix == ".py":
        tree = ast.parse(path.read_text(), filename=str(path))
        strings = [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
    else:
        strings = []

        def collect(value: object) -> None:
            if isinstance(value, str):
                strings.append(value)
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(json.loads(path.read_text()))
    return [
        s
        for s in strings
        if (s.startswith(("/", "~/")) and "\n" not in s and PROTECTED_WORDS.search(s))
    ]


def test_no_test_names_a_protected_place_that_exists_here() -> None:
    real = [
        f"{path.relative_to(ROOT)}: {text}"
        for path in sorted([*TESTS.rglob("*.py"), *TESTS.rglob("*.json")])
        for text in _path_strings(path)
        if os.path.lexists(os.path.expanduser(text.split()[0]))
    ]
    assert real == []


def test_a_test_naming_a_protected_place_that_exists_is_found(tmp_path: Path) -> None:
    place = tmp_path / "store" / "control" / "withheld"
    place.mkdir(parents=True)
    planted = tmp_path / "test_planted.py"
    planted.write_text(f"ROOT = {str(place)!r}\n")
    named = _path_strings(planted)
    assert named == [str(place)] and os.path.lexists(named[0])
