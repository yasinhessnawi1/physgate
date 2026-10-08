"""A paired reviewer's rubric: four sections, one promoted version, and its digest on every review.

**What a rubric holds (ARCH-062).** A title, then any number of preamble sections
(a verdict policy, a verdict format, notation), then the four required sections,
each once, in this order: the spec's acceptance criteria, the domain's standard
violations, the skill file's antipatterns, and the reward-hacking indicators to
report. A required section's heading may carry a number (``## 1. Acceptance
criteria``), and may hold third-level subheadings. Every section holds items,
each a list line opening with its bold id: ``- **<ID>. <title>**``, where the id
is one or two capitals and a number, with or without a hyphen (``A1``, ``DS-15``).
The reward-hacking section names, in its item titles, the three indicators the
architecture lists: feature isolation, hard-coded values and disabled checks.

Every item id is what a verdict must answer: a verdict that leaves one out is not
a verdict.

**The generalist rubric (ARCH-063's baseline).** The cost of pairing is measured
against a generalist review of the same artefact: the reviewed role's promoted
rubric with its two domain sections removed by code (:func:`generalist_of`). Their
headings stay, each followed by one fixed line saying the section is not part of
this review; every other byte is the promoted rubric's, its canary line included.
The four-section rule takes the kind: a ``paired`` rubric has items in all four
sections, a ``generalist`` one in the first and the fourth and none under the
other two. A role's rubric is always loaded as ``paired``, so a generalist text
promoted in a role's place is refused.

**Where it lives, and who may read it.** ``knowledge/reviewers/<role>/rubric.md``,
in the one tree beneath the library that every session but a reviewer is refused
(the hook layer withholds the whole tree, rubrics not yet written included). It is
not in any role's always-loaded or required reading, so the library copy into a
target never takes it, and it counts against no role's ceiling.

**How it changes (ARCH-062: a change is a ledger event).** Only through the
knowledge layer's promotion command, run by a person at a terminal. Each
promotion appends a line carrying the file's sha256 as written. A rubric is loaded
only if its bytes are the ones its last promotion line names, so a direct edit is
refused at the next review rather than reviewed with. The digest is carried on
every review's record.

**What it must not say.** A reviewer is the one being measured by the
injected-error experiment. A rubric, and every library file a reviewer is shown,
is therefore held to the words that would tell a reader it is being evaluated,
or by what: the evaluation-revealing part of the instrument's telltale list. The
review vocabulary a rubric needs ("wrong", "incorrect", a named error class) stays
allowed: those words are the same for every artefact and say nothing about any
one of them.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from physgate.evaluation.inject.corpus import fold
from physgate.knowledge.promote import PROMOTIONS_NAME, rubric_path
from physgate.orchestrator.protocols import RubricSection
from physgate.reviewers.exceptions import ReviewError

#: The four sections, in order, as their second-level headings read, and the name a
#: verdict gives each.
SECTIONS: tuple[tuple[str, RubricSection], ...] = (
    ("Acceptance criteria", "acceptance_criteria"),
    ("Domain standard violations", "domain_standards"),
    ("Skill-file antipatterns", "antipatterns"),
    ("Reward-hacking indicators", "reward_hacking"),
)
#: The two sections a generalist review leaves out: the domain's own.
DOMAIN_SECTIONS: tuple[RubricSection, ...] = ("domain_standards", "antipatterns")
#: The line that stands under each left-out section's heading in a generalist rubric.
NOT_IN_REVIEW = "This section is not part of this review."
RubricKind = Literal["paired", "generalist"]
_NUMBERED = re.compile(r"^\d+\.\s+")
_ITEM = re.compile(r"^- \*\*(?P<id>[A-Z]{1,2}-?[0-9]+)\.\s*(?P<rest>.*)$")
#: The words that would tell a reviewer it is being evaluated, or by what. A subset
#: of the instrument's telltale list, matched the same way; a test holds it to that
#: list, so the two cannot drift apart.
EVALUATION_WORDS: tuple[str, ...] = (
    r"\binject",
    r"\bplanted\b",
    r"\bdeliberate",
    r"\bcorpus",
    r"\bcorpora\b",
    r"\banswer",
    r"\btwin\b",
    r"\bphysgate\b",
    r"\bphysics gate\b",
    r"\bexpected check\b",
)
_EVALUATION = re.compile("|".join(EVALUATION_WORDS))
_ROLE = re.compile(r"^[a-z][a-z0-9_]*$")

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class RubricError(ReviewError):
    """A rubric is missing, malformed, says what is measured, or is not its promoted version."""


class RubricItem(BaseModel):
    """One item of a rubric: its id, the section it sits in, and its title."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,2}-?[0-9]+$")]
    section: RubricSection
    title: str


