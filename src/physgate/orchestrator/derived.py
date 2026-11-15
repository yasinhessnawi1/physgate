"""Exports held to their source: regenerated at the change check from the committed source alone.

A role commits a source file and the text exports a helper of the tool environment wrote from
it. The exports are the reviewer's evidence, so they must be what the source produces, not what
a role says it produces. At the change check each committed set is therefore made again from
the committed source, by the command the run's recorded tool environment names, inside the tool
containment, and compared byte for byte with what was committed.

**Where the command comes from.** One file at a root of the tool environment
(:data:`DERIVED_FILE`), written when the environment is provisioned and covered by its manifest
digest like every other file. It is read only once the environment has been held to the run's
record (the ``environment`` callable raises otherwise), strictly and bounded: per source suffix,
the products' suffixes (each a kind the commit-time rule shows in full), an argument list of
fixed words and named places only, a timeout, and the words for the exit codes the program
ends with on a source it refuses. This module names no tool; adding one adds an entry there.

**What is regenerated.** A source pairs with the products of the same name in the module's
exports folder (``<stem><suffix>``). Only a set the change touches (its source or any of its
products changed) is regenerated, so a change that touches none pays nothing. The source's
committed bytes alone are written at their module path in a folder made new for the call and
removed after any outcome; nothing else of the role's tree is put there or named on the
argument list.

**What refuses.** A source without its whole set, a product without its source, two sources of
one name, a product no recorded entry makes, no recorded environment or one that does not hold
its record, a command that fails, times out, writes a product over its kind's cap or writes
none, and any byte difference. A refusal names the file and says to regenerate; it never
quotes a file's content or the program's output.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
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

from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.exports import EXPORTS_DIR, SHOWN_IN_FULL, cap_of, suffix_of
from physgate.orchestrator.git import GitDir, changes_between, git, git_blob
from physgate.oslayer.containment import (
    SANDBOX_EXEC,
    ContainmentError,
    bwrap_args,
    seatbelt_profile,
)
from physgate.oslayer.policy import board_devices
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
#: The places an argument may name, and nothing else in braces.
PLACES = frozenset({"interpreter", "root", "source", "module", "name"})
_PLACE = re.compile(r"\{([^{}]*)\}")
_SUFFIX = r"^\.[a-z0-9_]+(\.[a-z0-9_]+)?$"

Suffix = Annotated[str, StringConstraints(pattern=_SUFFIX)]
Words = Annotated[str, StringConstraints(min_length=1, max_length=300, pattern=r"^[ -~]+$")]

#: What runs one regeneration: the argument list, the folder made for it, its environment, the
#: seconds it is given and the recorded roots; its exit code, or ``None`` when it timed out.
Runner = Callable[[Sequence[str], Path, Mapping[str, str], float, Sequence[str]], int | None]


class DerivedError(RuntimeError):
    """The record of how exports are made again is refused, or cannot be run here."""


class Derivation(BaseModel):
    """One entry of the record: how one source suffix's exports are made again."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source: Suffix
    products: tuple[Suffix, ...] = Field(min_length=1, max_length=8)
    argv: tuple[Words, ...] = Field(min_length=1, max_length=32)
    timeout_s: int = Field(ge=1, le=MAX_TIMEOUT_S)
    refusals: dict[Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,2}$")], Words] = (
        Field(default_factory=dict, max_length=16)
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


def read_derivations(recorded: ToolEnvironment) -> tuple[Recipe, ...]:
    """Every entry of the record at the recorded roots; a root without the file adds none.

    Read only once the environment has been held to the run's record.

    Raises:
        DerivedError: a file is no regular file, is too big, or is outside its shape; or two
            entries derive from one suffix or make one kind.
    """
    found: list[Recipe] = []
    for root in recorded.roots:
        path = Path(root) / DERIVED_FILE
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DERIVED_BYTES:
            msg = f"{path} is no regular file of at most {MAX_DERIVED_BYTES} bytes"
            raise DerivedError(msg)
        try:
            record = _Record.model_validate_json(path.read_bytes())
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


def contained_runner(*, platform: str = sys.platform, bwrap: str | None = None) -> Runner:
    """The runner the change check uses: the command inside the tool containment.

    Reads only the recorded roots (and the system's own places), writes only the folder made
    for the call, no network: on Linux bubblewrap at ``bwrap`` (``None``: there is none, and
    every regeneration is refused), on macOS a generated Seatbelt profile written outside that
    folder.
    """
    wrapper = bwrap

    def run(
        argv: Sequence[str],
        work: Path,
        env: Mapping[str, str],
        timeout_s: float,
        roots: Sequence[str],
    ) -> int | None:
        profiles: str | None = None
        try:
            if platform.startswith("linux"):
                if wrapper is None:
                    msg = "no bubblewrap on this machine contains the regeneration"
                    raise DerivedError(msg)
                options = bwrap_args(read_denied=(), server_dir=str(work), read_roots=roots)
                command = [wrapper, *options, "--", *argv]
            elif platform == "darwin":
                profiles = tempfile.mkdtemp(prefix="physgate-derived-profile-")
                profile = Path(profiles) / "regenerate.sb"
                profile.write_text(
                    seatbelt_profile(
                        read_denied=(),
                        server_dir=str(work),
                        devices=board_devices(platform),
                        command=argv[0],
                        exec_roots=roots,
                        read_roots=roots,
                    ),
                    encoding="utf-8",
                )
                command = [SANDBOX_EXEC, "-f", str(profile), *argv]
            else:
                msg = f"no wrapper contains the regeneration on {platform}"
                raise DerivedError(msg)
            return _run(command, work, env, timeout_s)
        except ContainmentError as exc:
            raise DerivedError(str(exc)) from None
        finally:
            if profiles is not None:
                shutil.rmtree(profiles, ignore_errors=True)

    return run


