"""Exports held to their source: regenerated at the change check from the committed source alone.

A role commits a source file and the text exports a helper of the tool environment wrote from
it. The exports are the reviewer's evidence, so they must be what the source produces, not what
a role says it produces. At the change check each committed set is therefore made again from
the committed source, by the command the run's recorded tool environment names, inside the tool
containment, and compared byte for byte with what was committed.

**Where the command comes from.** One file at a root of the tool environment
(:data:`DERIVED_FILE`), written when the environment is provisioned and covered by its manifest
digest like every other file. It is read only once the environment has been held to the run's
record (the ``environment`` callable raises otherwise), for which files are sources as much as
for the command, strictly and bounded: per source suffix,
the products' suffixes (each a kind the commit-time rule shows in full), an argument list of
fixed words and named places only, a timeout, and the words for the exit codes the program
ends with on a source it refuses. This module names no tool; adding one adds an entry there.

**What is regenerated.** A source pairs with the products of the same name in the module's
exports folder (``<stem><suffix>``). Only a set the change touches (its source or any of its
products changed) is regenerated, so a change that touches none runs nothing. The source's
committed bytes alone are written at their module path in a folder made new for the call and
removed after any outcome; nothing else of the role's tree is put there or named on the
argument list.

**What refuses.** A source without its whole set, a product without its source, two sources of
one name, a source whose name is not of the safe shape (:data:`SAFE_NAME`), a product no
recorded entry makes, no recorded environment or one that does not hold its record, a command
that fails, times out, passes a bound of the runner's, writes a product over its kind's cap or
writes none, and any byte difference. A refusal names the file and says to regenerate; it never
quotes a file's content. A command that fails is refused by its exit code alone, in the
record's words for that code where it has them: nothing the command wrote, to its error stream
or anywhere else, is quoted into a refusal. Its output is the program's, and so under the
control of whatever it ran; no rewriting of it keeps every spelling of a withheld place out, so
none is attempted.

**What the machine does is a refusal too.** A folder or file that cannot be made, written or
read, a wrapper program that is gone, a git read that fails, a bound the runner holds: each
refuses the set with a short reason (the error's kind and the system's words for it, never a
path or a program's text), and nothing of it escapes the change check. Anything else is a fault
of this code and is raised as it is, so it is never taken for a pass.

**The argument list.** The name is placed only once it has the safe shape, and the core puts
the end of the options (``--``) before the first word that names the source, the module or the
name, so nothing a role chose can be read as an option, whatever the recorded program parses.

**What the check says.** Its result carries the number of sets made again and found equal: 0
when the change touched none, so "nothing to check" is told apart from "every set held".

This module decides and starts nothing: the runner it is given starts the command
(:mod:`physgate.oslayer.regeneration` by default, inside the tool containment).
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import stat
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from physgate.orchestrator.exceptions import GitError, InvocationError
from physgate.orchestrator.exports import EXPORTS_DIR, SHOWN_IN_FULL, cap_of, suffix_of
from physgate.orchestrator.git import GitDir, changes_between, git, git_blob
from physgate.orchestrator.session_files import FileRefused, read_beneath
from physgate.oslayer.containment import ContainmentError
from physgate.oslayer.regeneration import RegenerationBoundError
from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.record import ToolEnvironment
from physgate.toolenv.session import wire

#: The file at a root of the tool environment that names how exports are made again.
DERIVED_FILE = "derived.json"
#: The most bytes that file may hold.
MAX_DERIVED_BYTES = 64_000
#: The largest committed source that is regenerated from.
MAX_SOURCE_BYTES = 10_000_000
#: The most seconds one regeneration may be given.
MAX_TIMEOUT_S = 600
#: The most sets one change check makes again. A module is one board, or a board and a few
#: daughter boards; eight sets is a module with room to spare, and past it the change is
#: refused, never checked in part.
MAX_SETS_PER_CHECK = 8
#: The seconds all of one change check's regenerations share. A set takes about 8 s on CI, so
#: a full module takes about a minute; each run is given the lesser of its own timeout and
#: what is left, and a check that runs out refuses.
TOTAL_DEADLINE_S = 900.0
#: The most characters of the system's or the runner's own words a refusal carries.
MAX_SAID = 200
#: What a refusal says of a regeneration that ended with an exit code the record does not word:
#: one sentence for every such code. The number would be a few bits a set, chosen by whatever
#: the command ran, carried to the session that reads the refusal; it goes to the run's own
#: record instead (:attr:`ExportRefusal.exit_code`).
ENDED_WITH_AN_ERROR = "the program ended with an error"
#: The places an argument may name, and nothing else in braces.
PLACES = frozenset({"interpreter", "root", "source", "module", "name"})
#: The places whose words a role chose: the end of the options stands before the first of them.
ROLE_PLACES = frozenset({"source", "module", "name"})
#: The word that ends a program's options; the core places it, and a record may not.
END_OF_OPTIONS = "--"
#: The shape a source's name has before it is placed: no dash first, no space, nothing but
#: lower-case letters, digits, ``-`` and ``_``, at most 64 characters.
SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_PLACE = re.compile(r"\{([^{}]*)\}")
_SUFFIX = r"^\.[a-z0-9_]+(\.[a-z0-9_]+)?$"

Suffix = Annotated[str, StringConstraints(pattern=_SUFFIX)]
Words = Annotated[str, StringConstraints(min_length=1, max_length=300, pattern=r"^[ -~]+$")]

#: What runs one regeneration: the argument list, the folder made for it, its environment, the
#: seconds it is given and the recorded roots; its exit code (``None`` when it timed out) and
#: the end of its error stream. It raises
#: :class:`~physgate.oslayer.containment.ContainmentError` when the command cannot be contained.
Runner = Callable[
    [Sequence[str], Path, Mapping[str, str], float, Sequence[str]], tuple[int | None, str]
]


class DerivedError(RuntimeError):
    """The record of how exports are made again is refused."""


class Derivation(BaseModel):
    """One entry of the record: how one source suffix's exports are made again."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source: Suffix
    products: tuple[Suffix, ...] = Field(min_length=1, max_length=8)
    argv: tuple[Words, ...] = Field(min_length=1, max_length=32)
    timeout_s: int = Field(ge=1, le=MAX_TIMEOUT_S)
    refusals: dict[Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,2}$")], Words] = Field(
        default_factory=dict, max_length=16
    )

    @field_validator("products")
    @classmethod
    def _shown_kinds(cls, products: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(products)) != len(products) or not set(products) <= set(SHOWN_IN_FULL):
            msg = "each product is a different kind the commit-time rule shows in full"
            raise ValueError(msg)
        return products

    @field_validator("argv")
    @classmethod
    def _fixed_words(cls, argv: tuple[str, ...]) -> tuple[str, ...]:
        for word in argv:
            if any(name not in PLACES for name in _PLACE.findall(word)):
                msg = f"an argument names a placeholder outside {sorted(PLACES)}"
                raise ValueError(msg)
        if argv[0] != "{interpreter}" and not argv[0].startswith("{root}/"):
            msg = "the command is the interpreter or a program beneath the root"
            raise ValueError(msg)
        if END_OF_OPTIONS in argv:
            msg = "the end of the options is placed by the core, not by the record"
            raise ValueError(msg)
        return argv


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    derivations: tuple[Derivation, ...] = Field(min_length=1, max_length=8)


