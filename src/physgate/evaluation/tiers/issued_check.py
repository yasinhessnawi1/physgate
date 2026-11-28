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
  rule could not be held to (their good reference cannot be read). The tier's own check and its
  records are not changed;
- of the tasks counted in ``issued_leaks``, what they hold. The rule counts a task when any one
  number of its reference other than 0, 1 and -1 equals any number the text holds, and it reads
  a number wherever digits stand, so the digit of a coefficient's name (``plant_den_2``), of a
  unit (``s**2``) or of a power (``s^2``) is a number to it. Each such number of the reference
  (each distinct one, read and compared as the rule reads and compares them) is placed where it
  lies, in this order: in the brief; a value written under one of the scorer's names (the
  plant's coefficients, its gain and delay, the reference step, the actuator limit, given or
  taken by default); the value of an input of any other name; else only a digit of the issued
  block's own names, units, powers and words. ``issued_leaks_by_kind`` counts the tasks by
  those places: ``scorer_named_values_only`` (the plant's own numbers: a controller may well
  place a zero on a plant pole), ``names_units_or_powers_only`` (an artefact of the reading),
  ``scorer_named_values_and_names_units_or_powers`` (both), and ``unread_input_or_brief`` (some
  number lies in an input the scorer does not read, or in the brief: where a give-away would
  be). ``issued_leaks_all_reference_numbers`` counts the tasks whose text holds every such
  number of the reference, wherever it lies, and ``issued_leaks_matched_of_total`` lists, for
  each counted task, how many of them the text holds and how many there are, sorted, so no
  task's place in its tier is told. A default is 0 or 1, so it never counts.

What it does not count: a unit a brief writes beside a value. A brief's units are words beside
numbers, and no rule here tells a unit from the word after a number soundly, so the issued text
states each value in the unit the scorer reads it in, and no count is made of where a brief says
another.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.answer import read_lti_tf
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.leaks import NUMBER as LEAK_NUMBER
from physgate.evaluation.per_role.leaks import TRIVIAL, text_leaks
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


#: Where a leaking task's reference numbers lie, as ``issued_leaks_by_kind`` counts the tasks.
LEAK_KINDS = (
    "scorer_named_values_only",
    "names_units_or_powers_only",
    "scorer_named_values_and_names_units_or_powers",
    "unread_input_or_brief",
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


def _held(number: float, told: list[float]) -> bool:
    # As the leak rule compares a number of the reference with one a text holds.
    return any(math.isclose(number, t, rel_tol=1e-9, abs_tol=0.0) for t in told)


def _read(text: str) -> list[float]:
    # As the leak rule reads a text's numbers: wherever digits stand.
    return [float(x) for x in LEAK_NUMBER.findall(text)]


def _leak_kind(issued: str, loaded: LoadedTask) -> tuple[str, int, int] | None:
    """Where ``issued``'s numbers of the good reference lie, how many it holds, of how many.

    ``None`` exactly when the leak rule finds none: the same reference, numbers and comparison.

    Raises:
        TaskFormatError: the good reference's answer cannot be read.
    """
    task = loaded.task
    good = next(ref for ref in loaded.references if ref.fails is None)
    answer = read_lti_tf(Path(good.answer_path))
    numbers = {
        n
        for n in (float(answer.gain.value), *answer.num_values(), *answer.den_values())
        if n not in TRIVIAL
    }
    held = [n for n in numbers if _held(n, _read(issued))]
    if not held:
        return None
    brief = _read(task.brief)
    named = [float(m.value) for m in task.inputs if _NAME.fullmatch(m.name)]
    named += [float(DEFAULTS[name].value) for name in _defaults(task)]
    unread = [float(m.value) for m in task.inputs if not _NAME.fullmatch(m.name)]
    places = set()
    for n in held:
        if _held(n, brief):
            places.add("brief")
        elif _held(n, named):
            places.add("named")
        elif _held(n, unread):
            places.add("unread")
        else:
            places.add("scaffold")
    if places & {"brief", "unread"}:
        kind = "unread_input_or_brief"
    elif places == {"named"}:
        kind = "scorer_named_values_only"
    elif places == {"scaffold"}:
        kind = "names_units_or_powers_only"
    else:
        kind = "scorer_named_values_and_names_units_or_powers"
    return kind, len(held), len(numbers)


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
        "issued_leaks_by_kind": dict.fromkeys(LEAK_KINDS, 0),
        "issued_leaks_all_reference_numbers": 0,
        "issued_leaks_matched_of_total": [],
    }
    pairs: list[list[int]] = []
    for each in loaded:
        task = each.task
        try:
            issued: str | None = issued_text(task)
        except PerRoleError:
            issued = None
            counts["not_issuable"] += 1
        if issued is not None:
            try:
                kind = _leak_kind(issued, each)
                counts["issued_leaks"] += text_leaks(issued, each)
            except Exception:  # noqa: BLE001 - a check that cannot run is counted, never passed
                counts["issued_leak_unchecked"] += 1
            else:
                if kind is not None:
                    name, held, total = kind
                    counts["issued_leaks_by_kind"][name] += 1
                    counts["issued_leaks_all_reference_numbers"] += held == total
                    pairs.append([held, total])
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
    # Sorted, so the list tells nothing of the order the tier's tasks are read in.
    counts["issued_leaks_matched_of_total"] = sorted(pairs)
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


__all__ = ["LEAK_KINDS", "TIERS", "ValuesCheckError", "value_counts"]
