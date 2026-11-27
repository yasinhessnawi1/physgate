"""Whether a version's tasks give a session every value they are scored on: counts, nothing shown.

``physgate tiers values-check`` reads one version of a role's tiers and, for each tier, counts
its tasks by what a session reading them is left without: once for the brief alone, which is all
a session was given before :mod:`.issued`, and once for the issued text, which is what a session
is given now. It prints counts only: no task id, no word of a brief, no value. It writes nothing.

**How a value is named.** The control scorer reads a task's values by fixed names
(``plant_num_<i>``, ``plant_den_<i>``, ``plant_gain``, ``plant_delay``, ``reference_step``,
``actuator_limit``: :mod:`.per_role.plant`), and a brief that writes its plant in symbols writes
these names (on the visible tier every symbol a brief writes is one of them). A symbol here is
one of those names written in the brief as a word of its own. A symbol of any other spelling is
not read, and a brief that writes its plant in numbers names none.

The counts, for each tier:

- ``tasks``;
- ``not_issuable``: tasks whose values the scorer refuses to read, so no session is given them;
- ``names_no_input``: tasks whose brief writes none of the scorer's names;
- ``symbol_without_value``, for the brief and for the issued text: tasks where a name the brief
  writes is given no value in that text (a value is the name followed by ``=``, ``:``, ``is`` or
  an opening parenthesis, then a number);
- ``given_without_value``, for the brief and for the issued text: tasks whose brief calls a value
  given or known in a sentence that holds no number, where that text gives no value to the input
  the sentence's words name (a limit or an actuator: ``actuator_limit``; a gain: ``plant_gain``;
  a delay or a dead time: ``plant_delay``; a step, a reference or an amplitude:
  ``reference_step``; the plant, a coefficient, a pole, a zero, a numerator or a denominator:
  every coefficient), or names none of them;
- ``relies_on_default``: tasks for which the scorer takes a value by default, by its name (the
  gain and the delay of every control task that gives none; the reference step only where the
  task bounds the controller's peak output, the one metric that uses it);
- ``brief_names_a_defaulted_value``: of those, tasks whose brief writes the defaulted value's
  name, by its name. Such a brief names a value the task never gives: the issued text says what
  the scorer takes for it, and the task stays as it was written;
- ``issued_leaks``: tasks whose issued text states a number of the task's passing reference
  answer, by the tier's own leak rule (:func:`.per_role.leaks.text_leaks`, the rule the split
  holds a brief to), now held to what a session reads; and ``issued_leak_unchecked``, tasks the
  rule could not be held to (their good reference cannot be read). On a sound tier both are 0:
  the values are the plant's, and the reference is a controller. The tier's own check and its
  records are not changed.

What it does not count: a unit a brief writes beside a value. A brief's units are words beside
numbers, and no rule here tells a unit from the word after a number soundly, so the issued text
states each value in the unit the scorer reads it in, and no count is made of where a brief says
another.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.leaks import text_leaks
from physgate.evaluation.per_role.metrics import ACTUATOR_LIMIT, REFERENCE_STEP
from physgate.evaluation.per_role.plant import (
    DEFAULTS,
    DELAY,
    DENOMINATOR,
    GAIN,
    NUMERATOR,
    bounds_actuator_peak,
)
from physgate.evaluation.tiers.issued import issued_text
from physgate.evaluation.tiers.task import LoadedTask, Role, Task, load_task

#: The tiers of a version, in the order they are counted.
TIERS = ("visible", "validation", "held_out")
#: The scorer's names, as a brief may write them: a word of its own, never part of another.
_EDGE_BEFORE = r"(?<![A-Za-z0-9_])"
_EDGE_AFTER = r"(?![A-Za-z0-9_])"
_NAME = re.compile(
    _EDGE_BEFORE
    + rf"({NUMERATOR}_\d+|{DENOMINATOR}_\d+|{GAIN}|{DELAY}|{REFERENCE_STEP}|{ACTUATOR_LIMIT})"
    + _EDGE_AFTER
)
#: What follows a name that is given its value: a sign of equality, then a number.
_VALUE_AFTER = r"[`*]*\s*(?:=|:|≈|\bis\b|\(\s*=?)\s*[-+−]?(?:\d|\.\d)"
#: A number of its own, never a digit of a name (``plant_den_2``) or a power (``s^2``).
_NUMBER = re.compile(r"(?<![A-Za-z_^\d.])[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_GIVEN = re.compile(r"\b(?:given|known)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.;!?])\s+|\n\s*\n")
#: The words of a sentence that name an input, and the inputs they name.
_WORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:limit|actuator|saturat)", re.IGNORECASE), ACTUATOR_LIMIT),
    (re.compile(r"\bgain", re.IGNORECASE), GAIN),
    (re.compile(r"\b(?:delay|dead[ -]time)", re.IGNORECASE), DELAY),
    (re.compile(r"\b(?:step|reference|amplitude)", re.IGNORECASE), REFERENCE_STEP),
    (
        re.compile(r"\b(?:plant|coefficient|pole|zero|numerator|denominator)", re.IGNORECASE),
        "coefficients",
    ),
)


class ValuesCheckError(PerRoleError):
    """The version cannot be counted, for a reason it names; never a task."""


def _valued(name: str, text: str) -> bool:
    return re.search(_EDGE_BEFORE + re.escape(name) + _VALUE_AFTER, text) is not None


def _symbols(brief: str) -> set[str]:
    return {match.group(1) for match in _NAME.finditer(brief)}


def _coefficients(task: Task) -> set[str]:
    return {m.name for m in task.inputs if m.name.startswith((NUMERATOR + "_", DENOMINATOR + "_"))}


def _given_without_value(task: Task, text: str) -> bool:
    """Whether the brief calls a value given or known that ``text`` gives no value to."""
    for sentence in _SENTENCE_END.split(task.brief):
        if not _GIVEN.search(sentence) or _NUMBER.search(sentence):
            continue
        named = set(_symbols(sentence))
        for pattern, name in _WORDS:
            if pattern.search(sentence):
                named |= _coefficients(task) if name == "coefficients" else {name}
        if not named or not any(_valued(name, text) for name in named):
            return True
    return False


def _defaults(task: Task) -> set[str]:
    """The values the scorer takes by default for ``task``: those it uses and the task lacks."""
    if task.scorer.id != "control":
        return set()
    used = {GAIN, DELAY} | ({REFERENCE_STEP} if bounds_actuator_peak(task) else set())
    return used - {m.name for m in task.inputs}


def _tier_counts(loaded: list[LoadedTask]) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "tasks": len(loaded),
        "not_issuable": 0,
        "names_no_input": 0,
        "symbol_without_value": {"brief": 0, "issued": 0},
        "given_without_value": {"brief": 0, "issued": 0},
        "relies_on_default": dict.fromkeys(DEFAULTS, 0),
        "brief_names_a_defaulted_value": dict.fromkeys(DEFAULTS, 0),
        "issued_leaks": 0,
        "issued_leak_unchecked": 0,
    }
    for each in loaded:
        task = each.task
        try:
            issued: str | None = issued_text(task)
        except PerRoleError:
            issued = None
            counts["not_issuable"] += 1
        if issued is not None:
            try:
                counts["issued_leaks"] += text_leaks(issued, each)
            except Exception:  # noqa: BLE001 - a check that cannot run is counted, never passed
                counts["issued_leak_unchecked"] += 1
        symbols = _symbols(task.brief)
        if not symbols:
            counts["names_no_input"] += 1
        for text, key in ((task.brief, "brief"), (issued, "issued")):
            if text is None:
                continue
            if any(not _valued(name, text) for name in symbols):
                counts["symbol_without_value"][key] += 1
            if _given_without_value(task, text):
                counts["given_without_value"][key] += 1
        for name in _defaults(task):
            counts["relies_on_default"][name] += 1
            if name in symbols:
                counts["brief_names_a_defaulted_value"][name] += 1
    return counts


def value_counts(store: Path, role: Role, version: str) -> dict[str, Any]:
    """Each tier of the version, counted; nothing of any task is in what is returned.

    Raises:
        ValuesCheckError: the version is not one of the role's, is not what its manifest says, or
            a task of a tier cannot be read; the tier is said, never a task.
    """
    from physgate.evaluation.tiers.manifest import VERSION_NAME, read_version
    from physgate.evaluation.tiers.store import version_dir

    if not VERSION_NAME.fullmatch(version):
        msg = "a version is named by its 64 hex digits"
        raise ValuesCheckError(msg, refused_because="version_unknown")
    directory = version_dir(store, role, version)
    try:
        read_version(directory)
    except (OSError, PerRoleError):
        msg = f"the version {version[:8]} is not one of the role's, or not what its manifest says"
        raise ValuesCheckError(msg, refused_because="version_unknown") from None
    tiers: dict[str, Any] = {}
    for tier in TIERS:
        here = directory / tier
        try:
            entries = sorted(p for p in here.iterdir() if p.is_dir() and not p.is_symlink())
            tasks = [load_task(entry) for entry in entries]
        except (OSError, PerRoleError):
            # The error may name a task; only its tier is said.
            msg = f"a task of the {tier} tier cannot be read"
            raise ValuesCheckError(msg, refused_because="tier_unreadable", tier=tier) from None
        tiers[tier] = _tier_counts(tasks)
    return {"role": role, "version": version, "tiers": tiers}


__all__ = ["TIERS", "ValuesCheckError", "value_counts"]