@dataclass(frozen=True)
class Recipe:
    """An entry of the record and the root it was read from."""

    root: str
    derivation: Derivation


@dataclass(frozen=True)
class ExportRefusal:
    """Why the committed exports are refused, and the path the refusal is keyed on."""

    reason: str
    subject: str
    #: The exit code of a regeneration that failed, for the run's own record that no session
    #: reads; never in :attr:`reason`, which a session reads. ``None`` for every other refusal.
    exit_code: int | None = None


@dataclass(frozen=True)
class HeldExports:
    """What the change check found of a commit's exports."""

    #: Why they are refused; ``None`` when every set the change touches held, or it touched none.
    refusal: ExportRefusal | None
    #: How many sets were made again from their committed sources and found equal to what was
    #: committed, before any refusal: 0 when the change touched none.
    regenerated: int = 0


#: What making a set again can meet that is the machine's, not this code's: a folder or file
#: that cannot be made, written or read (a wrapper program gone among them), a git read that
#: fails, a bound the runner holds. Each refuses the set; any other error is raised as it is.
_UNMADE: tuple[type[Exception], ...] = (OSError, GitError, RegenerationBoundError)


def read_derivations(recorded: ToolEnvironment) -> tuple[Recipe, ...]:
    """Every entry of the record at the recorded roots; a root without the file adds none.

    Read only once the environment has been held to the run's record.

    Raises:
        DerivedError: a file cannot be read, is no regular file, is too big, or is outside its
            shape; or two entries derive from one suffix or make one kind.
    """
    found: list[Recipe] = []
    for root in recorded.roots:
        path = Path(root) / DERIVED_FILE
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise DerivedError(_unreadable(path, exc)) from None
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DERIVED_BYTES:
            msg = f"{path} is no regular file of at most {MAX_DERIVED_BYTES} bytes"
            raise DerivedError(msg)
        try:
            record = _Record.model_validate_json(path.read_bytes())
        except OSError as exc:
            raise DerivedError(_unreadable(path, exc)) from None
        except ValidationError as exc:
            msg = f"{path} is outside its shape: {exc.errors()[0]['msg']}"
            raise DerivedError(msg) from None
        found += [Recipe(root=root, derivation=entry) for entry in record.derivations]
    sources = [recipe.derivation.source for recipe in found]
    products = [kind for recipe in found for kind in recipe.derivation.products]
    if len(set(sources)) != len(sources) or len(set(products)) != len(products):
        msg = "two entries of the record derive from one suffix or make one kind"
        raise DerivedError(msg)
    return tuple(found)