def _run(
    command: Sequence[str], work: Path, env: Mapping[str, str], timeout_s: float
) -> int | None:
    try:
        done = subprocess.run(  # noqa: S603 - the recorded command, inside its wrapper
            list(command),
            cwd=work,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    return done.returncode


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


def held_exports(  # noqa: PLR0913 - the change, the record and the two ways to act on it
    repo: Path,
    base: str,
    commit: str,
    module_dir: str,
    *,
    recorded: ToolEnvironment | None,
    environment: Callable[[], ToolEnvironment | None],
    runner: Runner,
    git_dir: GitDir | None = None,
) -> ExportRefusal | None:
    """Why the exports ``commit`` holds in ``module_dir`` are not what their sources produce.

    ``None`` when every set the change from ``base`` touches regenerates to the committed
    bytes, or when it touches none. ``recorded`` is the run's record of its tool environment
    (``None`` for a run that names none); its file is read here only to learn which suffixes
    are sources, so a change touching no source and no export asks for nothing. Otherwise
    ``environment`` holds the environment to that record and gives it (``None`` for a run that
    names none), raising :class:`~physgate.orchestrator.exceptions.InvocationError` when it
    does not hold; the command is read again from the held environment, and only from it.
    """
    module = PurePosixPath(module_dir)
    exports_dir = module / EXPORTS_DIR
    changed = [c.path for c in changes_between(repo, base, commit, git_dir=git_dir)]
    changed = [path for path in changed if module in PurePosixPath(path).parents]
    try:
        sources = {r.derivation.source for r in read_derivations(recorded)} if recorded else set()
    except DerivedError:
        sources = set()
    shown = [p for p in changed if PurePosixPath(p).parent == exports_dir]
    shown = [p for p in shown if suffix_of(p) in SHOWN_IN_FULL]
    named = [p for p in changed if any(PurePosixPath(p).name.endswith(s) for s in sources)]
    touched = shown + [p for p in named if p not in shown]
    if not touched:
        return None
    try:
        held = environment()
    except InvocationError as exc:
        return ExportRefusal(
            reason=f"the exports cannot be made again from their sources: {exc}",
            subject=touched[0],
        )
    if held is None:
        if not shown:
            return None
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
            reason=f"the tool environment's record of how exports are made is refused: {exc}",
            subject=touched[0],
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
        if refusal is not None:
            return refusal
    deadline = time.monotonic() + TOTAL_DEADLINE_S
    for found in chosen:
        refusal = _regenerated(repo, commit, module, found, held, runner, git_dir, deadline)
        if refusal is not None:
            return refusal
    return None


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
    argv = [_PLACE.sub(lambda m: places[m.group(1)], word) for word in derivation.argv]
    left = deadline - time.monotonic()
    given = min(float(derivation.timeout_s), left)
    if given <= 0:
        return _out_of_time(source)
    try:
        code = runner(argv, work, env, given, recorded.roots)
    except DerivedError as exc:
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
        words = derivation.refusals.get(str(code), f"the program ended with exit code {code}")
        return ExportRefusal(
            reason=f"the exports of {source} could not be made again: {words}", subject=source
        )
    for path in found.products:
        made = placed / EXPORTS_DIR / PurePosixPath(path).name
        refusal = _same(repo, commit, path, made, git_dir, source)
        if refusal is not None:
            return refusal
    return None


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
    made: Path,
    git_dir: GitDir | None,
    source: str,
) -> ExportRefusal | None:
    """Why the committed ``path`` is not the file made again at ``made``, if it is not."""
    if made.is_symlink() or not made.is_file():
        return ExportRefusal(
            reason=f"{path} was not written when the exports of {source} were made again",
            subject=path,
        )
    cap = cap_of(path)
    if made.stat().st_size > cap:
        return ExportRefusal(
            reason=f"{path} made again from {source} is over its kind's cap of {cap} bytes",
            subject=path,
        )
    if made.read_bytes() != git_blob(repo, f"{commit}:{path}", git_dir=git_dir):
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
                os.chmod(path, 0o700)  # noqa: S103 - a folder this module made
    shutil.rmtree(work, ignore_errors=True)