class Rubric(BaseModel):
    """One role's rubric as loaded: its text, its items, and the digest every review carries."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    role: Annotated[str, StringConstraints(pattern=_ROLE.pattern)]
    text: Annotated[str, StringConstraints(min_length=1)]
    sha256: Sha256
    items: tuple[RubricItem, ...] = ()
    kind: RubricKind = "paired"


def evaluation_words(text: str) -> list[str]:
    """Every evaluation-revealing word in ``text``, as matched, sorted and each once."""
    return sorted({m.group(0) for m in _EVALUATION.finditer(fold(text))})


def _title(rest: str, lines: list[str], index: int) -> str:
    """An item's bold title: up to its closing ``**``, which may fall on a later line."""
    parts = [rest]
    following = index + 1
    while "**" not in parts[-1] and following < len(lines) and lines[following].strip():
        parts.append(lines[following].strip())
        following += 1
    return " ".join(parts).split("**", 1)[0].strip()


def parse_rubric(text: str, kind: RubricKind = "paired") -> tuple[RubricItem, ...]:
    """Every item of the rubric ``text``, in order, each with its section.

    Raises:
        RubricError: the required sections are not each present once, in order and
            after any preamble; a section the kind needs items in holds none (all
            four for ``paired``, the first and the fourth for ``generalist``), a
            generalist holds an item under a domain section, or another
            second-level section follows them; an item id appears twice; or the
            reward-hacking items leave an indicator out.
    """
    names = {title: name for title, name in SECTIONS}
    order = [title for title, _ in SECTIONS]
    seen: list[str] = []
    current: RubricSection | None = None
    items: list[RubricItem] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("## "):
            title = _NUMBERED.sub("", line[3:].strip())
            if title in names:
                seen.append(title)
                current = names[title]
            elif seen:
                msg = "no other second-level section follows the required ones"
                raise RubricError(msg, section=title)
            continue
        found = _ITEM.match(line)
        if found and current is not None:
            title = _title(found["rest"], lines, index)
            items.append(RubricItem(id=found["id"], section=current, title=title))
    if seen != order:
        msg = "a rubric has the four required sections, each once, in order"
        raise RubricError(msg, found=" | ".join(seen), expected=" | ".join(order))
    for _, name in SECTIONS:
        held = any(i.section == name for i in items)
        if kind == "generalist" and name in DOMAIN_SECTIONS:
            if held:
                msg = "a generalist rubric holds no item under a domain section"
                raise RubricError(msg, section=name)
        elif not held:
            msg = "a required section holds no item"
            raise RubricError(msg, section=name, kind=kind)
    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        twice = sorted({i for i in ids if ids.count(i) > 1})
        msg = "an item id appears twice"
        raise RubricError(msg, ids=",".join(twice))
    titles = [fold(i.title) for i in items if i.section == "reward_hacking"]
    named = {
        "feature isolation": any("feature isolation" in t for t in titles),
        "hard-coded values": any("hard coded values" in t for t in titles),
        "disabled checks": any("disabled" in t and "check" in t for t in titles),
    }
    missing = [name for name, present in named.items() if not present]
    if missing:
        msg = "the reward-hacking items leave an indicator out"
        raise RubricError(msg, missing=",".join(missing))
    return tuple(items)