def _stem(name: str, suffix: str) -> str:
    return name[: -len(suffix)]


def _listed(repo: Path, commit: str, module: PurePosixPath, git_dir: GitDir | None) -> list[str]:
    """Every file path in ``module`` at ``commit``, as git lists them."""
    out = git(
        repo, "ls-tree", "-r", "-z", "--name-only", commit, "--", f"{module}/",
        objects_only=True, git_dir=git_dir, errors="surrogateescape",
    )  # fmt: skip
    return [path for path in out.split("\0") if path]


@dataclass(frozen=True)
class _Set:
    """A source's name in the module, its entry, and the sources and products of that name."""

    stem: str
    recipe: Recipe
    sources: tuple[str, ...]
    products: tuple[str, ...]


def _keys(path: str, module: PurePosixPath, recipes: Sequence[Recipe]) -> set[tuple[str, str]]:
    """The (source suffix, name) ``path`` is a source or a product of, if any."""
    pure = PurePosixPath(path)
    exports_dir = module / EXPORTS_DIR
    keys: set[tuple[str, str]] = set()
    for recipe in recipes:
        source = recipe.derivation.source
        if pure.name.endswith(source) and exports_dir not in pure.parents:
            keys.add((source, _stem(pure.name, source)))
        kind = suffix_of(path)
        if pure.parent == exports_dir and kind in recipe.derivation.products:
            keys.add((source, _stem(pure.name, kind)))
    return keys


def _sets(
    paths: Sequence[str], module: PurePosixPath, recipes: Sequence[Recipe]
) -> dict[tuple[str, str], _Set]:
    """Each (source suffix, name) the module holds a source or a product of, with them."""
    by_source = {recipe.derivation.source: recipe for recipe in recipes}
    members: dict[tuple[str, str], list[str]] = {}
    for path in paths:
        for key in _keys(path, module, recipes):
            members.setdefault(key, []).append(path)
    sets = {}
    for key in sorted(members):
        recipe = by_source[key[0]]
        held = sorted(members[key])
        products = [p for p in held if suffix_of(p) in recipe.derivation.products]
        sources = [p for p in held if p not in products]
        sets[key] = _Set(key[1], recipe, tuple(sources), tuple(products))
    return sets


def held_exports(  # noqa: PLR0913 - the change and the two ways to act on it
    repo: Path,
    base: str,
    commit: str,
    module_dir: str,
    *,
    environment: Callable[[], ToolEnvironment | None],
    runner: Runner,
    git_dir: GitDir | None = None,
) -> HeldExports:
    """Why the exports ``commit`` holds in ``module_dir`` are not what their sources produce.

    No refusal when every set the change from ``base`` touches regenerates to the committed
    bytes, or when it touches none; the result counts the sets made again and found equal. A
    change that touches nothing in the module asks for nothing. Otherwise ``environment``
    holds the run's tool environment to its record and gives it (``None`` for a run that names
    none), raising :class:`~physgate.orchestrator.exceptions.InvocationError` when it does not
    hold; which files are sources, and how each is made again, are read from the held
    environment, and only from it.
    """
    module = PurePosixPath(module_dir)
    picked = _picked(repo, base, commit, module, environment, git_dir)
    if isinstance(picked, ExportRefusal):
        return HeldExports(refusal=picked)
    deadline = time.monotonic() + TOTAL_DEADLINE_S
    for done, (found, held) in enumerate(picked):
        try:
            refusal = _regenerated(repo, commit, module, found, held, runner, git_dir, deadline)
        except _UNMADE as exc:
            refusal = _unmade(found.sources[0], exc)
        if refusal is not None:
            return HeldExports(refusal=refusal, regenerated=done)
    return HeldExports(refusal=None, regenerated=len(picked))


def _picked(  # noqa: PLR0911 - each refusal is its own return
    repo: Path,
    base: str,
    commit: str,
    module: PurePosixPath,
    environment: Callable[[], ToolEnvironment | None],
    git_dir: GitDir | None,
) -> ExportRefusal | list[tuple[_Set, ToolEnvironment]]:
    """The sets the change touches, each with the held environment, or why none may be made.

    Empty when the change asks for nothing: it touches nothing in the module, or the run names
    no tool environment and no export is shown.
    """
    exports_dir = module / EXPORTS_DIR
    changed = [c.path for c in changes_between(repo, base, commit, git_dir=git_dir)]
    changed = [path for path in changed if module in PurePosixPath(path).parents]
    if not changed:
        return []
    shown = [p for p in changed if PurePosixPath(p).parent == exports_dir]
    shown = [p for p in shown if suffix_of(p) in SHOWN_IN_FULL]
    first = (shown or changed)[0]
    try:
        held = environment()
    except InvocationError as exc:
        return ExportRefusal(
            reason=(
                "the run's tool environment does not hold its record, so which files are "
                f"sources of exports cannot be read, and the change to {first} is refused: {exc}"
            ),
            subject=first,
        )
    if held is None:
        if not shown:
            return []
        return ExportRefusal(
            reason=(
                f"{shown[0]} is an export made from a source, and the run records no tool "
                "environment to make it again, so it cannot be held to one"
            ),
            subject=shown[0],
        )
    try:
        recipes = read_derivations(held)
    except DerivedError as exc:
        return ExportRefusal(
            reason=(
                f"the tool environment's record of how exports are made is refused, so {first} "
                f"cannot be held to its source: {exc}"
            ),
            subject=first,
        )
    made = {kind for recipe in recipes for kind in recipe.derivation.products}
    unmade = [path for path in shown if suffix_of(path) not in made]
    if unmade:
        return ExportRefusal(
            reason=(
                f"{unmade[0]} is an export made from a source, and the run's tool environment "
                "names no way to make it again, so it cannot be held to one"
            ),
            subject=unmade[0],
        )
    keys = {key for path in changed for key in _keys(path, module, recipes)}
    sets = _sets(_listed(repo, commit, module, git_dir), module, recipes)
    # A set whose every file was removed is gone from the commit: nothing is left to hold.
    chosen = [sets[key] for key in sorted(keys) if key in sets]
    if len(chosen) > MAX_SETS_PER_CHECK:
        return ExportRefusal(
            reason=(
                f"the change touches {len(chosen)} sources with exports, and one change check "
                f"makes at most {MAX_SETS_PER_CHECK} sets again; commit fewer at a time"
            ),
            subject=(chosen[MAX_SETS_PER_CHECK].sources or chosen[MAX_SETS_PER_CHECK].products)[0],
        )
    for found in chosen:
        refusal = _paired(found, exports_dir)
        if refusal is None:
            refusal = _named(found)
        if refusal is not None:
            return refusal
    return [(found, held) for found in chosen]


def _named(found: _Set) -> ExportRefusal | None:
    """Why a set's name may not be placed on the argument list, if it may not."""
    if SAFE_NAME.fullmatch(found.stem):
        return None
    source = found.sources[0]
    return ExportRefusal(
        reason=(
            f"{source} has a name an export may not have: lower-case letters, digits, - and _, "
            "a letter or a digit first, at most 64 characters; rename it and regenerate"
        ),
        subject=source,
    )


def _unmade(source: str, exc: Exception) -> ExportRefusal:
    """The refusal of a set the machine stopped from being made again: short, and bounded."""
    return ExportRefusal(
        reason=(
            f"the exports of {source} could not be made again here ({_words_of(exc)}); the "
            "exports are refused"
        ),
        subject=source,
    )


def _words_of(exc: Exception) -> str:
    """The kind of ``exc``, and the system's or the runner's own words for it, cut to a line.

    Never a path or a program's text: an error of the system says its words (``strerror``),
    the runner's bound says the bound, and every other kind says its kind alone.
    """
    said = ""
    if isinstance(exc, RegenerationBoundError):
        said = str(exc)
    elif isinstance(exc, OSError):
        said = exc.strerror or ""
    said = last_line(said)
    return f"{type(exc).__name__}: {said}" if said else type(exc).__name__