def check_rubric(text: str, kind: RubricKind = "paired") -> tuple[RubricItem, ...]:
    """The items of ``text``, if it is a rubric ARCH-062 describes and says nothing it must not.

    Raises:
        RubricError: as :func:`parse_rubric`, or the text holds an
            evaluation-revealing word.
    """
    items = parse_rubric(text, kind)
    words = evaluation_words(text)
    if words:
        msg = "a rubric holds a word that would tell a reviewer it is being evaluated"
        raise RubricError(msg, found=",".join(words))
    return items


def promoted_digest(promotions_path: Path, role: str) -> str | None:
    """The digest the last promotion of ``role``'s rubric recorded, or ``None`` if none did."""
    path = Path(promotions_path)
    if not path.is_file():
        return None
    digest: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("kind") == "rubric" and event.get("domain") == role:
            recorded = event.get("sha256")
            digest = recorded if isinstance(recorded, str) else None
    return digest


def load_rubric(knowledge_root: Path, role: str) -> Rubric:
    """``role``'s rubric, if it is well formed and exactly its last promoted version.

    Raises:
        RubricError: the role name is unsafe; the file is missing or malformed
            (:func:`check_rubric`); or its bytes are not the ones its last
            promotion line recorded, including when no promotion recorded any.
    """
    if not _ROLE.fullmatch(role):
        msg = "a role name is a plain lower-case identifier"
        raise RubricError(msg, role=role)
    path = rubric_path(Path(knowledge_root), role)
    if path.is_symlink():
        msg = "the rubric is a link, so what is read is somewhere else than what was promoted"
        raise RubricError(msg, role=role, path=str(path))
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        msg = "the role has no rubric"
        raise RubricError(msg, role=role, path=str(path)) from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            msg = "the rubric is a link, so what is read is somewhere else than what was promoted"
            raise RubricError(msg, role=role, path=str(path)) from None
        raise
    with os.fdopen(fd, "rb") as handle:
        data = handle.read()
    text = data.decode("utf-8")
    items = check_rubric(text)
    digest = hashlib.sha256(data).hexdigest()
    promoted = promoted_digest(Path(knowledge_root) / PROMOTIONS_NAME, role)
    if promoted != digest:
        msg = "the rubric is not the version its last promotion recorded"
        raise RubricError(msg, role=role, found=digest, promoted=str(promoted))
    return Rubric(role=role, text=text, sha256=digest, items=items)


def generalist_of(rubric: Rubric) -> Rubric:
    """The generalist rubric for ``rubric``'s role: its two domain sections left out, by code.

    Each domain section's heading stays, followed by a blank line, :data:`NOT_IN_REVIEW`
    and a blank line; everything from the heading to the next second-level heading is
    dropped. Every other line is the paired rubric's, byte for byte, its canary line
    included. The same paired rubric always gives the same bytes.

    Raises:
        RubricError: ``rubric`` is not a paired rubric, or what is left is not a
            generalist rubric.
    """
    if rubric.kind != "paired":
        msg = "a generalist rubric is made from a role's paired rubric"
        raise RubricError(msg, role=rubric.role, kind=rubric.kind)
    names = {title: name for title, name in SECTIONS}
    kept: list[str] = []
    skipping = False
    for line in rubric.text.splitlines(keepends=True):
        if line.startswith("## "):
            title = _NUMBERED.sub("", line[3:].strip())
            skipping = names.get(title) in DOMAIN_SECTIONS
            kept.append(line)
            if skipping:
                kept.append(f"\n{NOT_IN_REVIEW}\n\n")
            continue
        if not skipping:
            kept.append(line)
    text = "".join(kept)
    items = check_rubric(text, "generalist")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Rubric(role=rubric.role, text=text, sha256=digest, items=items, kind="generalist")