def _unreadable(path: Path, exc: OSError) -> str:
    return f"{path} cannot be read ({_words_of(exc)})"


def _paired(found: _Set, exports_dir: PurePosixPath) -> ExportRefusal | None:
    """Why a set is not one source with all its products, if it is not."""
    derivation = found.recipe.derivation
    if len(found.sources) > 1:
        return ExportRefusal(
            reason=(
                f"{found.sources[1]} has the name of {found.sources[0]}, and a source's exports "
                "are named after it: give each source in the module a name of its own"
            ),
            subject=found.sources[1],
        )
    wanted = [f"{exports_dir}/{found.stem}{kind}" for kind in derivation.products]
    if not found.sources:
        first = next(path for path in wanted if path in found.products)
        return ExportRefusal(
            reason=(
                f"{first} has no source {found.stem}{derivation.source} in the module; exports "
                "are regenerated from their source at commit: commit the source and regenerate "
                "the exports with the helper, or remove them"
            ),
            subject=first,
        )
    missing = [path for path in wanted if path not in found.products]
    if missing:
        return ExportRefusal(
            reason=(
                f"{missing[0]} is missing: {found.sources[0]} is committed without its exports; "
                "regenerate them with the helper and commit what it writes"
            ),
            subject=missing[0],
        )
    return None


def _regenerated(  # noqa: PLR0913 - the one call's parts
    repo: Path,
    commit: str,
    module: PurePosixPath,
    found: _Set,
    recorded: ToolEnvironment,
    runner: Runner,
    git_dir: GitDir | None,
    deadline: float,
) -> ExportRefusal | None:
    """Make one set again from its committed source, in a folder made for it, and compare."""
    source = found.sources[0]
    spec = f"{commit}:{source}"
    size = int(git(repo, "cat-file", "-s", spec, objects_only=True, git_dir=git_dir))
    if size > MAX_SOURCE_BYTES:
        return ExportRefusal(
            reason=f"{source} is over {MAX_SOURCE_BYTES} bytes; its exports are not made again",
            subject=source,
        )
    work = Path(tempfile.mkdtemp(prefix="physgate-derived-"))
    try:
        placed = work / "module"
        target = placed / PurePosixPath(source).relative_to(module)
        target.parent.mkdir(parents=True)
        target.write_bytes(git_blob(repo, spec, git_dir=git_dir))
        return _run_and_compare(
            repo, commit, found, recorded, runner, git_dir, work, target, deadline
        )
    finally:
        _remove(work)


def _run_and_compare(  # noqa: PLR0911, PLR0913 - each refusal is its own return
    repo: Path,
    commit: str,
    found: _Set,
    recorded: ToolEnvironment,
    runner: Runner,
    git_dir: GitDir | None,
    work: Path,
    target: Path,
    deadline: float,
) -> ExportRefusal | None:
    source, derivation, placed = found.sources[0], found.recipe.derivation, work / "module"
    # The two directories this check made, as they are before the command runs: what is read
    # after it is read beneath these very ones, or not at all.
    made_here = [(info.st_dev, info.st_ino) for info in (os.lstat(work), os.lstat(placed))]
    try:
        env = _environment(recorded, work)
    except ToolEnvironmentError as exc:
        return ExportRefusal(
            reason=f"the exports of {source} cannot be made again: {exc}", subject=source
        )
    places = {
        "interpreter": recorded.interpreter,
        "root": found.recipe.root,
        "source": str(target),
        "module": str(placed),
        "name": found.stem,
    }
    argv = _argv(derivation.argv, places)
    left = deadline - time.monotonic()
    given = min(float(derivation.timeout_s), left)
    if given <= 0:
        return _out_of_time(source)
    try:
        # What the command said is never read here: only how it ended.
        code, _ = runner(argv, work, env, given, recorded.roots)
    except ContainmentError as exc:
        return ExportRefusal(
            reason=f"the exports of {source} cannot be made again here: {exc}", subject=source
        )
    if code is None and given < derivation.timeout_s:
        return _out_of_time(source)
    if code is None:
        return ExportRefusal(
            reason=(
                f"making the exports of {source} again timed out after {derivation.timeout_s} s; "
                "the exports are refused"
            ),
            subject=source,
        )
    if code != 0:
        # By kind, in closed words: the record's for a code it words, one sentence for any
        # other; never the number, never what the command said (see the module's docstring).
        words = derivation.refusals.get(str(code), ENDED_WITH_AN_ERROR)
        return ExportRefusal(
            reason=f"the exports of {source} could not be made again: {words}",
            subject=source,
            exit_code=code,
        )
    for path in found.products:
        refusal = _same(repo, commit, path, work, git_dir, source, made_here)
        if refusal is not None:
            return refusal
    return None


def _argv(words: Sequence[str], places: Mapping[str, str]) -> list[str]:
    """The record's words with each place filled in one pass, and the end of the options first.

    :data:`END_OF_OPTIONS` stands once, before the first word that names a place a role chose,
    so no such word is read as an option, whatever the program parses.
    """
    argv: list[str] = []
    ended = False
    for word in words:
        if not ended and ROLE_PLACES & set(_PLACE.findall(word)):
            argv.append(END_OF_OPTIONS)
            ended = True
        argv.append(_PLACE.sub(lambda m: places[m.group(1)], word))
    return argv


def last_line(said: str) -> str:
    """The last line of ``said`` that holds a printable character, at most :data:`MAX_SAID` long.

    Every character that is not printable is a space; a line cut short ends in an ellipsis.
    """
    lines = ["".join(c if c.isprintable() else " " for c in line) for line in said.splitlines()]
    lines = [line.strip() for line in lines if line.strip()]
    if not lines:
        return ""
    return lines[-1] if len(lines[-1]) <= MAX_SAID else lines[-1][: MAX_SAID - 1] + "…"


def _out_of_time(source: str) -> ExportRefusal:
    return ExportRefusal(
        reason=(
            f"the change check's deadline of {TOTAL_DEADLINE_S:g} s for making exports again ran "
            f"out at {source}; the exports are refused: commit fewer sources at a time"
        ),
        subject=source,
    )


def _same(  # noqa: PLR0913 - the committed file, the made one and where they come from
    repo: Path,
    commit: str,
    path: str,
    work: Path,
    git_dir: GitDir | None,
    source: str,
    made_here: Sequence[tuple[int, int]],
) -> ExportRefusal | None:
    """Why the committed ``path`` is not the file made again in ``work``, if it is not.

    The file made again is ``work/module/exports/<name>``, opened beneath ``work`` one part at a
    time with no link followed on the way or at the end (``session_files.open_beneath``), the
    folder and its ``module`` held to the very directories this check made (``made_here``), and
    read no further than its kind's cap: the command chose what it left there, a link among it,
    and nothing outside its folder is read for it, whatever it named. Anything that is not one
    regular file of one name there was not written; one over the cap is over it.
    """
    cap = cap_of(path)
    names = ("module", EXPORTS_DIR, PurePosixPath(path).name)
    try:
        made = read_beneath(work, names, limit=cap, identity=made_here)
    except FileRefused as refused:
        if refused.kind == "too_large":
            return ExportRefusal(
                reason=f"{path} made again from {source} is over its kind's cap of {cap} bytes",
                subject=path,
            )
        return ExportRefusal(
            reason=f"{path} was not written when the exports of {source} were made again",
            subject=path,
        )
    if made != git_blob(repo, f"{commit}:{path}", git_dir=git_dir):
        return ExportRefusal(
            reason=(
                f"{path} is not what {source} produces at this commit; regenerate the exports "
                "with the helper from the committed source and commit what it writes"
            ),
            subject=path,
        )
    return None


def _environment(recorded: ToolEnvironment, work: Path) -> dict[str, str]:
    """The regeneration's environment: the recorded tool environment wired into ``work``."""
    temp, home = work / "temp", work / "home"
    temp.mkdir()
    home.mkdir()
    taken = ("PATH", "HOME", "TMPDIR", "LANG")
    variables = wire(recorded, bin_dir=work / "bin", temp=temp, taken=taken)
    return {
        "PATH": f"{work / 'bin'}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(home),
        "TMPDIR": str(temp),
        "LANG": "C.UTF-8",
        **variables,
    }


def _remove(work: Path) -> None:
    """Remove the folder made for a regeneration, whatever the program left read-only in it."""
    for folder, directories, _files in os.walk(work):
        for name in directories:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                # Gone since it was listed, or not this module's to change: left as it is.
                with contextlib.suppress(OSError):
                    os.chmod(path, 0o700)  # noqa: S103 - a folder this module made
    shutil.rmtree(work, ignore_errors=True)
